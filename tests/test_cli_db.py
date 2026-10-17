import csv

import pytest

from skrapkin import cli, config, jobs, verifier


class FakeClient:
    calls = []

    def __init__(self, key):
        pass

    def account(self):
        return {"plan": "Free", "remaining": 50, "available": 50, "used": 0}

    def verify(self, email):
        FakeClient.calls.append(email)
        return {"status": "valid" if email.startswith("info@") else "invalid", "score": 90}


@pytest.fixture
def wired(database, monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "connect_db", lambda cfg: database)
    monkeypatch.setattr(verifier, "mx_status", lambda d: "ok")
    monkeypatch.setattr(jobs, "HunterClient", FakeClient)
    monkeypatch.setenv("SKRAPKIN_HOME", str(tmp_path))
    monkeypatch.setenv("HUNTER_API_KEY", "KEY")
    FakeClient.calls = []
    database.upsert_lead({"business": "Acme", "website": "https://acme.com", "category": "building",
                          "emails": "info@acme.com; xk3j9q2w7z4m@acme.com; sales@othercorp.com",
                          "phones": ""}, {"country": "US", "region": "Texas"})
    return database


def test_verify_preview_spends_nothing(wired):
    logs = []
    assert cli.cmd_verify(cli.argparse.Namespace(preview=True, yes=False, min_likelihood=None, max_lookups=None),
                          log=logs.append) == 1
    assert FakeClient.calls == []
    text = "\n".join(logs)
    assert "would check  info@acme.com" in text and "looks auto-generated" in text


def test_verify_yes_checks_only_likely_emails_and_files_verified(wired):
    cli.cmd_verify(cli.argparse.Namespace(preview=False, yes=True, min_likelihood=None, max_lookups=None),
                   log=lambda m: None)
    assert FakeClient.calls == ["info@acme.com"]
    assert [v["email"] for v in wired.list_verified()] == ["info@acme.com"]


def test_verify_without_a_key_exits_with_a_clear_message(wired, monkeypatch):
    monkeypatch.delenv("HUNTER_API_KEY")
    monkeypatch.setattr(config, "keyring", None)
    with pytest.raises(SystemExit) as e:
        cli.cmd_verify(cli.argparse.Namespace(preview=False, yes=True, min_likelihood=None, max_lookups=None))
    assert "HUNTER_API_KEY" in str(e.value)


def test_export_writes_excel_friendly_csv(wired, tmp_path):
    wired.upsert_verified("info@acme.com", {"business": "Acme", "country": "US", "region": "Texas"}, {"score": 90})
    out = tmp_path / "v.csv"
    assert cli.cmd_export(cli.argparse.Namespace(what="verified", output=str(out)), log=lambda m: None) == 1
    rows = list(csv.reader(open(out, encoding="utf-8-sig")))
    assert rows[0][0] == "email" and rows[1][:2] == ["info@acme.com", "Acme"]


def test_env_vars_override_stored_settings_without_being_persisted(monkeypatch, tmp_path):
    monkeypatch.setenv("SKRAPKIN_HOME", str(tmp_path))
    monkeypatch.setattr(config, "keyring", None)
    monkeypatch.setenv("SKRAPKIN_MONGO_URI", "mongodb://mongo:27017")
    monkeypatch.setenv("HUNTER_API_KEY", "ENVKEY")
    cfg = config.Config.load()
    assert cfg.mongo_uri == "mongodb://mongo:27017" and config.get_hunter_key() == "ENVKEY"
    cfg.save()
    assert config.get_secret("mongo_uri") is None  # env values never leak into the keychain/file
