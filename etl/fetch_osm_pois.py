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
a shared public Overpass instance, so each category is split into a grid
of smaller regional tiles, fetched one at a time, then merged and
de-duplicated by OSM id.

Two things worth knowing about the public Overpass instances specifically:

1. GitHub Actions runners share IP ranges with a lot of other CI traffic,
   and Overpass's abuse protection often throttles/blocks those ranges
   outright (406s, 429s, 504s) regardless of how small your query is.
   Retries help some, but there's a point past which waiting longer just
   wastes CI minutes on a connection that isn't going to succeed. So
   retries here are intentionally short and few -- fail fast, move on.
2. Because of (1), some tiles will fail most runs. Rather than treat that
   as data loss, each category's fetch is merged against whatever
   data/raw/<category>.geojson already exists on disk: a successful tile
   overwrites its slice of that data, a failed tile just leaves the old
   data in place. Coverage fills in gradually across runs instead of
   flickering between complete and empty.

Usage:
    python3 etl/fetch_osm_pois.py                 # fetch everything
    python3 etl/fetch_osm_pois.py --only bars golf # fetch a subset
    python3 etl/fetch_osm_pois.py --rows 4 --cols 6 # change tile grid size
"""
import argparse
import glob
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

TILE_TIMEOUT_S = 45           # Overpass server-side [timeout:] per tile
REQUEST_TIMEOUT_S = 35         # urllib socket timeout per attempt
RETRIES_PER_MIRROR = 1         # one try per mirror, then give up on this tile
BACKOFF_S = 2                  # brief pause between attempts
SLEEP_BETWEEN_REQUESTS_S = 3   # pause between tiles, successful or not

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
    """POST one Overpass query: one attempt per mirror, short timeout,
    short backoff. Returns the parsed JSON payload, or raises on total
    failure. Deliberately doesn't linger -- a blocked/throttled CI IP
    isn't going to start working after a long wait."""
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
                body = e.read().decode("utf-8", errors="replace")[:200]
                print(f"    {url} -> HTTP {e.code}: {body}", file=sys.stderr)
                last_err = e
            except Exception as e:
                print(f"    {url} -> {e}", file=sys.stderr)
                last_err = e
            time.sleep(BACKOFF_S)

    raise RuntimeError("all mirrors exhausted for this tile") from last_err


def elements_to_features(elements):
    features = {}  # (osm_type, osm_id) -> feature, for de-dup across tiles
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
            "properties": {"osm_type": el["type"], "osm_id": el.get("id"), "tags": el.get("tags", {})},
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
        }
    return features


def load_existing(path):
    """Load a previous run's output for this category, keyed the same way
    as elements_to_features, so it can serve as the merge baseline."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            fc = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    baseline = {}
    for ft in fc.get("features", []):
        props = ft.get("properties", {})
        key = (props.get("osm_type"), props.get("osm_id"))
        baseline[key] = ft
    return baseline


def fetch_category(name, filters, tiles, existing_path):
    all_features = load_existing(existing_path)
    baseline_count = len(all_features)
    failed_tiles = 0
    succeeded_tiles = 0

    for i, tile in enumerate(tiles, start=1):
        query = build_query(filters, tile)
        print(f"  tile {i}/{len(tiles)}...", end=" ", flush=True)
        try:
            payload = fetch_tile(query)
            tile_features = elements_to_features(payload.get("elements", []))
            all_features.update(tile_features)
            succeeded_tiles += 1
            print(f"+{len(tile_features)} (running total {len(all_features)})")
        except Exception as e:
            failed_tiles += 1
            print(f"FAILED ({e}) -- keeping any previous data for this area")
        time.sleep(SLEEP_BETWEEN_REQUESTS_S)

    fc = {"type": "FeatureCollection", "features": list(all_features.values())}
    return fc, succeeded_tiles, failed_tiles, baseline_count


def clean_stale_raw_files(raw_dir):
    """Remove any data/raw/*.geojson that no longer matches a known
    category (e.g. a category was renamed or deleted since the last run)."""
    if not os.path.isdir(raw_dir):
        return
    valid = {f"{name}.geojson" for name in CATEGORIES}
    for path in glob.glob(os.path.join(raw_dir, "*.geojson")):
        if os.path.basename(path) not in valid:
            print(f"Removing stale raw file: {path}")
            os.remove(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="Subset of category names to fetch")
    ap.add_argument("--out", default="data/raw")
    ap.add_argument("--rows", type=int, default=TILE_ROWS)
    ap.add_argument("--cols", type=int, default=TILE_COLS)
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    clean_stale_raw_files(args.out)
    names = args.only or list(CATEGORIES.keys())
    tiles = build_tiles(CONUS_BBOX, args.rows, args.cols)
    print(f"Grid: {args.rows} x {args.cols} = {len(tiles)} tiles per category")

    any_category_totally_empty = False

    for name in names:
        if name not in CATEGORIES:
            print(f"Unknown category: {name}", file=sys.stderr)
            continue
        print(f"Fetching {name}...")
        out_path = os.path.join(args.out, f"{name}.geojson")
        fc, succeeded, failed, baseline_count = fetch_category(name, CATEGORIES[name], tiles, out_path)

        if succeeded == 0 and baseline_count == 0:
            # Every tile failed and there was no prior data to fall back
            # on -- writing an empty file would look like "zero results"
            # rather than "the fetch never worked." Skip the write.
            print(f"  ALL {len(tiles)} tiles failed for '{name}' and no previous data exists -- skipping write.")
            any_category_totally_empty = True
            continue

        with open(out_path, "w") as f:
            json.dump(fc, f)
        print(f"  -> {out_path} ({len(fc['features'])} features; "
              f"{succeeded}/{len(tiles)} tiles refreshed this run, {failed} kept previous data)")

    if any_category_totally_empty:
        print("One or more categories have never successfully fetched -- see log above.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
