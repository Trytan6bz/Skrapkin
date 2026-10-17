"""Regenerate skrapkin/data/regions.json from ISO 3166 (needs: pip install pycountry).

The app reads the generated JSON, so pycountry is only needed to refresh it. Regions are the top-level
ISO 3166-2 subdivisions of each country (states, provinces, nations, prefectures...), which OpenStreetMap
also tags on its boundaries as ISO3166-2.
"""

import json
import re
from pathlib import Path

import pycountry

countries = [{"code": c.alpha_2, "name": getattr(c, "common_name", c.name)}
             for c in sorted(pycountry.countries, key=lambda c: getattr(c, "common_name", c.name))]
regions = {}
for s in pycountry.subdivisions:
    if s.parent_code is None:
        regions.setdefault(s.country_code, []).append([s.code, re.sub(r"\s*\[.*?\]", "", s.name).strip()])
for code in regions:
    regions[code].sort(key=lambda r: r[1])

out = Path(__file__).resolve().parent.parent / "skrapkin" / "data" / "regions.json"
out.write_text(json.dumps({"countries": countries, "regions": regions}, ensure_ascii=False, separators=(",", ":")),
               encoding="utf-8")
print(f"{len(countries)} countries, {sum(map(len, regions.values()))} regions -> {out} ({out.stat().st_size // 1024} KB)")
