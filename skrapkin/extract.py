"""Pull business contact details out of a page."""

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
OBFUSCATED_RE = re.compile(
    r"([A-Za-z0-9._%+-]+)\s*[\[(]\s*at\s*[\])]\s*([A-Za-z0-9.-]+)\s*[\[(]\s*dot\s*[\])]\s*([A-Za-z]{2,})",
    re.IGNORECASE,
)
PHONE_RE = re.compile(r"(?:\+?\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}")

# Personal mailbox providers: kept by default (small businesses often use them); drop with --exclude-personal.
FREE_MAIL = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com",
    "icloud.com", "live.com", "msn.com", "proton.me", "protonmail.com",
}
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")
CONTACT_HINTS = ("contact", "about", "team", "support", "impressum")
# Pages listing many branches/partners pollute results with other entities' details.
SKIP_HINTS = ("location", "store", "branch", "dealer", "franchise", "find-us")


def filter_free_mail(emails, include_personal=True):
    if include_personal:
        return set(emails)
    return {e for e in emails if e.split("@")[1] not in FREE_MAIL}


def same_site_emails(emails, site_url):
    """Keep addresses on the business's own domain (or a subdomain/parent of it).

    Free-mail addresses found on the site are kept: small businesses often list them as their contact.
    """
    host = urlparse(site_url).netloc.lower().removeprefix("www.")
    return {e for e in emails
            if (d := e.split("@")[1]) in FREE_MAIL or d == host or host.endswith("." + d) or d.endswith("." + host)}


def extract_emails(html, include_personal=True):
    soup = BeautifulSoup(html, "html.parser")
    found = set()
    for a in soup.select('a[href^="mailto:"]'):
        found.update(EMAIL_RE.findall(a["href"].split("?")[0]))
    text = soup.get_text(" ")
    found.update(EMAIL_RE.findall(text))
    found.update(f"{u}@{d}.{t}" for u, d, t in OBFUSCATED_RE.findall(text))
    emails = {e.lower() for e in found if not e.lower().endswith(IMAGE_SUFFIXES)}
    if not include_personal:
        emails = {e for e in emails if e.split("@")[1] not in FREE_MAIL}
    return sorted(emails)


def extract_phones(html):
    text = BeautifulSoup(html, "html.parser").get_text(" ")
    return sorted({re.sub(r"\s+", " ", p).strip() for p in PHONE_RE.findall(text)})


def extract_name(html):
    soup = BeautifulSoup(html, "html.parser")
    og = soup.find("meta", property="og:site_name")
    if og and og.get("content"):
        return og["content"].strip()
    if soup.title and soup.title.string:
        return re.split(r"\s[|\-–—]\s", soup.title.string.strip())[-1].strip()
    return ""


def contact_links(html, base_url):
    """Same-domain links that look like contact/about pages."""
    host = urlparse(base_url).netloc
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        url = urljoin(base_url, a["href"]).split("#")[0]
        if urlparse(url).netloc != host:
            continue
        if any(h in url.lower() for h in SKIP_HINTS):
            continue
        if any(h in url.lower() or h in a.get_text().lower() for h in CONTACT_HINTS):
            if url not in links:
                links.append(url)
    return links
