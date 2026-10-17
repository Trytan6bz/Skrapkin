"""Minimal Hunter.io client: Email Verifier and Account endpoints (https://hunter.io/api-documentation/v2)."""

import time

import requests

BASE = "https://api.hunter.io/v2"
MIN_INTERVAL = 0.25  # Hunter allows 10/s and 300/min; 4/s stays under both


class HunterError(Exception):
    pass


class InvalidKey(HunterError):
    pass


class QuotaExceeded(HunterError):
    """Plan usage limit reached (HTTP 429): stop spending, nothing more will succeed."""


class HunterClient:
    def __init__(self, api_key, session=None, sleep=time.sleep, clock=time.monotonic,
                 max_attempts=8, retry_delay=3.0):
        self.session = session or requests.Session()
        self.headers = {"X-API-KEY": api_key}  # header, not a query param, so it never lands in URLs/logs
        self.sleep, self.clock = sleep, clock
        self.max_attempts, self.retry_delay = max_attempts, retry_delay
        self._last = 0.0

    def _throttle(self):
        wait = MIN_INTERVAL - (self.clock() - self._last)
        if wait > 0:
            self.sleep(wait)
        self._last = self.clock()

    def _get(self, path, params=None):
        self._throttle()
        try:
            return self.session.get(f"{BASE}{path}", params=params, headers=self.headers, timeout=35)
        except requests.RequestException as e:
            raise HunterError(f"could not reach Hunter: {e}") from e

    def account(self):
        """Free call. Returns plan name and how many verifications remain."""
        resp = self._get("/account")
        if resp.status_code == 401:
            raise InvalidKey("Hunter rejected this API key.")
        if resp.status_code != 200:
            raise HunterError(f"Hunter account check failed (HTTP {resp.status_code}).")
        data = resp.json()["data"]
        requests_ = data.get("requests", {})
        # A shared credits pool takes precedence over the separate verification quota.
        pool = requests_.get("credits") or requests_.get("verifications") or {}
        return {"plan": data.get("plan_name", ""), "remaining": int(pool.get("remaining", 0)),
                "available": int(pool.get("available", 0)), "used": int(pool.get("used", 0))}

    def verify(self, email):
        """Return a normalised result dict. status is one of Hunter's: valid, invalid, accept_all,
        webmail, disposable, unknown, plus 'claimed' for addresses whose owner opted out (HTTP 451)."""
        for attempt in range(self.max_attempts):
            resp = self._get("/email-verifier", {"email": email})
            code = resp.status_code
            if code == 200:
                return self._parse(resp.json()["data"])
            if code in (202, 222):  # still verifying / remote server hiccup: ask again
                self.sleep(self.retry_delay)
                continue
            if code == 403:  # rate limited: back off
                self.sleep(self.retry_delay * (attempt + 1))
                continue
            if code == 401:
                raise InvalidKey("Hunter rejected this API key.")
            if code == 429:
                raise QuotaExceeded("Your Hunter plan's usage limit has been reached.")
            if code == 451:
                return {"status": "claimed", "score": 0}
            if code == 400:
                errors = (resp.json().get("errors") or [{}])
                if errors[0].get("id") == "invalid_email":
                    return {"status": "invalid", "score": 0}
                raise HunterError(f"Hunter rejected the request: {errors[0].get('details', 'bad request')}")
            raise HunterError(f"Hunter returned HTTP {code}.")
        raise HunterError(f"Hunter did not finish verifying {email}; try again later.")

    @staticmethod
    def _parse(data):
        return {
            "status": data.get("status", "unknown"),
            "score": data.get("score"),
            "accept_all": bool(data.get("accept_all")),
            "disposable": bool(data.get("disposable")),
            "webmail": bool(data.get("webmail")),
            "mx_records": data.get("mx_records"),
            "smtp_check": data.get("smtp_check"),
            "gibberish": bool(data.get("gibberish")),
            "block": bool(data.get("block")),
        }
