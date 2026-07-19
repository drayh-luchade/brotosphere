#!/usr/bin/env python3
"""
fetch_osm_pois.py

Pulls raw point-of-interest data from OpenStreetMap via the Overpass API
for every category in CATEGORIES and writes one GeoJSON file per category
to data/raw/. This is step 1 of the real pipeline (see etl/README.md).

Requires network access to overpass-api.de (or a mirror) -- this will NOT
run inside a network-restricted sandbox. Run it from a normal machine or
inside the GitHub Action, which has full internet access.

Usage:
    python3 etl/fetch_osm_pois.py                 # fetch everything
    python3 etl/fetch_osm_pois.py --only bars golf # fetch a subset
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
CONUS_BBOX = "24.5,-125.0,49.5,-66.9"  # south,west,north,east

# Each category maps to one or more Overpass tag filters. Keep filters
# narrow -- broad tags like amenity=bar will also pull hotel bars, private
# clubs, etc. Tune these once you see real output for your area.
CATEGORIES = {
    "bars": [
        'node["amenity"="bar"]',
        'node["amenity"="pub"]',
    ],
    "breweries": [
        'node["craft"="brewery"]',
        'node["craft"="distillery"]',
        'node["amenity"="bar"]["microbrewery"="yes"]',
    ],
    "golf_courses": [
        'node["leisure"="golf_course"]',
        'way["leisure"="golf_course"]',
    ],
    "boat_ramps": [
        'node["leisure"="slipway"]',
        'node["leisure"="marina"]',
        'way["leisure"="marina"]',
    ],
    "fishing_access": [
        'node["leisure"="fishing"]',
        'node["natural"="water"]["fishing"="yes"]',
    ],
    "hardware_stores": [
        'node["shop"="hardware"]',
        'node["shop"="doityourself"]',
        'node["shop"="trade"]',
    ],
    "campgrounds": [
        'node["tourism"="camp_site"]',
        'node["tourism"="caravan_site"]',
    ],
    "bowling_pool_clubs": [
        'node["leisure"="bowling_alley"]',
        'node["leisure"="amusement_arcade"]["billiards"="yes"]',
        'node["club"="social"]',
        'node["amenity"="social_centre"]',
    ],
    "casinos": [
        'node["amenity"="casino"]',
    ],
}


def build_query(filters, bbox):
    clauses = "\n".join(f"  {f}({bbox});" for f in filters)
    return f"""
[out:json][timeout:180];
(
{clauses}
);
out center;
""".strip()


def fetch_category(name, filters, bbox=CONUS_BBOX):
    query = build_query(filters, bbox)
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        # Overpass (and most public APIs) reject requests with the
        # default urllib User-Agent as unidentified bot traffic (406).
        # Swap the contact email for your own if you're running this
        # regularly, per Overpass's usage policy.
        "User-Agent": "brotosphere-etl/1.0 (contact: replace-with-your-email@example.com)",
    }

    last_err = None
    for url in OVERPASS_URLS:
        req = urllib.request.Request(url, data=("data=" + query).encode("utf-8"), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=200) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:500]
            print(f"  {url} -> HTTP {e.code}: {body}", file=sys.stderr)
            last_err = e
        except Exception as e:
            print(f"  {url} -> {e}", file=sys.stderr)
            last_err = e
    else:
        raise RuntimeError(f"All Overpass mirrors failed for category '{name}'") from last_err

    features = []
    for el in payload.get("elements", []):
        if el["type"] == "node":
            lat, lon = el["lat"], el["lon"]
        elif "center" in el:
            lat, lon = el["center"]["lat"], el["center"]["lon"]
        else:
            continue
        features.append({
            "type": "Feature",
            "properties": {"osm_id": el.get("id"), "tags": el.get("tags", {})},
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
        })

    return {"type": "FeatureCollection", "features": features}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="Subset of category names to fetch")
    ap.add_argument("--out", default="data/raw")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    names = args.only or list(CATEGORIES.keys())

    for name in names:
        if name not in CATEGORIES:
            print(f"Unknown category: {name}", file=sys.stderr)
            continue
        print(f"Fetching {name}...")
        fc = fetch_category(name, CATEGORIES[name])
        out_path = os.path.join(args.out, f"{name}.geojson")
        with open(out_path, "w") as f:
            json.dump(fc, f)
        print(f"  -> {out_path} ({len(fc['features'])} features)")
        time.sleep(2)  # be polite to the public Overpass instance


if __name__ == "__main__":
    main()
