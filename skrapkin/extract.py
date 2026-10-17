"""Pull business contact details out of a page."""

import re
from urllib.parse import urljoin, urlparse

import phonenumbers
from bs4 import BeautifulSoup

from .validate import registered_domain

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
OBFUSCATED_RE = re.compile(
    r"([A-Za-z0-9._%+-]+)\s*[\[(]\s*at\s*[\])]\s*([A-Za-z0-9.-]+)\s*[\[(]\s*dot\s*[\])]\s*([A-Za-z]{2,})",
    re.IGNORECASE,
)

# Personal mailbox providers: kept by default (small businesses often use them); drop with --exclude-personal.
FREE_MAIL = {
    "gmail.com", "googlemail.com", "yahoo.com", "ymail.com", "rocketmail.com", "hotmail.com", "outlook.com",
    "aol.com", "icloud.com", "me.com", "live.com", "msn.com", "proton.me", "protonmail.com", "pm.me",
    "mail.com", "gmx.com", "gmx.net", "gmx.de", "gmx.at", "web.de", "t-online.de", "freenet.de",
    "yahoo.co.uk", "yahoo.co.in", "yahoo.co.jp", "yahoo.com.br", "yahoo.com.au", "yahoo.fr", "yahoo.de",
    "yahoo.es", "yahoo.it", "yahoo.ca", "hotmail.co.uk", "hotmail.fr", "hotmail.de", "hotmail.es",
    "hotmail.it", "outlook.fr", "outlook.de", "outlook.es", "live.co.uk", "live.fr", "btinternet.com",
    "sky.com", "orange.fr", "wanadoo.fr", "free.fr", "sfr.fr", "laposte.net", "libero.it", "virgilio.it",
    "alice.it", "tiscali.it", "mail.ru", "bk.ru", "inbox.ru", "list.ru", "yandex.ru", "yandex.com",
    "rambler.ru", "qq.com", "163.com", "126.com", "sina.com", "foxmail.com", "naver.com", "daum.net",
    "hanmail.net", "rediffmail.com", "seznam.cz", "wp.pl", "o2.pl", "interia.pl", "onet.pl", "uol.com.br",
    "bol.com.br", "terra.com.br", "ig.com.br", "tutanota.com", "tuta.io", "zoho.com", "yopmail.com",
}
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")
CONTACT_HINTS = (
    "contact", "about", "team", "support", "impressum",                        # English / German
    "kontakt", "ueber-uns", "uber-uns", "über-uns", "unternehmen",              # German, Polish, Nordic
    "contacto", "nosotros", "quienes-somos", "equipo", "empresa",               # Spanish
    "contato", "sobre", "fale-conosco", "equipe",                               # Portuguese
    "contatti", "contatto", "chi-siamo", "azienda",                             # Italian
    "nous-contacter", "a-propos", "qui-sommes-nous", "mentions-legales",        # French
    "over-ons", "o-nas", "kapcsolat", "yhteystiedot", "iletisim", "hakkimizda",  # Dutch, Slavic, Hungarian, Finnish, Turkish
    "контакты", "о-нас", "о нас",                                               # Russian
    "联系", "聯絡", "关于", "關於", "お問い合わせ", "お問合せ", "会社概要", "연락", "문의", "회사소개",
    "اتصل", "من نحن",
)
# Pages listing many branches/partners pollute results with other entities' details.
SKIP_HINTS = ("location", "store", "branch", "dealer", "franchise", "find-us", "standort", "filiale",
              "sucursal", "tiendas", "lojas", "negozi", "magasins", "succursale", "vestiging")


def filter_free_mail(emails, include_personal=True):
    if include_personal:
        return set(emails)
    return {e for e in emails if e.split("@")[1] not in FREE_MAIL}


def same_site_emails(emails, site_url):
    """Keep addresses on the business's own domain (or a subdomain/parent of it).

    Free-mail addresses found on the site are kept: small businesses often list them as their contact.
    """
    site = registered_domain(site_url)
    return {e for e in emails if (d := e.split("@")[1]) in FREE_MAIL or registered_domain(d) == site}


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


def extract_phones(html, region="US"):
    """Phone numbers in E.164 form, in page order. `region` (ISO country) resolves local formats."""
    text = BeautifulSoup(html, "html.parser").get_text(" ")
    found = []
    for match in phonenumbers.PhoneNumberMatcher(text, region.upper(), leniency=phonenumbers.Leniency.VALID):
        number = phonenumbers.format_number(match.number, phonenumbers.PhoneNumberFormat.E164)
        if number not in found:
            found.append(number)
    return found


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
