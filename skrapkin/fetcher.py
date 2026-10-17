"""Polite HTTP fetching: honours robots.txt and rate-limits per domain."""

import time
from urllib import robotparser
from urllib.parse import urlparse

import requests

USER_AGENT = "SKrapkin/0.1 (business contact research; respects robots.txt)"


class Fetcher:
    def __init__(self, delay=2.0, timeout=15):
        self.delay = delay
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self._robots = {}
        self._last_hit = {}

    def _robots_for(self, url):
        parts = urlparse(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            rp = robotparser.RobotFileParser()
            try:
                resp = self.session.get(f"{origin}/robots.txt", timeout=self.timeout)
                if resp.status_code >= 500:
                    rp.disallow_all = True
                elif resp.status_code >= 400:
                    rp.allow_all = True
                else:
                    rp.parse(resp.text.splitlines())
            except requests.RequestException:
                rp.disallow_all = True
            self._robots[origin] = rp
        return self._robots[origin]

    def allowed(self, url):
        return self._robots_for(url).can_fetch(USER_AGENT, url)

    def get(self, url):
        """Return page HTML, or None if disallowed, failed, or not HTML."""
        if not self.allowed(url):
            return None
        domain = urlparse(url).netloc
        wait = self.delay - (time.monotonic() - self._last_hit.get(domain, 0))
        if wait > 0:
            time.sleep(wait)
        self._last_hit[domain] = time.monotonic()
        try:
            resp = self.session.get(url, timeout=self.timeout)
        except requests.RequestException:
            return None
        if resp.status_code != 200 or "html" not in resp.headers.get("Content-Type", ""):
            return None
        return resp.text
