import pytest

from skrapkin.hunter import HunterClient, HunterError, InvalidKey, QuotaExceeded


class Resp:
    def __init__(self, code, body=None):
        self.status_code, self._body = code, body or {}

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params, headers))
        return self.responses.pop(0)


def client(*responses):
    session = FakeSession(*responses)
    return HunterClient("KEY123", session=session, sleep=lambda s: None, retry_delay=0), session


def ok(status="valid", **extra):
    return Resp(200, {"data": {"status": status, "score": 91, **extra}})


def test_verify_parses_result_and_sends_key_in_header_only():
    c, s = client(ok(accept_all=False, smtp_check=True))
    result = c.verify("a@acme.com")
    assert result["status"] == "valid" and result["score"] == 91 and result["smtp_check"] is True
    url, params, headers = s.calls[0]
    assert headers == {"X-API-KEY": "KEY123"} and params == {"email": "a@acme.com"}
    assert "KEY123" not in url


def test_retries_while_hunter_is_still_verifying():
    c, s = client(Resp(202), Resp(222), ok("accept_all", accept_all=True))
    assert c.verify("a@acme.com")["status"] == "accept_all"
    assert len(s.calls) == 3


def test_rate_limit_403_backs_off_then_succeeds():
    c, _ = client(Resp(403), ok())
    assert c.verify("a@acme.com")["status"] == "valid"


def test_usage_limit_and_bad_key_raise_distinct_errors():
    with pytest.raises(QuotaExceeded):
        client(Resp(429))[0].verify("a@acme.com")
    with pytest.raises(InvalidKey):
        client(Resp(401))[0].verify("a@acme.com")


def test_claimed_and_malformed_addresses_are_not_errors():
    assert client(Resp(451))[0].verify("a@acme.com")["status"] == "claimed"
    bad = Resp(400, {"errors": [{"id": "invalid_email", "details": "x"}]})
    assert client(bad)[0].verify("a@acme.com")["status"] == "invalid"


def test_gives_up_after_too_many_pending_responses():
    c, _ = client(*[Resp(202)] * 8)
    with pytest.raises(HunterError):
        c.verify("a@acme.com")


def test_account_prefers_shared_credit_pool():
    body = {"data": {"plan_name": "Starter", "requests": {
        "credits": {"used": 550.0, "available": 10000.0, "remaining": 9450.0},
        "verifications": {"used": 1100, "available": 20000, "remaining": 18900}}}}
    assert client(Resp(200, body))[0].account() == {
        "plan": "Starter", "remaining": 9450, "available": 10000, "used": 550}


def test_account_uses_verification_quota_without_a_pool():
    body = {"data": {"plan_name": "Free", "requests": {
        "verifications": {"used": 5, "available": 50, "remaining": 45}}}}
    assert client(Resp(200, body))[0].account()["remaining"] == 45
