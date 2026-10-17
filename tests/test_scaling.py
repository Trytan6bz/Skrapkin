"""Parallel scraping, politeness, and 'continue where I left off'."""
import csv
import threading
import time
from argparse import Namespace
from datetime import timedelta

import pytest

from skrapkin import cli, config, jobs
from skrapkin import fetcher as fetcher_module
from skrapkin.db import now, seed_key
from skrapkin.fetcher import Fetcher
from skrapkin.web import create_app


# ---- the fetcher stays polite when shared between threads ---------------------------------------------

class FakeResponse:
    def __init__(self, status=200, text="<html></html>"):
        self.status_code, self.text, self.headers = status, text, {"Content-Type": "text/html"}


class RecordingSession:
    instances, hits = [], []

    def __init__(self):
        self.headers = {}
        RecordingSession.instances.append(self)

    def get(self, url, timeout=None):
        if url.endswith("/robots.txt"):
            return FakeResponse(404)
        RecordingSession.hits.append((url, time.monotonic(), threading.get_ident()))
        return FakeResponse()


@pytest.fixture
def recording(monkeypatch):
    RecordingSession.instances, RecordingSession.hits = [], []
    monkeypatch.setattr(fetcher_module.requests, "Session", RecordingSession)
    return RecordingSession


def test_one_site_is_never_hit_faster_than_the_delay_even_from_two_threads(recording):
    f = Fetcher(delay=0.25)
    threads = [threading.Thread(target=f.get, args=(f"https://acme.com/p{i}",)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    times = sorted(t for _, t, _ in recording.hits)
    assert len(times) == 3
    assert all(b - a >= 0.22 for a, b in zip(times, times[1:])), times


def test_different_sites_do_not_wait_for_each_other(recording):
    f = Fetcher(delay=0.5)
    start = time.monotonic()
    threads = [threading.Thread(target=f.get, args=(f"https://site{i}.com/",)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert time.monotonic() - start < 0.4          # eight first visits in parallel, none delayed


def test_each_thread_gets_its_own_http_session(recording):
    f = Fetcher(delay=0)
    sessions = set()

    def fetch():
        f.get("https://x.com/")
        sessions.add(id(f.session))

    threads = [threading.Thread(target=fetch) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(sessions) == 4


# ---- parallel scraping ------------------------------------------------------------------------------

def seeds_file(tmp_path, n=16, extra=None):
    extra = extra or {}
    path = tmp_path / "seeds.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cli.SEED_FIELDS)
        w.writeheader()
        for i in range(n):
            row = {"category": "toys", "business": f"Shop {i}", "website": f"https://shop{i}.com", "phone": "",
                   "email": "", "city": "X", "brand": "", "country": "US", "region": "Ohio"}
            row.update(extra.get(i, {}))
            w.writerow(row)
    return path


def scrape_args(path, out, **kw):
    base = dict(seeds=str(path), output=str(out), delay=0, max_pages=2, exclude_personal=False, any_domain=False,
                country="US", min_confidence="low", keep_chains=False, workers=8, save_db=False)
    return Namespace(**{**base, **kw})


@pytest.fixture
def fake_sites(monkeypatch):
    """Replace the network: each site takes `delay` seconds and has one email on its own domain."""
    state = {"delay": 0.3, "calls": [], "fail": set(), "empty": set(), "reverse": False}

    def scrape_site(fetcher, url, max_pages, include_personal, any_domain=False, region="US", should_stop=lambda: False, **kw):
        n = int(url.split("shop")[1].split(".")[0])
        state["calls"].append(n)
        time.sleep(state["delay"] * ((16 - n) / 16 if state["reverse"] else 1))
        if n in state["fail"]:
            raise RuntimeError("boom")
        if n in state["empty"]:
            return None
        return {"name": f"Shop {n}", "emails": {f"info@shop{n}.com"}, "phones": set(), "pages": [url]}

    monkeypatch.setattr(cli, "scrape_site", scrape_site)
    monkeypatch.setattr(cli, "mx_status", lambda d: "ok")
    return state


def read_leads(path):
    return list(csv.DictReader(open(path, encoding="utf-8-sig")))


def test_eight_workers_are_much_faster_than_one(tmp_path, fake_sites):
    path = seeds_file(tmp_path)
    t = time.monotonic()
    assert cli.cmd_scrape(scrape_args(path, tmp_path / "a.csv", workers=8), log=lambda m: None) == 16
    parallel = time.monotonic() - t
    t = time.monotonic()
    assert cli.cmd_scrape(scrape_args(path, tmp_path / "b.csv", workers=1), log=lambda m: None) == 16
    sequential = time.monotonic() - t
    assert sequential > 4.0 and parallel < 1.6 and sequential / parallel > 3


def test_output_keeps_seed_order_even_when_sites_finish_out_of_order(tmp_path, fake_sites):
    fake_sites["reverse"] = True          # the first seeds are the slowest, so they finish last
    path = seeds_file(tmp_path)
    cli.cmd_scrape(scrape_args(path, tmp_path / "o.csv"), log=lambda m: None)
    assert [r["business"] for r in read_leads(tmp_path / "o.csv")] == [f"Shop {i}" for i in range(16)]


def test_progress_reaches_the_total_and_never_goes_backwards(tmp_path, fake_sites):
    fake_sites["delay"] = 0.05
    seen = []
    path = seeds_file(tmp_path, extra={0: {"brand": "Chainy"}, 1: {"business": "Gewerkschaft Bau"}})
    cli.cmd_scrape(scrape_args(path, tmp_path / "p.csv"), log=lambda m: None, progress=lambda d, t: seen.append((d, t)))
    assert seen[-1] == (16, 16) and all(t == 16 for _, t in seen)
    assert [d for d, _ in seen] == sorted(d for d, _ in seen)


def test_stop_returns_quickly_with_partial_results_and_no_late_callbacks(tmp_path, fake_sites):
    fake_sites["delay"] = 0.4
    path = seeds_file(tmp_path, n=16)
    leads, logs = [], []
    started = time.monotonic()
    stop_at = started + 0.6
    count = cli.cmd_scrape(scrape_args(path, tmp_path / "s.csv", workers=2), log=logs.append,
                           should_stop=lambda: time.monotonic() > stop_at, on_lead=leads.append)
    assert time.monotonic() - started < 2.0                 # not the 3.2s that finishing would take
    assert 0 < count < 16 and "Stopped early; saving what was found so far." in logs
    seen_at_stop = len(leads)
    time.sleep(0.9)                                         # abandoned workers finish in the background...
    assert len(leads) == seen_at_stop                       # ...but nothing more is delivered
    assert len(read_leads(tmp_path / "s.csv")) == count


def test_one_failing_site_does_not_sink_the_run_and_is_retried_later(tmp_path, fake_sites):
    fake_sites["delay"] = 0.01
    fake_sites["fail"] = {3}
    checked, logs = [], []
    path = seeds_file(tmp_path)
    count = cli.cmd_scrape(scrape_args(path, tmp_path / "e.csv"), log=logs.append,
                           on_checked=lambda seed, outcome: checked.append((seed["business"], outcome)))
    assert count == 15 and any("could not check Shop 3" in m for m in logs)
    assert "Shop 3" not in [b for b, _ in checked]          # not remembered, so the next run tries it again
    assert len(checked) == 15


def test_every_decision_is_remembered_with_its_outcome(tmp_path, fake_sites):
    fake_sites["delay"] = 0.01
    fake_sites["empty"] = {5}                               # unreachable site, nothing else to go on
    path = seeds_file(tmp_path, n=8, extra={0: {"brand": "Chainy"}, 1: {"business": "Escuela Técnica"},
                                           2: {"website": "https://shop3.com"}})   # shop 2 and shop 3 share a site
    outcomes = {}
    cli.cmd_scrape(scrape_args(path, tmp_path / "c.csv"), log=lambda m: None,
                   on_checked=lambda seed, outcome: outcomes.update({seed["business"] + seed["website"][-9:]: outcome}))
    assert outcomes["Shop 0shop0.com"] == "chain" and outcomes["Escuela Técnicashop1.com"] == "non_buyer"
    assert outcomes["Shop 5shop5.com"] == "no_contact" and outcomes["Shop 4shop4.com"] == "lead"
    assert outcomes["Shop 2shop3.com"] == "lead"            # first entry for shop3.com does the work...
    assert "Shop 3shop3.com" not in outcomes                # ...so the later entry for the same site is skipped
    assert len(outcomes) == 7                               # 8 seeds, one of them a duplicate


def test_worker_count_is_bounded():
    assert cli.worker_count(Namespace(workers=0)) == 8 or cli.worker_count(Namespace(workers=0)) >= 1
    assert cli.worker_count(Namespace(workers=500)) == cli.MAX_WORKERS
    assert cli.worker_count(Namespace(workers=3)) == 3


# ---- the search history (continue where I left off) --------------------------------------------------

def test_ledger_remembers_results_and_forgets_failures_sooner(database):
    database.mark_checked("acme.com", "lead", {"country": "US", "region": "Texas"})
    database.mark_checked("chain.com", "chain")
    database.mark_checked("down.com", "no_contact")
    assert set(database.checked_map()) == {"acme.com", "chain.com", "down.com"}
    old = lambda days: now() - timedelta(days=days)  # noqa: E731
    database.checked.update_one({"_id": "down.com"}, {"$set": {"checked_at": old(45)}})     # failure: retry after 30d
    database.checked.update_one({"_id": "chain.com"}, {"$set": {"checked_at": old(120)}})   # stable: kept for 180d
    database.checked.update_one({"_id": "acme.com"}, {"$set": {"checked_at": old(200)}})    # stable but old
    assert set(database.checked_map()) == {"chain.com"}
    assert database.checked_map()["chain.com"] == {"country": "", "region": ""}
    assert database.clear_checked() == 3 and database.checked_count() == 0


def businesses(n=35):
    return [{"business": f"Shop {i}", "website": f"https://shop{i}.com", "phone": "", "email": "", "city": "X",
             "brand": "Chainy" if i % 5 == 0 else "", "category": "toys"} for i in range(n)]


def test_discovery_skips_checked_businesses_and_applies_the_limit_after(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(cli, "discover", lambda category, country, region, place, limit, **kw:
                        seen.update(kw) or businesses(30))
    exclude = {seed_key(b): {"country": "US", "region": "Ohio"} for b in businesses(10)}
    logs, out = [], tmp_path / "s.csv"
    cli.cmd_discover(Namespace(country="US", region="Ohio", place="", category="toys", output=str(out), limit=10,
                               exclude=exclude), log=logs.append)
    names = [r["business"] for r in csv.DictReader(open(out, encoding="utf-8-sig"))]
    assert names == [f"Shop {i}" for i in range(10, 20)]            # the next ten, not the same ten again
    assert seen["skip"] == 10 and any("Skipping 10 businesses" in m for m in logs)


def test_the_search_reaches_past_what_was_already_checked(monkeypatch):
    from skrapkin import discover as discover_module
    sent = []

    class Resp:
        status_code, ok = 200, True
        def json(self): return {"elements": [{"tags": {"name": "Acme", "website": "https://acme.com"}}]}

    monkeypatch.setattr(discover_module.requests, "post", lambda url, data, **k: sent.append(data["data"]) or Resp())
    discover_module.discover("toys", "US", "Texas", limit=50, skip=0)
    discover_module.discover("toys", "US", "Texas", limit=50, skip=500)
    assert "center 400;" in sent[0] and "center 4400;" in sent[1]


def test_cli_skip_checked_reads_the_history_from_the_database(monkeypatch, tmp_path, database):
    for b in businesses(5):
        database.mark_checked(seed_key(b), "lead", {"country": "US", "region": "Ohio"})
    monkeypatch.setattr(jobs, "connect_db", lambda cfg: database)
    monkeypatch.setattr(cli, "discover", lambda *a, **k: businesses(8))
    out = tmp_path / "s.csv"
    cli.cmd_discover(Namespace(country="US", region="Ohio", place="", category="toys", output=str(out), limit=None,
                               skip_checked=True), log=lambda m: None)
    assert [r["business"] for r in csv.DictReader(open(out, encoding="utf-8-sig"))] == ["Shop 5", "Shop 6", "Shop 7"]


@pytest.fixture
def pipeline(monkeypatch, database, tmp_path):
    monkeypatch.setattr(cli, "discover", lambda category, country, region, place, limit, **kw: businesses(35))
    monkeypatch.setattr(cli, "mx_status", lambda d: "ok")
    monkeypatch.setattr(cli, "scrape_site", lambda fetcher, url, *a, **k: {
        "name": "x", "emails": {f"info@{url.split('//')[1]}"}, "phones": set(), "pages": [url]})

    def run(**kw):
        s = jobs.Settings(category="toys", country="US", region="Ohio", output_dir=tmp_path, max_businesses=10,
                          workers=4, **kw)
        logs = []
        path, count = jobs.run_pipeline(s, logs.append, lambda d, t: None, lambda: False, db=database)
        return count, logs
    return run


def test_repeated_searches_keep_moving_forward_until_the_area_is_exhausted(pipeline, database):
    counts = []
    for _ in range(4):
        counts.append(pipeline()[0])
    # 10 businesses per run; every fifth is a chain and is dropped, but still counts as checked
    assert counts == [8, 8, 8, 4]
    assert database.checked_count() == 35 and database.stats()["leads"] == 28
    count, logs = pipeline()
    assert count == 0 and any("No new businesses" in m for m in logs)


def test_without_skip_checked_the_same_businesses_come_back(pipeline, database):
    assert pipeline(skip_checked=False)[0] == 8
    assert pipeline(skip_checked=False)[0] == 8
    assert database.stats()["leads"] == 8                 # the same eight, merged rather than duplicated


def test_chains_do_not_use_up_slots_on_later_runs(pipeline, database):
    pipeline()                                            # checks shops 0-9, two of them chains
    chain_keys = {seed_key(b) for b in businesses() if b["brand"]}
    assert {"shop0.com", "shop5.com"} <= set(database.checked_map()) and chain_keys >= {"shop0.com", "shop5.com"}
    pipeline()
    assert "shop10.com" in database.checked_map() and "shop15.com" in database.checked_map()


# ---- the web API ------------------------------------------------------------------------------------

H = {"X-Skrapkin": "1"}


@pytest.fixture
def client(database, monkeypatch, tmp_path):
    monkeypatch.setenv("SKRAPKIN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SKRAPKIN_OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.setattr(config, "keyring", None)
    app = create_app(cfg=config.Config(), connect=False)
    svc = app.extensions["skrapkin"]
    svc.db, svc.connected, svc.refresh = database, True, lambda: None
    return app.test_client()


GOOD = {"category": "toys", "country": "US", "region": "Ohio", "min_confidence": "low", "max_businesses": 20}


def test_find_passes_speed_and_history_options_through(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(jobs, "run_pipeline", lambda s, *a, **k: seen.update(s=s) or (None, 0))
    for payload in ({}, {"workers": 3, "skip_checked": False}):
        seen.clear()
        task = client.post("/api/find", json={**GOOD, **payload}, headers=H).get_json()["task"]
        end = time.time() + 3
        while not seen and time.time() < end:
            time.sleep(0.02)
        assert (seen["s"].workers, seen["s"].skip_checked) == ((8, True) if not payload else (3, False))
        while client.get(f"/api/tasks/{task}").get_json()["state"] == "running":
            time.sleep(0.02)


@pytest.mark.parametrize("workers", [0, 33, "many"])
def test_find_rejects_silly_worker_counts(client, workers):
    r = client.post("/api/find", json={**GOOD, "workers": workers}, headers=H)
    assert r.status_code == 400 and "Sites checked at once" in r.get_json()["error"]


def test_history_can_be_viewed_and_cleared(client, database):
    database.mark_checked("a.com", "lead")
    database.mark_checked("b.com", "chain")
    assert client.get("/api/history").get_json() == {"checked": 2}
    assert client.post("/api/history/clear", headers=H).get_json() == {"cleared": 2}
    assert client.get("/api/history").get_json() == {"checked": 0}
    assert client.post("/api/history/clear").status_code == 403         # needs the custom header like any change


def test_settings_validation_covers_workers():
    s = jobs.Settings(category="toys", country="US", output_dir="/tmp/x", workers=0)
    assert "between 1 and 32" in jobs.validate(s)
    assert jobs.validate(jobs.Settings(category="toys", country="US", output_dir="/tmp/x", workers=8)) is None


# ---- quick mode: stop reading a site once it has given us its email ------------------------------------

class PageFetcher:
    def __init__(self, pages):
        self.pages, self.fetched = pages, []

    def get(self, url):
        self.fetched.append(url)
        return self.pages.get(url)


HOME_LINKS = '<a href="/contact">Contact</a><a href="/about">About</a><a href="/team">Team</a>'


def page(*emails, links=HOME_LINKS):
    return "<html><body>" + links + " ".join(f"<a href='mailto:{e}'>x</a>" for e in emails) + "</body></html>"


def scrape(fetcher, **kw):
    return cli.scrape_site(fetcher, "https://acme.com/", 4, True, region="US", **kw)


def test_quick_mode_stops_at_the_first_page_with_an_email_on_the_business_domain():
    f = PageFetcher({"https://acme.com/": page("info@acme.com"), "https://acme.com/contact": page("sales@acme.com")})
    result = scrape(f, stop_at_email=True)
    assert f.fetched == ["https://acme.com/"] and result["emails"] == {"info@acme.com"}


def test_quick_mode_keeps_looking_until_it_finds_one():
    f = PageFetcher({"https://acme.com/": page(), "https://acme.com/contact": page("sales@acme.com"),
                     "https://acme.com/about": page("info@acme.com")})
    result = scrape(f, stop_at_email=True)
    assert f.fetched == ["https://acme.com/", "https://acme.com/contact"] and result["emails"] == {"sales@acme.com"}


def test_quick_mode_is_not_satisfied_by_a_webmail_address_or_someone_elses_domain():
    f = PageFetcher({"https://acme.com/": page("owner@gmail.com", "x@partner.com"),
                     "https://acme.com/contact": page("info@acme.com")})
    result = scrape(f, stop_at_email=True)
    assert len(f.fetched) == 2 and "info@acme.com" in result["emails"] and "owner@gmail.com" in result["emails"]


def test_thorough_mode_reads_every_page_and_finds_the_extra_addresses():
    pages = {"https://acme.com/": page("info@acme.com"), "https://acme.com/contact": page("sales@acme.com"),
             "https://acme.com/about": page("jobs@acme.com"), "https://acme.com/team": page("ceo@acme.com")}
    f = PageFetcher(pages)
    result = scrape(f, stop_at_email=False)
    assert len(f.fetched) == 4 and result["emails"] == {"info@acme.com", "sales@acme.com", "jobs@acme.com", "ceo@acme.com"}


def test_stopping_the_search_stops_fetching_more_pages():
    f = PageFetcher({"https://acme.com/": page(), "https://acme.com/contact": page("a@acme.com")})
    scrape(f, should_stop=lambda: True)
    assert f.fetched == ["https://acme.com/"]


def test_the_thorough_option_reaches_the_scraper(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "scrape_site", lambda *a, **k: seen.append(k["stop_at_email"]) or None)
    monkeypatch.setattr(cli, "mx_status", lambda d: "ok")
    path = seeds_file(tmp_path, n=1)
    cli.cmd_scrape(scrape_args(path, tmp_path / "t.csv"), log=lambda m: None)
    cli.cmd_scrape(scrape_args(path, tmp_path / "t.csv", thorough=True), log=lambda m: None)
    assert seen == [True, False]                       # quick by default, thorough on request


# ---- leads saved before the history existed ---------------------------------------------------------

def test_existing_leads_are_counted_as_checked_once_and_clearing_sticks(database):
    database.upsert_lead({"business": "Acme", "website": "https://acme.com", "emails": "info@acme.com"},
                         {"country": "DE", "region": "Bayern"})
    database.upsert_lead({"business": "Bolt", "website": "https://bolt.de", "emails": "x@bolt.de"},
                         {"country": "DE", "region": "Bayern"})
    assert database.checked_count() == 0
    assert database.backfill_history() == 2
    assert set(database.checked_map()) == {"acme.com", "bolt.de"}
    assert database.checked_map()["acme.com"] == {"country": "DE", "region": "Bayern"}
    assert database.backfill_history() == 0                 # only ever once
    database.clear_checked()
    database.backfill_history()
    assert database.checked_count() == 0                    # forgetting the history stays forgotten


def test_backfill_does_not_overwrite_a_real_outcome(database):
    database.mark_checked("acme.com", "chain")
    database.upsert_lead({"business": "Acme", "website": "https://acme.com", "emails": "i@acme.com"}, {})
    database.backfill_history()
    assert database.checked.find_one({"_id": "acme.com"})["outcome"] == "chain"
