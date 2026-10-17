from datetime import date
from pathlib import Path

from skrapkin import jobs


def settings(**kw):
    base = dict(category="toys", country="US", region="Texas", output_dir=Path("/tmp/out"))
    return jobs.Settings(**{**base, **kw})


def test_validate_catches_bad_input_in_plain_language():
    assert "country" in jobs.validate(settings(country="")).lower()
    assert "country" in jobs.validate(settings(country="ZZ")).lower()
    assert "isn't a known region" in jobs.validate(settings(region="Narnia"))
    assert "characters" in jobs.validate(settings(place="x" * 200))
    assert jobs.validate(settings(region="", place="")) is None   # whole country is allowed
    assert jobs.validate(settings(country="NG", region="Lagos", place="Ikeja")) is None
    assert jobs.validate(settings(country="GB", region="GB-ENG")) is None   # ISO code works too
    assert "at least 1" in jobs.validate(settings(max_businesses=0))
    assert "folder" in jobs.validate(settings(output_dir=None))
    assert jobs.validate(settings()) is None


def test_output_paths_are_safe_and_dated():
    seeds, leads = jobs.output_paths(settings(country="NG", region="Lagos", place="Ikeja / Mainland"),
                                     today=date(2026, 10, 17))
    assert seeds.name == "toys_ng-lagos-ikeja-mainland_2026-10-17_businesses.csv"
    assert leads.name == "toys_ng-lagos-ikeja-mainland_2026-10-17_leads.csv"


def test_pipeline_runs_discover_then_scrape_and_reports(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(jobs, "cmd_discover", lambda a, log, should_stop=None: calls.append(("discover", a)) or 5)
    monkeypatch.setattr(jobs, "cmd_scrape", lambda a, log, progress, should_stop, on_lead, on_checked=None: calls.append(("scrape", a)) or 3)
    logs = []
    path, count = jobs.run_pipeline(settings(output_dir=tmp_path, exclude_personal=True, max_businesses=25),
                                    logs.append, lambda d, t: None, lambda: False)
    assert count == 3 and path.name.endswith("_leads.csv")
    discover_args, scrape_args = calls[0][1], calls[1][1]
    assert discover_args.country == "US" and discover_args.category == "toys"
    assert discover_args.limit == 25 and (discover_args.region, discover_args.place) == ("Texas", "")
    assert scrape_args.exclude_personal is True and scrape_args.seeds == discover_args.output


def test_pipeline_stops_when_nothing_found(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "cmd_discover", lambda a, log, should_stop=None: 0)
    logs = []
    assert jobs.run_pipeline(settings(output_dir=tmp_path), logs.append, None, None) == (None, 0)
    assert any("No businesses found" in m for m in logs)


def test_pipeline_saves_each_lead_to_the_database_with_search_context(monkeypatch, tmp_path):
    saved = []

    class FakeDb:
        def upsert_lead(self, lead, search):
            saved.append((lead["business"], search))

        def checked_map(self):
            return {}

        def mark_checked(self, key, outcome, search=None):
            pass

    def fake_scrape(a, log, progress, should_stop, on_lead, on_checked=None):
        on_lead({"business": "Acme"})
        on_lead({"business": "Bolt"})
        return 2

    monkeypatch.setattr(jobs, "cmd_discover", lambda a, log, should_stop=None: 5)
    monkeypatch.setattr(jobs, "cmd_scrape", fake_scrape)
    seen = []
    jobs.run_pipeline(settings(output_dir=tmp_path), print, None, None, db=FakeDb(), on_lead=seen.append)
    context = {"country": "US", "region": "Texas"}
    assert saved == [("Acme", context), ("Bolt", context)]
    assert len(seen) == 2


def test_run_verification_validates_key_and_caps_to_account_balance(monkeypatch):
    seen = {}

    class FakeClient:
        def __init__(self, key):
            seen["key"] = key

        def account(self):
            return {"plan": "Free", "remaining": 7, "available": 50, "used": 43}

    monkeypatch.setattr(jobs, "HunterClient", FakeClient)
    monkeypatch.setattr(jobs, "build_plan", lambda db, cfg: type("P", (), {"summary": lambda self: "plan"})())
    monkeypatch.setattr(jobs, "run_plan", lambda db, client, plan, cfg, **kw: {"budget": kw["budget"]})
    logs = []
    account, plan, stats = jobs.run_verification(None, object(), "KEY", logs.append, None, None)
    assert seen["key"] == "KEY" and stats == {"budget": 7}
    assert any("7 verifications remaining" in m for m in logs)
