import pytest

from skrapkin.config import Config
from skrapkin.hunter import InvalidKey, QuotaExceeded
from skrapkin.verifier import build_plan, run_plan

OK = lambda d: "ok"


class FakeHunter:
    def __init__(self, results=None, raises=None):
        self.results, self.raises, self.calls = results or {}, raises, []

    def verify(self, email):
        self.calls.append(email)
        if self.raises:
            raise self.raises
        return {"status": self.results.get(email, "valid"), "score": 90}


def lead(name, site, emails, source=None):
    row = {"business": name, "website": site, "emails": emails, "category": "building", "phones": ""}
    if source:
        row["email_sources"] = {e.strip(): source for e in emails.split(";")}
    return row


@pytest.fixture
def seeded(database):
    database.upsert_lead(lead("Acme", "https://acme.com", "info@acme.com; john.smith@acme.com; "
                              "owner@gmail.com; xk3j9q2w7z4m@acme.com; sales@othercorp.com"), {"state": "Texas"})
    return database


def status_of(db, address):
    statuses = {e["status"] for l in db.leads.find({"emails.address": address})
                for e in l["emails"] if e["address"] == address}
    assert len(statuses) == 1, statuses  # every lead holding the address agrees
    return statuses.pop()


def test_plan_sends_only_likely_real_emails(seeded):
    plan = build_plan(seeded, Config(), mx=OK)
    assert [c.address for c in plan.to_check] == ["info@acme.com", "john.smith@acme.com"]
    assert [c.address for c in plan.webmail] == ["owner@gmail.com"]
    reasons = {c.address: r for c, r in plan.filtered}
    assert set(reasons) == {"xk3j9q2w7z4m@acme.com", "sales@othercorp.com"}
    assert "auto-generated" in reasons["xk3j9q2w7z4m@acme.com"] and "unlikely" in reasons["sales@othercorp.com"]
    assert plan.saved == 3


def test_run_spends_credits_only_on_the_plan_and_files_verified_emails(seeded):
    hunter = FakeHunter({"john.smith@acme.com": "invalid"})
    stats = run_plan(seeded, hunter, build_plan(seeded, Config(), mx=OK), Config(), log=lambda m: None)
    assert hunter.calls == ["info@acme.com", "john.smith@acme.com"]
    assert stats["checked"] == 2 and stats["valid"] == 1 and stats["invalid"] == 1 and stats["skipped_free"] == 3
    assert [v["email"] for v in seeded.list_verified()] == ["info@acme.com"]
    assert status_of(seeded, "john.smith@acme.com") == "invalid"
    assert status_of(seeded, "owner@gmail.com") == "webmail"
    assert status_of(seeded, "sales@othercorp.com") == "filtered"


def test_second_run_costs_nothing(seeded):
    cfg = Config()
    run_plan(seeded, FakeHunter(), build_plan(seeded, cfg, mx=OK), cfg, log=lambda m: None)
    seeded.upsert_lead(lead("Acme 2", "https://acme2.com", "info@acme.com"), {"state": "Ohio"})  # same address
    hunter = FakeHunter()
    plan = build_plan(seeded, cfg, mx=OK)
    assert plan.to_check == [] and len(plan.cached) == 1
    run_plan(seeded, hunter, plan, cfg, log=lambda m: None)
    assert hunter.calls == []
    assert status_of(seeded, "info@acme.com") == "valid"  # both leads that hold it
    assert seeded.verified.count_documents({"email": "info@acme.com"}) == 1


def test_budget_caps_lookups_and_leaves_the_rest_unchecked(seeded):
    cfg = Config(max_credits_per_run=1)
    hunter = FakeHunter()
    stats = run_plan(seeded, hunter, build_plan(seeded, cfg, mx=OK), cfg, log=lambda m: None)
    assert hunter.calls == ["info@acme.com"] and stats["left_unchecked"] == 1
    assert status_of(seeded, "john.smith@acme.com") == "unchecked"
    stats = run_plan(seeded, hunter, build_plan(seeded, cfg, mx=OK), cfg, log=lambda m: None, budget=0)
    assert stats["checked"] == 0


def test_accept_all_domain_is_checked_once(database):
    database.upsert_lead(lead("Acme", "https://acme.com", "info@acme.com; sales@acme.com; john.smith@acme.com"),
                         {"state": "Texas"})
    hunter = FakeHunter({"info@acme.com": "accept_all"})
    stats = run_plan(database, hunter, build_plan(database, Config(), mx=OK), Config(), log=lambda m: None)
    assert hunter.calls == ["info@acme.com"]
    assert status_of(database, "sales@acme.com") == "accept_all" and stats["checked"] == 1
    assert database.list_verified() == []


def test_quota_exhaustion_stops_cleanly_and_bad_key_aborts(seeded):
    hunter = FakeHunter(raises=QuotaExceeded("limit"))
    stats = run_plan(seeded, hunter, build_plan(seeded, Config(), mx=OK), Config(), log=lambda m: None)
    assert "limit" in stats["stopped"] and stats["checked"] == 0 and stats["left_unchecked"] == 2
    with pytest.raises(InvalidKey):
        run_plan(seeded, FakeHunter(raises=InvalidKey("bad")), build_plan(seeded, Config(), mx=OK), Config(),
                 log=lambda m: None)


def test_stop_button_halts_between_lookups(seeded):
    hunter = FakeHunter()
    stats = run_plan(seeded, hunter, build_plan(seeded, Config(), mx=OK), Config(), log=lambda m: None,
                     should_stop=lambda: bool(hunter.calls))
    assert len(hunter.calls) == 1 and stats["stopped"] == "stopped by you"
