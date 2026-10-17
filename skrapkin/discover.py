"""Find bulk-buyer businesses anywhere in the world via OpenStreetMap (Overpass API, open data)."""

import threading
import time

import requests

from . import regions as geo

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
POLL_SECONDS = 0.5        # how often a running search checks whether you pressed Stop
WAIT_REPORT_SECONDS = 10  # how often it reports "still waiting"
MAX_TOTAL_SECONDS = 8 * 60


class DiscoveryError(RuntimeError):
    """A problem with finding businesses. The message is written for the user."""


class AreaTooLarge(DiscoveryError):
    pass


class ServiceBusy(DiscoveryError):
    pass


class Cancelled(Exception):
    """The user pressed Stop."""


# Preset -> OSM tag filters. Each filter is key=regex-of-values. OSM tags are the same worldwide.
CATEGORIES = {
    "building": [("shop", "doityourself|hardware|trade|building_materials|electrical|paint|tiles|flooring"),
                 ("craft", "builder|carpenter|electrician|plumber|roofer|hvac|painter|tiler")],
    "clothing": [("shop", "clothes|boutique|fashion|shoes|fabric|second_hand")],
    "toys": [("shop", "toys|games|baby_goods|variety_store|gift")],
}


def build_query(category, country, region=None, place=None, cap=None, timeout=180):
    """Overpass QL for businesses of `category` in a country, optionally narrowed to a region and a place.

    `country` is validated ISO 3166-1; `region` is {code, name} from regions.py; `place` is a validated
    free-text name. All interpolated values are validated or escaped.
    """
    if not geo.is_country(country):
        raise ValueError(f"Unknown country code: {country!r}")
    lines = [f'area["ISO3166-1"="{country.upper()}"]->.c;']
    base = "c"
    if region:
        name = geo.ql_quote(region["name"])
        # OSM tags first-level boundaries with their ISO 3166-2 code; the name match is a fallback for
        # the few that lack it. admin_level 3-5 keeps a city called "New York" out of the state match.
        lines += ["(",
                  f'  rel(area.c)["boundary"="administrative"]["ISO3166-2"="{region["code"]}"];',
                  f'  rel(area.c)["boundary"="administrative"]["admin_level"~"^[3-5]$"]["name"="{name}"];',
                  f'  rel(area.c)["boundary"="administrative"]["admin_level"~"^[3-5]$"]["name:en"="{name}"];',
                  ");", "map_to_area->.r;"]
        base = "r"
    if place:
        quoted = geo.ql_quote(place)
        lines += ["(",
                  f'  rel(area.{base})["boundary"="administrative"]["name"="{quoted}"];',
                  f'  rel(area.{base})["boundary"="administrative"]["name:en"="{quoted}"];',
                  ");", "map_to_area->.a;"]
    else:
        lines.append(f"(.{base};)->.a;")
    lines.append("(")
    for key, values in CATEGORIES[category]:
        lines.append(f'  nwr["{key}"~"^({values})$"](area.a);')
    lines.append(");")
    lines.append(f"out tags center{f' {int(cap)}' if cap else ''};")
    return f"[out:json][timeout:{int(timeout)}];\n" + "\n".join(lines)


def parse_elements(elements, category):
    leads = []
    for el in elements:
        t = el.get("tags", {})
        name = t.get("name")
        if not name:
            continue
        leads.append({
            "category": category,
            "business": name,
            "website": t.get("website") or t.get("contact:website") or "",
            "phone": t.get("phone") or t.get("contact:phone") or "",
            "email": t.get("email") or t.get("contact:email") or "",
            "city": t.get("addr:city", ""),
            "brand": t.get("brand", ""),
        })
    return leads


def resolve_region(country, region):
    """Accept an ISO code, a name, or an already-resolved {code, name}; raise ValueError if unknown."""
    if not region:
        return None
    if isinstance(region, dict):
        return region
    found = geo.find_region(country, region)
    if found is None:
        raise ValueError(f"'{region}' isn't a known region of {geo.country_name(country)}.")
    return found


def _post(url, query, wait, should_stop, on_wait, started):
    """POST on a helper thread so a Stop request can abandon it within half a second.

    The thread can't be killed mid-request, so it is left to finish on its own (it is a daemon and its
    result is discarded). Returns the response, or raises Cancelled / the request's own error.
    """
    box = {}

    def run():
        try:
            box["resp"] = requests.post(url, data={"data": query}, timeout=(10, wait),
                                        headers={"User-Agent": "SKrapkin/0.2"})
        except Exception as e:  # reported to the caller below
            box["error"] = e

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    last_report = 0.0
    while worker.is_alive():
        worker.join(POLL_SECONDS)
        if should_stop():
            raise Cancelled()
        elapsed = time.monotonic() - started
        if on_wait and elapsed - last_report >= WAIT_REPORT_SECONDS:
            last_report = elapsed
            on_wait(elapsed)
    if "error" in box:
        raise box["error"]
    return box["resp"]


def _pause(seconds, should_stop):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if should_stop():
            raise Cancelled()
        time.sleep(POLL_SECONDS)


def discover(category, country, region=None, place=None, limit=None, should_stop=None, on_wait=None,
             skip=0):
    """Find businesses. Raises Cancelled if should_stop() turns true, DiscoveryError for problems the
    user can act on (area too large, server busy)."""
    should_stop = should_stop or (lambda: False)
    if category not in CATEGORIES:
        raise ValueError(f"Unknown category: {category!r}")
    region = resolve_region(country, region)
    place = geo.clean_place(place) if place else ""
    # The server returns matches in id order, so cap what it sends for big areas. Keep headroom, because
    # chains and non-buyers are dropped afterwards, and `skip` businesses were already checked on earlier
    # runs (they come first in that order, so the cap has to reach past them to find new ones).
    cap = min(max((limit + skip) * 8, 400), 20000) if limit else None
    # A query that timed out will time out again, so don't keep retrying it. Whole-country searches are
    # the heaviest, so they get a short leash and fail fast with advice instead of making you wait.
    whole_country = not (region or place)
    server_limit = 45 if whole_country else 120
    query = build_query(category, country, region, place, cap, timeout=server_limit)
    wait = server_limit + 15
    started = time.monotonic()
    last_problem = "no response"
    slow_replies = 0
    empty_replies = 0
    too_large = AreaTooLarge("That area is too large for the free OpenStreetMap server to search in time. "
                             "Choose a region or a city and try again.")
    for attempt in range(3):
        for url in OVERPASS_URLS:
            if time.monotonic() - started > MAX_TOTAL_SECONDS:
                raise ServiceBusy("OpenStreetMap is too busy right now. Try again in a few minutes.")
            try:
                resp = _post(url, query, wait, should_stop, on_wait, started)
            except requests.ReadTimeout:
                # The server never answered within its own limit: the area is too heavy, or it is overloaded.
                slow_replies += 1
                if whole_country or slow_replies >= 2:
                    raise too_large
                last_problem = "no answer in time"
                continue
            except requests.RequestException as e:
                last_problem = type(e).__name__
                continue
            if resp.status_code in RETRYABLE_STATUS:
                last_problem = f"HTTP {resp.status_code}"
                continue
            if not resp.ok:
                raise DiscoveryError(f"OpenStreetMap rejected the search (HTTP {resp.status_code}).")
            try:
                body = resp.json()
            except ValueError:
                last_problem = "unreadable reply"
                continue
            elements = body.get("elements", [])
            remark = str(body.get("remark", "")).lower()
            if not elements and ("timed out" in remark or "out of memory" in remark or "runtime error" in remark):
                raise too_large
            if not elements:
                # An empty answer can be wrong: a busy server sometimes returns nothing, and the backup server's
                # map data lags behind for some areas. Believe "nothing here" only when two answers agree.
                empty_replies += 1
                if empty_replies < 2:
                    last_problem = "an empty answer"
                    continue
            return parse_elements(elements, category)
        _pause(5 * (attempt + 1), should_stop)
    raise ServiceBusy("Couldn't get an answer from OpenStreetMap (" + last_problem + "). "
                      "The free servers are sometimes busy; try again in a minute.")
