"""Settlements in Saudi Arabia from OpenStreetMap: every place node tagged city, town, village or hamlet.

model/manure.py uses them, with the mapped fields, to keep penned sheep and goats near farms and settlements (cells
within its NEAR_KM of a field or any place, hamlets included) and poultry houses near farms, cities, towns and villages
(no hamlets). It records this file's sha256 in data/national/manure_points.meta.json, so rerun model/manure.py after
rerunning this script (model/national_siting.py stops until then).

Source: OpenStreetMap contributors, through the Overpass API (data under the ODbL, openstreetmap.org/copyright).
Output: data/national/osm_places.csv  (lon, lat, place), one row per node, sorted
Run:    .venv/bin/python scripts/osm_places.py [saved_overpass.json]   (reads a saved Overpass JSON answer instead of
        querying, if given)
"""
import json
import sys
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "national" / "osm_places.csv"
URL = "https://overpass-api.de/api/interpreter"
QUERY = ('[out:json][timeout:170];area["ISO3166-1"="SA"][admin_level=2]->.a;'
         'node[place~"^(city|town|village|hamlet)$"](area.a);out;')


def main():
    if len(sys.argv) > 1:
        d = json.loads(Path(sys.argv[1]).read_text())
    else:
        r = requests.post(URL, data={"data": QUERY}, timeout=200,
                          headers={"User-Agent": "research-client/1.0", "Accept": "application/json"})
        r.raise_for_status()
        d = r.json()
    rows = [(round(e["lon"], 5), round(e["lat"], 5), e["tags"]["place"]) for e in d["elements"]
            if e.get("type") == "node" and "tags" in e]
    out = pd.DataFrame(rows, columns=["lon", "lat", "place"]).sort_values(["lon", "lat"]).reset_index(drop=True)
    out.to_csv(OUT, index=False)
    print(len(out), "places;", out.place.value_counts().to_dict(), "OSM snapshot",
          d.get("osm3s", {}).get("timestamp_osm_base", "?"))


if __name__ == "__main__":
    main()
