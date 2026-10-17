"""Find bulk-buyer businesses in an area via OpenStreetMap (Overpass API, open data)."""

import time

import requests

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

# Preset -> OSM tag filters. Each filter is key=regex-of-values.
US_STATES = [
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado", "Connecticut", "Delaware",
    "District of Columbia", "Florida", "Georgia", "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa",
    "Kansas", "Kentucky", "Louisiana", "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota",
    "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada", "New Hampshire", "New Jersey",
    "New Mexico", "New York", "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon",
    "Pennsylvania", "Rhode Island", "South Carolina", "South Dakota", "Tennessee", "Texas", "Utah",
    "Vermont", "Virginia", "Washington", "West Virginia", "Wisconsin", "Wyoming",
]

CATEGORIES = {
    "building": [("shop", "doityourself|hardware|trade|building_materials|electrical|paint|tiles|flooring"),
                 ("craft", "builder|carpenter|electrician|plumber|roofer|hvac|painter|tiler")],
    "clothing": [("shop", "clothes|boutique|fashion|shoes|fabric|second_hand")],
    "toys": [("shop", "toys|games|baby_goods|variety_store|gift")],
}


def build_query(area, category, country=None, admin_level=None):
    # admin_level 4 is a US state; it stops "New York" matching the city as well as the state.
    level_filter = f'["admin_level"="{admin_level}"]' if admin_level else ""
    if country:
        lines = [f'area["ISO3166-1"="{country}"]->.c;',
                 f'rel(area.c)["name"="{area}"]["boundary"="administrative"]{level_filter};',
                 "map_to_area->.a;", "("]
    else:
        lines = [f'area["name"="{area}"]["boundary"="administrative"]{level_filter}->.a;', "("]
    for key, values in CATEGORIES[category]:
        lines.append(f'  nwr["{key}"~"^({values})$"](area.a);')
    lines.append(");")
    lines.append("out tags center;")
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


def discover(area, category, country=None):
    admin_level = 4 if country == "US" and area in US_STATES else None
    query = build_query(area, category, country, admin_level)
    last_error = None
    for attempt in range(3):
        for url in OVERPASS_URLS:
            try:
                resp = requests.post(url, data={"data": query}, timeout=200,
                                     headers={"User-Agent": "SKrapkin/0.1"})
                resp.raise_for_status()
                return parse_elements(resp.json().get("elements", []), category)
            except (requests.RequestException, ValueError) as e:
                last_error = e
        time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"Overpass API unavailable after retries: {last_error}")
