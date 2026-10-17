import csv
import io
import threading
import time

import pytest

from skrapkin import config, jobs, verifier
from skrapkin.hunter import InvalidKey
from skrapkin.web import app as webapp
from skrapkin.web import create_app

H = {"X-Skrapkin": "1"}


class FakeHunter:
    def __init__(self, key):
        self.key = key

    def account(self):
        if self.key.startswith("BADKEY"):
            raise InvalidKey("bad")
        return {"plan": "Free", "remaining": 40, "available": 50, "used": 10}

    def verify(self, email):
        return {"status": "valid" if email.startswith(("info@", "sales@")) else "invalid", "score": 90}


@pytest.fixture
def app(database, monkeypatch, tmp_path):
    monkeypatch.setenv("SKRAPKIN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SKRAPKIN_OUTPUT_DIR", str(tmp_path / "out"))
    for var in ("HUNTER_API_KEY", "SKRAPKIN_MONGO_URI", "SKRAPKIN_WEB_PASSWORD", "SKRAPKIN_ALLOWED_HOSTS"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(config, "keyring", None)
    monkeypatch.setattr(verifier, "mx_status", lambda d: "ok")
    monkeypatch.setattr(jobs, "HunterClient", FakeHunter)
    monkeypatch.setattr(webapp, "HunterClient", FakeHunter)
    app = create_app(cfg=config.Config(), connect=False)
    svc = app.extensions["skrapkin"]
    svc.db, svc.connected = database, True
    svc.refresh = lambda: None  # mongomock has no admin ping
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def wait_for(client, task_id, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        snap = client.get(f"/api/tasks/{task_id}").get_json()
        if snap["state"] != "running":
            return snap
        time.sleep(0.02)
    raise AssertionError("task did not finish")


def seed(database):
    database.upsert_lead({"business": "Acme Supply", "website": "https://acme.com", "category": "building",
                          "emails": "info@acme.com; xk3j9q2w7z4m@acme.com; owner@gmail.com",
                          "phones": "+17135550100", "city": "Houston", "confidence": "high"},
                         {"country": "US", "region": "Texas"})


# ---- guards ---------------------------------------------------------------------------------------

def test_unknown_host_is_rejected_against_dns_rebinding(client):
    assert client.get("/api/status", headers={"Host": "evil.example.com"}).status_code == 421
    assert client.get("/api/status", headers={"Host": "localhost:8080"}).status_code == 200


def test_changes_need_the_custom_header(client):
    assert client.post("/api/verify/settings", json={"min_likelihood": 50}).status_code == 403
    assert client.post("/api/verify/settings", json={"min_likelihood": 50}, headers=H).status_code == 200


def test_extra_hosts_can_be_allowed(monkeypatch, app):
    monkeypatch.setenv("SKRAPKIN_ALLOWED_HOSTS", "leads.mycompany.com")
    other = create_app(cfg=config.Config(), connect=False)
    assert other.test_client().get("/api/health", headers={"Host": "leads.mycompany.com"}).status_code == 200


def test_password_protects_everything_but_health(monkeypatch):
    monkeypatch.setenv("SKRAPKIN_WEB_PASSWORD", "s3cret")
    protected = create_app(cfg=config.Config(), connect=False).test_client()
    assert protected.get("/api/health").status_code == 200
    assert protected.get("/api/status").status_code == 401
    import base64
    good = {"Authorization": "Basic " + base64.b64encode(b"skrapkin:s3cret").decode()}
    bad = {"Authorization": "Basic " + base64.b64encode(b"skrapkin:nope").decode()}
    assert protected.get("/api/status", headers=good).status_code == 200
    assert protected.get("/api/status", headers=bad).status_code == 401


def test_security_headers(client):
    r = client.get("/api/status")
    assert "script-src 'self'" in r.headers["Content-Security-Policy"] and "unsafe-inline" not in r.headers["Content-Security-Policy"]
    assert r.headers["X-Frame-Options"] == "DENY" and r.headers["Cache-Control"] == "no-store"


def test_status_never_leaks_the_database_address(app, client):
    app.extensions["skrapkin"].cfg.mongo_uri = "mongodb://user:topsecret@db.internal:27017"
    text = client.get("/api/status").get_data(as_text=True)
    assert "topsecret" not in text and "db.internal:27017" in text


# ---- settings -------------------------------------------------------------------------------------

def test_db_settings_validation(client, monkeypatch):
    assert "mongodb://" in client.post("/api/db", json={"uri": "http://nope"}, headers=H).get_json()["error"]
    assert client.post("/api/db", json={"db_name": "bad name!"}, headers=H).status_code == 400
    monkeypatch.setenv("SKRAPKIN_MONGO_URI", "mongodb://mongo:27017")
    assert "environment" in client.post("/api/db", json={"uri": "mongodb://x:1"}, headers=H).get_json()["error"]


def test_verify_settings_validation(client):
    assert client.post("/api/verify/settings", json={"min_likelihood": 500}, headers=H).status_code == 400
    assert client.post("/api/verify/settings", json={"max_credits_per_run": "x"}, headers=H).status_code == 400


# ---- hunter key -----------------------------------------------------------------------------------

def test_key_flow(client):
    assert client.post("/api/hunter/key", json={"key": "short"}, headers=H).status_code == 400
    r = client.post("/api/hunter/key", json={"key": "BADKEY1234567890"}, headers=H)
    assert r.status_code == 400 and "rejected" in r.get_json()["error"]
    assert client.get("/api/status").get_json()["hunter"]["configured"] is False
    ok = client.post("/api/hunter/key", json={"key": "goodkey1234567890"}, headers=H).get_json()
    assert ok["account"]["remaining"] == 40
    assert client.get("/api/status").get_json()["hunter"] == {"configured": True, "source": "saved"}
    assert client.get("/api/hunter/account").get_json()["account"]["plan"] == "Free"
    client.delete("/api/hunter/key", headers=H)
    assert client.get("/api/status").get_json()["hunter"]["configured"] is False


def test_key_from_environment_is_reported(client, monkeypatch):
    monkeypatch.setenv("HUNTER_API_KEY", "envkey1234567890")
    assert client.get("/api/status").get_json()["hunter"] == {"configured": True, "source": "environment"}


# ---- find leads -----------------------------------------------------------------------------------

def fake_pipeline(monkeypatch, gate=None):
    def discover(args, log, should_stop=None):
        log("found 2")
        return 2

    def scrape(args, log, progress, should_stop, on_lead, on_checked=None):
        for i, name in enumerate(["Acme Supply", "=EVIL()"]):
            if gate:
                gate.wait(5)
            progress(i, 2)
            on_lead({"category": "building", "business": name, "website": f"https://s{i}.com",
                     "emails": f"info@s{i}.com", "phones": "+17135550100", "city": "Austin",
                     "confidence": "high", "source_pages": "x", "email_sources": {}})
        progress(2, 2)
        open(args.output, "w").write("x")
        return 2

    monkeypatch.setattr(jobs, "cmd_discover", discover)
    monkeypatch.setattr(jobs, "cmd_scrape", scrape)


GOOD_FIND = {"category": "building", "country": "US", "region": "Texas", "min_confidence": "medium",
             "max_businesses": 20}


@pytest.mark.parametrize("change,fragment", [
    ({"category": "cars"}, "type of business"), ({"country": "ZZ"}, "country"),
    ({"region": "Narnia"}, "known region"), ({"place": "x" * 200}, "characters"),
    ({"min_confidence": "x"}, "keep"), ({"max_businesses": 0}, "between"), ({"max_businesses": "abc"}, "whole number"),
])
def test_find_validation(client, change, fragment):
    r = client.post("/api/find", json={**GOOD_FIND, **change}, headers=H)
    assert r.status_code == 400 and fragment in r.get_json()["error"]


def test_find_runs_streams_leads_and_saves(client, monkeypatch, database):
    fake_pipeline(monkeypatch)
    task = client.post("/api/find", json=GOOD_FIND, headers=H).get_json()["task"]
    snap = wait_for(client, task)
    assert snap["state"] == "done" and snap["result"]["count"] == 2 and snap["lead_count"] == 2
    assert snap["result"]["file"].endswith("_leads.csv") and snap["result"]["saved_to_database"] is True
    assert client.get(f"/api/tasks/{task}?cursor=1").get_json()["leads"][0]["business"] == "=EVIL()"
    assert database.stats()["leads"] == 2
    assert client.get(f"/api/download/{snap['result']['file']}").status_code == 200


def test_only_one_task_runs_at_a_time_and_stop_works(client, monkeypatch):
    gate = threading.Event()
    fake_pipeline(monkeypatch, gate)
    task = client.post("/api/find", json=GOOD_FIND, headers=H).get_json()["task"]
    assert client.get("/api/status").get_json()["active_task"]["id"] == task
    assert client.post("/api/find", json=GOOD_FIND, headers=H).status_code == 409
    client.post(f"/api/tasks/{task}/stop", headers=H)
    gate.set()
    assert wait_for(client, task)["state"] == "stopped"


def test_find_needs_database_unless_unticked(client, app, monkeypatch):
    fake_pipeline(monkeypatch)
    svc = app.extensions["skrapkin"]
    svc.db, svc.connected = None, False
    assert client.post("/api/find", json=GOOD_FIND, headers=H).status_code == 409
    task = client.post("/api/find", json={**GOOD_FIND, "save_db": False}, headers=H).get_json()["task"]
    assert wait_for(client, task)["result"]["saved_to_database"] is False


def test_verify_after_requires_a_key(client):
    r = client.post("/api/find", json={**GOOD_FIND, "verify_after": True}, headers=H)
    assert r.status_code == 400 and "Hunter" in r.get_json()["error"]


def test_failures_become_plain_language_errors(client, monkeypatch):
    def boom(args, log, should_stop=None):
        raise RuntimeError("Overpass API unavailable after retries: 502")

    monkeypatch.setattr(jobs, "cmd_discover", boom)
    snap = wait_for(client, client.post("/api/find", json=GOOD_FIND, headers=H).get_json()["task"])
    assert snap["state"] == "error" and "OpenStreetMap" in snap["error"] and "Overpass" not in snap["error"]


# ---- leads, verification, verified --------------------------------------------------------------

def test_leads_listing_filters_and_delete(client, database):
    seed(database)
    database.upsert_lead({"business": "Bolt Toys", "website": "https://bolt.com", "emails": "x@bolt.com",
                          "category": "toys"}, {"country": "US", "region": "Ohio"})
    data = client.get("/api/leads").get_json()
    assert len(data["leads"]) == 2 and data["totals"]["leads"] == 2
    assert [l["business"] for l in client.get("/api/leads?q=bolt").get_json()["leads"]] == ["Bolt Toys"]
    assert [l["business"] for l in client.get("/api/leads?country=US&region=Ohio&category=toys").get_json()["leads"]] == ["Bolt Toys"]
    database.set_email_status("info@acme.com", "valid")
    assert [l["business"] for l in client.get("/api/leads?status=valid").get_json()["leads"]] == ["Acme Supply"]
    keys = [l["key"] for l in data["leads"]]
    assert client.post("/api/leads/delete", json={"keys": keys}, headers=H).get_json()["deleted"] == 2


def test_database_errors_are_reported_not_crashed(client, app):
    svc = app.extensions["skrapkin"]
    svc.db, svc.connected = None, False
    r = client.get("/api/leads")
    assert r.status_code == 409 and "isn't connected" in r.get_json()["error"]


def test_verify_preview_then_run_then_free_second_run(client, database):
    seed(database)
    assert client.post("/api/verify/start", headers=H).status_code == 409  # no key yet
    client.post("/api/hunter/key", json={"key": "goodkey1234567890"}, headers=H)
    preview = client.post("/api/verify/preview", headers=H).get_json()
    decisions = {r["email"]: (r["decision"], r["reason"]) for r in preview["rows"]}
    assert decisions["info@acme.com"][0] == "check" and preview["will_use"] == 1
    assert "auto-generated" in decisions["xk3j9q2w7z4m@acme.com"][1]
    assert "webmail" in decisions["owner@gmail.com"][1]
    task = client.post("/api/verify/start", headers=H).get_json()["task"]
    snap = wait_for(client, task)
    assert snap["state"] == "done" and snap["result"]["stats"]["valid"] == 1
    assert [v["email"] for v in client.get("/api/verified").get_json()["verified"]] == ["info@acme.com"]
    again = client.post("/api/verify/preview", headers=H).get_json()
    assert again["will_use"] == 0


def test_exports_are_excel_safe_and_filtered(client, database):
    database.upsert_lead({"business": "=HYPERLINK(\"http://evil\")", "website": "https://e.com",
                          "emails": "info@e.com", "phones": "+17135550100"}, {"country": "US", "region": "Texas"})
    database.upsert_verified("info@e.com", {"business": "@SUM(1)", "country": "US", "region": "Texas"}, {"score": 90})
    leads = client.get("/api/export/leads.csv")
    assert leads.data.startswith(b"\xef\xbb\xbf") and "attachment" in leads.headers["Content-Disposition"]
    row = list(csv.reader(io.StringIO(leads.get_data(as_text=True).lstrip("﻿"))))[1]
    assert row[0].startswith("'=") and row[6] == "+17135550100"
    ver = list(csv.reader(io.StringIO(client.get("/api/export/verified.csv").get_data(as_text=True).lstrip("﻿"))))
    assert ver[1][0] == "info@e.com" and ver[1][1] == "'@SUM(1)" and ver[1][2:4] == ["US", "Texas"]
    assert len(list(csv.reader(io.StringIO(client.get("/api/export/verified.csv?q=zzz").get_data(as_text=True))))) == 1


def test_verified_delete(client, database):
    database.upsert_verified("a@acme.com", {"business": "Acme"}, {"score": 90})
    assert client.post("/api/verified/delete", json={"emails": ["a@acme.com"]}, headers=H).get_json()["deleted"] == 1


def test_download_rejects_anything_but_plain_csv_names(client):
    for name in ["..%2f..%2fetc%2fpasswd", "x.txt", "a%2fb.csv", "..csv"]:
        assert client.get(f"/api/download/{name}").status_code == 404


# ---- worldwide ------------------------------------------------------------------------------------

def test_status_lists_every_country_and_regions_load_per_country(client):
    countries = client.get("/api/status").get_json()["options"]["countries"]
    assert len(countries) >= 245 and {"code": "NG", "name": "Nigeria"} in countries
    ng = client.get("/api/regions/NG").get_json()
    assert ng["country"] == "Nigeria" and {"code": "NG-LA", "name": "Lagos"} in ng["regions"]
    assert client.get("/api/regions/ng").status_code == 200       # case-insensitive
    assert client.get("/api/regions/ZZ").status_code == 404
    assert client.get("/api/regions/..%2f").status_code in (404, 405)


def test_find_accepts_any_country_region_and_city(client, monkeypatch):
    seen = {}

    def discover(args, log, should_stop=None):
        seen.update(country=args.country, region=args.region, place=args.place)
        return 0

    monkeypatch.setattr(jobs, "cmd_discover", discover)
    payload = {**GOOD_FIND, "country": "ng", "region": "NG-LA", "place": "Ikeja"}
    task = client.post("/api/find", json=payload, headers=H).get_json()["task"]
    snap = wait_for(client, task)
    assert snap["state"] == "done" and seen == {"country": "NG", "region": "NG-LA", "place": "Ikeja"}


def test_find_allows_a_whole_country_search(client, monkeypatch):
    monkeypatch.setattr(jobs, "cmd_discover", lambda a, log, should_stop=None: 0)
    r = client.post("/api/find", json={**GOOD_FIND, "region": "", "country": "DE"}, headers=H)
    assert r.status_code == 202


def test_leads_filter_by_country(client, database):
    seed(database)
    database.upsert_lead({"business": "Lagos Hardware", "website": "https://lagoshw.com.ng",
                          "emails": "info@lagoshw.com.ng", "category": "building"},
                         {"country": "NG", "region": "Lagos"})
    names = lambda url: sorted(l["business"] for l in client.get(url).get_json()["leads"])  # noqa: E731
    assert names("/api/leads?country=NG") == ["Lagos Hardware"]
    assert names("/api/leads?country=ng&region=Lagos") == ["Lagos Hardware"]
    assert names("/api/leads?country=US") == ["Acme Supply"]
    assert names("/api/leads?country=ZZ") == ["Acme Supply", "Lagos Hardware"]   # unknown filter is ignored
    lead = client.get("/api/leads?country=NG").get_json()["leads"][0]
    assert (lead["country"], lead["region"]) == ("NG", "Lagos")


def test_unwritable_output_folder_gives_a_plain_message(client, monkeypatch, tmp_path):
    blocker = tmp_path / "a-file"
    blocker.write_text("x")
    monkeypatch.setenv("SKRAPKIN_OUTPUT_DIR", str(blocker / "out"))   # a folder cannot be created inside a file
    snap = wait_for(client, client.post("/api/find", json=GOOD_FIND, headers=H).get_json()["task"])
    assert snap["state"] == "error" and "output folder" in snap["error"]
    assert "Error" not in snap["error"] and "errno" not in snap["error"].lower()
