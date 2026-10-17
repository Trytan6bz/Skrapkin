"""Polite HTTP fetching: honours robots.txt and rate-limits per domain. Safe to share between threads."""

import threading
import time
from urllib import robotparser
from urllib.parse import urlparse

import requests

from . import __version__

USER_AGENT = f"SKrapkin/{__version__} (business contact research; respects robots.txt)"


class Fetcher:
    """One Fetcher serves many worker threads. Each thread gets its own HTTP session, and the per-domain
    delay is enforced under a lock, so no single site is hit more often than `delay` allows no matter how
    many sites are being fetched at once."""

    def __init__(self, delay=2.0, timeout=15):
        self.delay = delay
        self.timeout = timeout
        self._local = threading.local()
        self._lock = threading.Lock()
        self._robots = {}
        self._last_hit = {}

    @property
    def session(self):
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers["User-Agent"] = USER_AGENT
            self._local.session = session
        return session

    def _robots_for(self, url):
        parts = urlparse(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        with self._lock:
            rp = self._robots.get(origin)
        if rp is None:
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
            with self._lock:
                rp = self._robots.setdefault(origin, rp)
        return rp

    def allowed(self, url):
        return self._robots_for(url).can_fetch(USER_AGENT, url)

    def get(self, url):
        """Return page HTML, or None if disallowed, failed, or not HTML."""
        if not self.allowed(url):
            return None
        domain = urlparse(url).netloc
        with self._lock:  # reserve this domain's next slot, so concurrent callers queue up behind each other
            now = time.monotonic()
            last = self._last_hit.get(domain)
            wait = 0.0 if last is None else max(0.0, self.delay - (now - last))
            self._last_hit[domain] = now + wait
        if wait:
            time.sleep(wait)
        try:
            resp = self.session.get(url, timeout=self.timeout)
        except requests.RequestException:
            return None
        if resp.status_code != 200 or "html" not in resp.headers.get("Content-Type", ""):
            return None
        return resp.text
