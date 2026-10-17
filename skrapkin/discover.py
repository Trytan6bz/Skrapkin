"""Find bulk-buyer businesses anywhere in the world via OpenStreetMap (Overpass API, open data)."""

import time

import requests

from . import regions as geo

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

# Preset -> OSM tag filters. Each filter is key=regex-of-values. OSM tags are the same worldwide.
CATEGORIES = {
    "building": [("shop", "doityourself|hardware|trade|building_materials|electrical|paint|tiles|flooring"),
                 ("craft", "builder|carpenter|electrician|plumber|roofer|hvac|painter|tiler")],
    "clothing": [("shop", "clothes|boutique|fashion|shoes|fabric|second_hand")],
    "toys": [("shop", "toys|games|baby_goods|variety_store|gift")],
}


def build_query(category, country, region=None, place=None, cap=None):
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
    return "[out:json][timeout:180];\n" + "\n".join(lines)


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


def discover(category, country, region=None, place=None, limit=None):
    if category not in CATEGORIES:
        raise ValueError(f"Unknown category: {category!r}")
    region = resolve_region(country, region)
    place = geo.clean_place(place) if place else ""
    # The server returns matches in id order, so cap what it sends for big areas. Keep headroom,
    # because chains and non-buyers are dropped afterwards.
    cap = min(max(limit * 8, 400), 20000) if limit else None
    query = build_query(category, country, region, place, cap)
    last_error = None
    for attempt in range(3):
        for url in OVERPASS_URLS:
            try:
                resp = requests.post(url, data={"data": query}, timeout=200,
                                     headers={"User-Agent": "SKrapkin/0.2"})
                resp.raise_for_status()
                return parse_elements(resp.json().get("elements", []), category)
            except (requests.RequestException, ValueError) as e:
                last_error = e
        time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"Overpass API unavailable after retries: {last_error}")
