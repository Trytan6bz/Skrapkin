"""Decide which emails are worth a paid Hunter lookup. Everything here is free and local."""

import re
from dataclasses import dataclass, field

from .extract import FREE_MAIL
from .validate import is_junk_email, mx_status, registered_domain

EMAIL_STRICT = re.compile(
    r"^[a-z0-9](?:[a-z0-9._%+-]{0,62}[a-z0-9])?@(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$")
ROLE_LOCALS = {"info", "sales", "contact", "hello", "office", "support", "admin", "orders", "service",
               "enquiries", "inquiries", "team", "help", "customerservice", "quotes", "estimating",
               "billing", "accounting", "marketing", "bids", "purchasing", "wholesale", "store"}
# Not exhaustive: Hunter flags the rest, but these are free to catch here.
DISPOSABLE = {"mailinator.com", "guerrillamail.com", "10minutemail.com", "tempmail.com", "yopmail.com",
              "trashmail.com", "throwawaymail.com", "sharklasers.com", "getnada.com", "maildrop.cc",
              "temp-mail.org", "dispostable.com", "fakeinbox.com", "mailnesia.com"}
PERSON_RE = re.compile(r"^[a-z]{2,}[._-][a-z]{2,}$|^[a-z]\.?[a-z]{3,}$")
VOWELS = set("aeiouy")


@dataclass
class Verdict:
    score: int
    reasons: list = field(default_factory=list)
    reject: str = ""        # non-empty: never send to Hunter, and why
    webmail: bool = False   # free-mail: SMTP can't confirm these, so Hunter adds nothing

    @property
    def reject_reason(self):
        return self.reject


def looks_gibberish(local):
    letters = re.sub(r"[^a-z]", "", local)
    if len(local) >= 8 and sum(c.isdigit() for c in local) / len(local) > 0.4:
        return True
    if len(letters) >= 8 and not (set(letters) & VOWELS):
        return True
    return bool(re.search(r"[^aeiouy\W\d_]{6,}", local))


def likelihood(email, website="", source="site", mx=mx_status):
    """Score 0-100: how likely this is a real, reachable business mailbox.

    source is where we found it: 'site' (scraped from the business's own pages) or 'osm'
    (published by the business in OpenStreetMap).
    """
    email = email.strip().lower()
    local, _, domain = email.partition("@")
    if len(email) > 254 or not EMAIL_STRICT.match(email):
        return Verdict(0, reject="not a valid email format")
    if is_junk_email(email):
        return Verdict(0, reject="placeholder or system address")
    if domain in DISPOSABLE:
        return Verdict(0, reject="disposable email provider")
    if domain in FREE_MAIL:
        return Verdict(50, ["webmail address"], webmail=True)
    if looks_gibberish(local):
        return Verdict(0, reject="looks auto-generated")

    reasons, score = [], 40
    if website and registered_domain(domain) == registered_domain(website):
        score += 30
        reasons.append("on the business's own domain")
    elif source == "osm":
        score += 25
        reasons.append("published by the business")
    elif website:
        score -= 15  # a different company's domain: probably a partner, web designer, or parent brand
        reasons.append("on a different company's domain")
    if local in ROLE_LOCALS:
        score += 10
        reasons.append("shared mailbox (info/sales/...)")
    elif PERSON_RE.match(local):
        score += 5
        reasons.append("looks like a person's name")

    dns = mx(domain)
    if dns == "bad":
        return Verdict(0, reject="domain cannot receive email")
    if dns == "ok":
        score += 10
        reasons.append("domain accepts email")
    else:
        score -= 10
        reasons.append("domain check inconclusive")
    return Verdict(max(0, min(100, score)), reasons)
