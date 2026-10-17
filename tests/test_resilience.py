"""Stop must work at every stage, and slow or failing searches must say so clearly."""
import logging
import threading
import time

import pytest

from skrapkin import config, discover, jobs
from skrapkin.discover import AreaTooLarge, Cancelled, DiscoveryError, ServiceBusy
from skrapkin.web import create_app
from skrapkin.web.__main__ import startup_notice

H = {"X-Skrapkin": "1"}


class Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self._body = status, body if body is not None else {"elements": []}
        self.ok = status < 400

    def json(self):
        return self._body


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(discover, "POLL_SECONDS", 0.02)


def run(**kw):
    return discover.discover("toys", "US", "Texas", **kw)


# ---- the discovery request ---------------------------------------------------------------------

def test_stop_interrupts_a_slow_request_within_a_moment(monkeypatch):
    monkeypatch.setattr(discover.requests, "post", lambda *a, **k: time.sleep(5) or Resp())
    stop_at = time.monotonic() + 0.2
    started = time.monotonic()
    with pytest.raises(Cancelled):
        run(should_stop=lambda: time.monotonic() > stop_at)
    assert time.monotonic() - started < 1.5


def test_stop_also_interrupts_the_wait_between_retries(monkeypatch):
    monkeypatch.setattr(discover.requests, "post", lambda *a, **k: Resp(504))
    flag = {"stop": False}
    threading.Timer(0.3, lambda: flag.update(stop=True)).start()
    started = time.monotonic()
    with pytest.raises(Cancelled):
        run(should_stop=lambda: flag["stop"])
    assert time.monotonic() - started < 2


def test_a_timeout_note_with_no_results_is_explained_not_retried(monkeypatch):
    calls = []
    note = 'runtime error: Query timed out in "query" at line 5 after 61 seconds.'
    monkeypatch.setattr(discover.requests, "post", lambda *a, **k: calls.append(1) or Resp(200, {"elements": [], "remark": note}))
    with pytest.raises(AreaTooLarge, match="too large"):
        run()
    assert len(calls) == 1          # repeating a query that timed out would only time out again


def test_partial_results_are_kept_when_the_server_adds_a_note(monkeypatch):
    body = {"elements": [{"tags": {"name": "Acme", "website": "https://acme.com"}}], "remark": "runtime error: out of memory"}
    monkeypatch.setattr(discover.requests, "post", lambda *a, **k: Resp(200, body))
    assert [l["business"] for l in run()] == ["Acme"]


def test_a_genuinely_empty_area_is_not_an_error_once_two_answers_agree(monkeypatch):
    calls = []
    monkeypatch.setattr(discover.requests, "post", lambda url, **k: calls.append(url) or Resp(200, {"elements": []}))
    assert run() == []
    assert len(calls) == 2 and calls[0] != calls[1]      # confirmed on the other server before believing it


def test_one_wrong_empty_answer_does_not_hide_the_real_results(monkeypatch):
    real = {"elements": [{"tags": {"name": "Acme", "website": "https://acme.com"}}]}
    monkeypatch.setattr(discover.requests, "post",
                        lambda url, **k: Resp(200, {"elements": []}) if url == discover.OVERPASS_URLS[0] else Resp(200, real))
    assert [l["business"] for l in run()] == ["Acme"]


def test_busy_servers_are_retried_on_both_mirrors_then_reported_plainly(monkeypatch):
    calls = []
    monkeypatch.setattr(discover.requests, "post", lambda url, **k: calls.append(url) or Resp(504))
    monkeypatch.setattr(discover, "_pause", lambda s, should_stop: None)
    with pytest.raises(ServiceBusy, match="HTTP 504"):
        run()
    assert len(calls) == 3 * len(discover.OVERPASS_URLS) and set(calls) == set(discover.OVERPASS_URLS)


def test_a_rejected_query_is_not_retried(monkeypatch):
    calls = []
    monkeypatch.setattr(discover.requests, "post", lambda *a, **k: calls.append(1) or Resp(400))
    with pytest.raises(DiscoveryError, match="rejected"):
        run()
    assert len(calls) == 1


def test_it_reports_progress_while_waiting(monkeypatch):
    monkeypatch.setattr(discover, "WAIT_REPORT_SECONDS", 0.1)
    monkeypatch.setattr(discover.requests, "post", lambda *a, **k: time.sleep(0.5) or Resp())
    waits = []
    run(on_wait=waits.append)
    assert len(waits) >= 2 and waits == sorted(waits)


def test_whole_country_searches_get_a_shorter_server_limit(monkeypatch):
    sent = []
    one = {"elements": [{"tags": {"name": "Acme", "website": "https://acme.com"}}]}
    monkeypatch.setattr(discover.requests, "post", lambda url, data, **k: sent.append(data["data"]) or Resp(200, one))
    discover.discover("toys", "US")
    discover.discover("toys", "US", "Texas")
    discover.discover("toys", "US", None, "Austin")
    assert "[timeout:45]" in sent[0] and "[timeout:120]" in sent[1] and "[timeout:120]" in sent[2]


# ---- the pipeline and the web app ---------------------------------------------------------------

def test_stopping_during_discovery_ends_the_pipeline_cleanly(monkeypatch, tmp_path):
    def cancelled(args, log, should_stop=None):
        raise Cancelled()

    monkeypatch.setattr(jobs, "cmd_discover", cancelled)
    monkeypatch.setattr(jobs, "cmd_scrape", lambda *a, **k: pytest.fail("must not scrape after a stop"))
    logs = []
    s = jobs.Settings(category="toys", country="US", region="Texas", output_dir=tmp_path)
    assert jobs.run_pipeline(s, logs.append, None, lambda: True) == (None, 0)
    assert "Stopped." in logs


@pytest.fixture
def client(database, monkeypatch, tmp_path):
    monkeypatch.setenv("SKRAPKIN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SKRAPKIN_OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.setattr(config, "keyring", None)
    app = create_app(cfg=config.Config(), connect=False)
    svc = app.extensions["skrapkin"]
    svc.db, svc.connected, svc.refresh = database, True, lambda: None
    return app.test_client()


GOOD = {"category": "toys", "country": "US", "region": "Texas", "min_confidence": "low", "max_businesses": 20}


def wait_for(client, task_id, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        snap = client.get(f"/api/tasks/{task_id}").get_json()
        if snap["state"] != "running":
            return snap
        time.sleep(0.02)
    raise AssertionError("task did not finish: Stop was ignored")


def test_the_stop_button_works_while_waiting_on_openstreetmap(client, monkeypatch):
    def slow_discover(args, log, should_stop=None):
        while not should_stop():          # stands in for a long wait on the Overpass server
            time.sleep(0.02)
        raise Cancelled()

    monkeypatch.setattr(jobs, "cmd_discover", slow_discover)
    task = client.post("/api/find", json=GOOD, headers=H).get_json()["task"]
    time.sleep(0.2)
    assert client.get(f"/api/tasks/{task}").get_json()["state"] == "running"
    client.post(f"/api/tasks/{task}/stop", headers=H)
    assert wait_for(client, task)["state"] == "stopped"
    # and a new search can start straight away
    monkeypatch.setattr(jobs, "cmd_discover", lambda a, log, should_stop=None: 0)
    assert client.post("/api/find", json=GOOD, headers=H).status_code == 202


def test_area_too_large_is_explained_in_the_task_error(client, monkeypatch):
    def too_big(args, log, should_stop=None):
        raise AreaTooLarge("That area is too large for the free OpenStreetMap server to search in time. "
                           "Choose a region or a city and try again.")

    monkeypatch.setattr(jobs, "cmd_discover", too_big)
    snap = wait_for(client, client.post("/api/find", json=GOOD, headers=H).get_json()["task"])
    assert snap["state"] == "error" and "too large" in snap["error"] and "Something went wrong" not in snap["error"]


def test_task_outcomes_are_written_to_the_server_log(client, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="skrapkin.tasks")

    def too_big(args, log, should_stop=None):
        raise AreaTooLarge("too large")

    monkeypatch.setattr(jobs, "cmd_discover", too_big)
    wait_for(client, client.post("/api/find", json=GOOD, headers=H).get_json()["task"])
    time.sleep(0.1)
    text = caplog.text
    assert "started" in text and "failed: too large" in text and "error after" in text
    assert "Traceback" not in text                      # an expected failure gets no scary traceback

    caplog.clear()
    monkeypatch.setattr(jobs, "cmd_discover", lambda a, log, should_stop=None: 1 / 0)
    wait_for(client, client.post("/api/find", json=GOOD, headers=H).get_json()["task"])
    time.sleep(0.1)
    assert "crashed" in caplog.text and "ZeroDivisionError" in caplog.text   # a real bug does


# ---- startup message ----------------------------------------------------------------------------

def test_startup_notice_does_not_cry_wolf_in_a_default_container():
    assert startup_notice("127.0.0.1", "", False, False) is None
    assert startup_notice("0.0.0.0", "s3cret", False, False) is None
    calm = startup_notice("0.0.0.0", "", True, False)
    assert "WARNING" not in calm and "this computer only" in calm


def test_startup_notice_warns_when_it_is_really_exposed():
    assert "WARNING" in startup_notice("0.0.0.0", "", False, False)           # plain `python -m skrapkin.web`
    assert "WARNING" in startup_notice("0.0.0.0", "", True, True)             # container meant to be shared


# ---- slow replies fail fast instead of being retried -----------------------------------------------

def test_a_whole_country_search_that_gets_no_answer_fails_after_one_attempt(monkeypatch):
    calls = []

    def hang(url, **k):
        calls.append(url)
        raise discover.requests.ReadTimeout()

    monkeypatch.setattr(discover.requests, "post", hang)
    with pytest.raises(AreaTooLarge, match="too large"):
        discover.discover("toys", "US")
    assert len(calls) == 1


def test_a_regional_search_gets_one_more_try_on_the_other_server_then_fails(monkeypatch):
    calls = []

    def hang(url, **k):
        calls.append(url)
        raise discover.requests.ReadTimeout()

    monkeypatch.setattr(discover.requests, "post", hang)
    with pytest.raises(AreaTooLarge):
        discover.discover("toys", "US", "Texas")
    assert len(calls) == 2 and calls[0] != calls[1]


def test_a_regional_search_can_succeed_on_the_second_server(monkeypatch):
    def first_hangs_second_answers(url, **k):
        if url == discover.OVERPASS_URLS[0]:
            raise discover.requests.ReadTimeout()
        return Resp(200, {"elements": [{"tags": {"name": "Acme", "website": "https://acme.com"}}]})

    monkeypatch.setattr(discover.requests, "post", first_hangs_second_answers)
    assert [l["business"] for l in discover.discover("toys", "US", "Texas")] == ["Acme"]
