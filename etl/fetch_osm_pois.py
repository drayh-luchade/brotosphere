#!/usr/bin/env python3
"""
fetch_osm_pois.py

Pulls raw point-of-interest data from OpenStreetMap via the Overpass API
for every category in CATEGORIES and writes one GeoJSON file per category
to data/raw/. This is step 1 of the real pipeline (see etl/README.md).

Requires network access to overpass-api.de (or a mirror) -- this will NOT
run inside a network-restricted sandbox. Run it from a normal machine or
inside the GitHub Action, which has full internet access.

A single "give me every bar in the continental US" query is too heavy for
a shared public Overpass instance -- it either times out or gets rejected
outright as abusive load (the 406 you may have seen). So each category is
split into a grid of smaller regional tiles, fetched one at a time, then
merged and de-duplicated by OSM id. This is slower (dozens of small
requests instead of one big one) but far more reliable, and a single
tile failing doesn't take down the whole category.

Usage:
    python3 etl/fetch_osm_pois.py                 # fetch everything
    python3 etl/fetch_osm_pois.py --only bars golf # fetch a subset
    python3 etl/fetch_osm_pois.py --rows 4 --cols 6 # change tile grid size
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

# south, west, north, east
CONUS_BBOX = (24.5, -125.0, 49.5, -66.9)

TILE_ROWS = 4   # latitude bands
TILE_COLS = 6   # longitude bands -- 24 tiles total by default

TILE_TIMEOUT_S = 60          # Overpass server-side [timeout:] per tile
REQUEST_TIMEOUT_S = 90        # urllib socket timeout per tile request
RETRIES_PER_MIRROR = 2
SLEEP_BETWEEN_REQUESTS_S = 2  # be polite to the free public instance

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


def build_tiles(bbox, rows, cols):
    """Split (south, west, north, east) into rows x cols sub-bboxes."""
    south, west, north, east = bbox
    lat_step = (north - south) / rows
    lon_step = (east - west) / cols
    tiles = []
    for r in range(rows):
        for c in range(cols):
            s = south + r * lat_step
            n = south + (r + 1) * lat_step
            w = west + c * lon_step
            e = west + (c + 1) * lon_step
            tiles.append((s, w, n, e))
    return tiles


def build_query(filters, bbox):
    bbox_str = ",".join(str(x) for x in bbox)
    clauses = "\n".join(f"  {f}({bbox_str});" for f in filters)
    return f"""
[out:json][timeout:{TILE_TIMEOUT_S}];
(
{clauses}
);
out center;
""".strip()


def fetch_tile(query):
    """POST one Overpass query, trying each mirror with a couple of
    retries. Returns the parsed JSON payload, or raises on total failure."""
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "*/*",
        # Overpass (and most public APIs) reject requests with the
        # default urllib User-Agent as unidentified bot traffic (406).
        # Swap the contact email for your own if you're running this
        # regularly, per Overpass's usage policy.
        "User-Agent": "brotosphere-etl/1.0 (contact: replace-with-your-email@example.com)",
    }

    last_err = None
    for url in OVERPASS_URLS:
        for attempt in range(1, RETRIES_PER_MIRROR + 1):
            req = urllib.request.Request(url, data=("data=" + query).encode("utf-8"), headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", errors="replace")[:300]
                print(f"    {url} attempt {attempt} -> HTTP {e.code}: {body}", file=sys.stderr)
                last_err = e
            except Exception as e:
                print(f"    {url} attempt {attempt} -> {e}", file=sys.stderr)
                last_err = e
            time.sleep(3 * attempt)  # brief backoff before retrying/switching mirror

    raise RuntimeError("all mirrors/retries exhausted for this tile") from last_err


def elements_to_features(elements):
    features = {}  # (type, id) -> feature, for de-dup across tile borders
    for el in elements:
        if el["type"] == "node":
            lat, lon = el["lat"], el["lon"]
        elif "center" in el:
            lat, lon = el["center"]["lat"], el["center"]["lon"]
        else:
            continue
        key = (el["type"], el.get("id"))
        features[key] = {
            "type": "Feature",
            "properties": {"osm_id": el.get("id"), "tags": el.get("tags", {})},
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
        }
    return features


def fetch_category(name, filters, tiles):
    all_features = {}
    failed_tiles = 0

    for i, tile in enumerate(tiles, start=1):
        query = build_query(filters, tile)
        print(f"  tile {i}/{len(tiles)}...", end=" ", flush=True)
        try:
            payload = fetch_tile(query)
            tile_features = elements_to_features(payload.get("elements", []))
            all_features.update(tile_features)
            print(f"+{len(tile_features)} (running total {len(all_features)})")
        except Exception as e:
            failed_tiles += 1
            print(f"FAILED ({e}) -- skipping this tile")
        time.sleep(SLEEP_BETWEEN_REQUESTS_S)

    fc = {"type": "FeatureCollection", "features": list(all_features.values())}
    return fc, failed_tiles


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="Subset of category names to fetch")
    ap.add_argument("--out", default="data/raw")
    ap.add_argument("--rows", type=int, default=TILE_ROWS)
    ap.add_argument("--cols", type=int, default=TILE_COLS)
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    names = args.only or list(CATEGORIES.keys())
    tiles = build_tiles(CONUS_BBOX, args.rows, args.cols)
    print(f"Grid: {args.rows} x {args.cols} = {len(tiles)} tiles per category")

    any_category_totally_failed = False

    for name in names:
        if name not in CATEGORIES:
            print(f"Unknown category: {name}", file=sys.stderr)
            continue
        print(f"Fetching {name}...")
        fc, failed_tiles = fetch_category(name, CATEGORIES[name], tiles)
        out_path = os.path.join(args.out, f"{name}.geojson")

        if failed_tiles == len(tiles):
            # Every tile failed -- almost certainly a network/API outage,
            # not "this category genuinely has zero results." Don't
            # overwrite a previous good file with an empty one.
            print(f"  ALL {len(tiles)} tiles failed for '{name}' -- leaving {out_path} untouched.")
            any_category_totally_failed = True
            continue

        with open(out_path, "w") as f:
            json.dump(fc, f)
        note = f", {failed_tiles} tile(s) failed and were skipped" if failed_tiles else ""
        print(f"  -> {out_path} ({len(fc['features'])} features{note})")

    if any_category_totally_failed:
        print("One or more categories failed completely -- see log above.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
