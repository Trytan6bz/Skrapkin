from datetime import date
from pathlib import Path

from leadscraper import jobs


def settings(**kw):
    base = dict(category="toys", area="Texas", country="US", output_dir=Path("/tmp/out"))
    return jobs.Settings(**{**base, **kw})


def test_validate_catches_bad_input_in_plain_language():
    assert "state" in jobs.validate(settings(area="")).lower()
    assert "state" in jobs.validate(settings(area="Houston")).lower()
    assert "at least 1" in jobs.validate(settings(max_businesses=0))
    assert "folder" in jobs.validate(settings(output_dir=None))
    assert jobs.validate(settings()) is None


def test_output_paths_are_safe_and_dated():
    seeds, leads = jobs.output_paths(settings(area="New Hampshire"), today=date(2026, 10, 17))
    assert seeds.name == "toys_new-hampshire_2026-10-17_businesses.csv"
    assert leads.name == "toys_new-hampshire_2026-10-17_leads.csv"


def test_pipeline_runs_discover_then_scrape_and_reports(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(jobs, "cmd_discover", lambda a, log: calls.append(("discover", a)) or 5)
    monkeypatch.setattr(jobs, "cmd_scrape", lambda a, log, progress, should_stop: calls.append(("scrape", a)) or 3)
    logs = []
    path, count = jobs.run_pipeline(settings(output_dir=tmp_path, exclude_personal=True, max_businesses=25),
                                    logs.append, lambda d, t: None, lambda: False)
    assert count == 3 and path.name.endswith("_leads.csv")
    discover_args, scrape_args = calls[0][1], calls[1][1]
    assert discover_args.country == "US" and discover_args.category == "toys"
    assert discover_args.limit == 25 and discover_args.area == "Texas"
    assert scrape_args.exclude_personal is True and scrape_args.seeds == discover_args.output


def test_pipeline_stops_when_nothing_found(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "cmd_discover", lambda a, log: 0)
    logs = []
    assert jobs.run_pipeline(settings(output_dir=tmp_path), logs.append, None, None) == (None, 0)
    assert any("No businesses found" in m for m in logs)
