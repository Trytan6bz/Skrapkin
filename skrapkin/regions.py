"""Countries and their first-level regions (ISO 3166), plus safe handling of free-text place names."""

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

PLACE_MAX = 80


@lru_cache(maxsize=1)
def _data():
    return json.loads((Path(__file__).parent / "data" / "regions.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _country_names():
    return {c["code"]: c["name"] for c in _data()["countries"]}


def countries():
    return _data()["countries"]


def is_country(code):
    return isinstance(code, str) and code.upper() in _country_names()


_ALIASES = {"usa": "US", "u.s.": "US", "u.s.a.": "US", "uk": "GB", "great britain": "GB", "britain": "GB",
            "uae": "AE", "russia": "RU", "south korea": "KR", "korea": "KR", "vietnam": "VN", "taiwan": "TW",
            "ivory coast": "CI", "czech republic": "CZ", "turkey": "TR"}


def find_country(text):
    """Resolve an ISO code (NG), a name (Nigeria), or a common alias (UK) to a country code, or None."""
    wanted = _fold(text or "")
    if not wanted:
        return None
    if wanted.upper() in _country_names():
        return wanted.upper()
    for code, name in _country_names().items():
        if _fold(name) == wanted:
            return code
    return _ALIASES.get(wanted)


def country_name(code):
    return _country_names().get(str(code).upper(), str(code))


def regions(country):
    """[{code, name}] for a country's first-level regions (states, provinces, nations...). May be empty."""
    return [{"code": c, "name": n} for c, n in _data()["regions"].get(str(country).upper(), [])]


def _fold(text):
    """Case- and accent-insensitive form for matching user input to names."""
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch)).casefold().strip()


def find_region(country, text):
    """Resolve an ISO 3166-2 code (US-TX) or a name (Texas, texas) to {code, name}, or None."""
    wanted = _fold(text or "")
    if not wanted:
        return None
    for r in regions(country):
        if wanted in (_fold(r["code"]), _fold(r["name"])):
            return r
    return None


def clean_place(text):
    """Validate a free-text city/area name. Returns '' for blank; raises ValueError for unusable input."""
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return ""
    if len(text) > PLACE_MAX:
        raise ValueError(f"The city or area name must be at most {PLACE_MAX} characters.")
    if any(unicodedata.category(ch).startswith("C") for ch in text):
        raise ValueError("The city or area name contains characters that aren't allowed.")
    return text


def ql_quote(text):
    """Escape a value for use inside a double-quoted Overpass QL string."""
    return text.replace("\\", "\\\\").replace('"', '\\"')
