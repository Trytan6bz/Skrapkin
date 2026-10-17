"""Lead quality checks: junk filtering, deliverability, phone validity, chain detection."""

import re
from collections import Counter
from functools import lru_cache
from urllib.parse import urlparse

import dns.exception
import dns.resolver
import phonenumbers

JUNK_LOCALS = {"noreply", "no-reply", "donotreply", "do-not-reply", "abuse", "postmaster",
               "privacy", "unsubscribe", "mailer-daemon", "bounce", "bounces"}
# Template placeholders and tracking/error-reporting addresses that show up in page source.
JUNK_DOMAINS = {"example.com", "domain.com", "yourdomain.com", "email.com", "test.com",
                "sentry.io", "wixpress.com", "sentry-next.wixpress.com", "godaddy.com",
                "squarespace.com", "wordpress.com", "shopify.com"}
JUNK_LOCAL_RE = re.compile(r"^(your|user|name|email|first|last|example|test)(name|email)?$|^[0-9a-f]{16,}$")
# Aggregators and social pages are not the business's own site.
AGGREGATOR_DOMAINS = {"facebook.com", "instagram.com", "yelp.com", "linkedin.com", "twitter.com",
                      "x.com", "tiktok.com", "youtube.com", "yellowpages.com", "mapquest.com",
                      "google.com", "tripadvisor.com", "bbb.org"}
CHAIN_MIN_LOCATIONS = 3
# Organisations that match a trade tag but won't buy supplies for resale or projects.
NON_BUYER_RE = re.compile(
    r"\b(union|local \d+|local no|training|school|college|university|academy|association|church|"
    r"benefit|pension|apprentice\w*|institute|foundation|museum|library)\b", re.IGNORECASE)


def is_non_buyer(name):
    return bool(NON_BUYER_RE.search(name or ""))


def registered_domain(url_or_host):
    host = urlparse(url_or_host if "//" in url_or_host else "//" + url_or_host).netloc.lower()
    host = host.removeprefix("www.")
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def is_junk_email(email):
    local, _, domain = email.partition("@")
    return (local in JUNK_LOCALS or domain in JUNK_DOMAINS
            or bool(JUNK_LOCAL_RE.match(local)) or ".." in email)


@lru_cache(maxsize=None)
def mx_status(domain):
    """'ok' if the domain accepts mail, 'bad' if it provably doesn't, 'unknown' on DNS trouble."""
    for rtype in ("MX", "A"):
        try:
            if len(dns.resolver.resolve(domain, rtype, lifetime=6)):
                return "ok"
        except (dns.resolver.NXDOMAIN, dns.resolver.NoNameservers):
            return "bad"
        except dns.resolver.NoAnswer:
            continue
        except dns.exception.DNSException:
            return "unknown"
    return "bad"


def normalize_phone(raw, region="US"):
    """E.164 string if it's a valid number, else None."""
    try:
        num = phonenumbers.parse(raw, region)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(num):
        return None
    return phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)


def chain_domains(seeds):
    """Domains that appear for several seed businesses are chains/franchises, not independents."""
    counts = Counter(registered_domain(s["website"]) for s in seeds if s.get("website"))
    return {d for d, n in counts.items() if n >= CHAIN_MIN_LOCATIONS}


def is_aggregator(url):
    return registered_domain(url) in AGGREGATOR_DOMAINS


def confidence(emails_checked, phones, own_domain_email):
    """high: deliverable email on the business's own domain; medium: other deliverable email;
    low: phone only."""
    if own_domain_email:
        return "high"
    if emails_checked:
        return "medium"
    return "low" if phones else ""
