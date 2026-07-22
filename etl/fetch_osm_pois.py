#!/usr/bin/env python3
"""
fetch_osm_pois.py

Pulls raw point-of-interest data from OpenStreetMap via the Overpass API
for every category in CATEGORIES and writes one CSV file per category to
data/raw/ -- just "lon,lat" rows, nothing else. This is step 1 of the
real pipeline (see etl/README.md).

Why CSV and not GeoJSON: nothing downstream ever reads anything but the
coordinates (compute_metrics.py buckets points into hexes and discards
everything else), so there's no reason to pay GeoJSON's per-point
structural overhead (~80+ bytes of "type"/"properties"/"geometry" syntax
per point) or to store OSM tags (name, address, phone, website...) that
are never displayed anywhere. A CSV row is ~15 bytes. De-duplication uses
the rounded coordinate itself as the key rather than the OSM id, so no id
needs to be stored either -- this is genuinely just a location list.

Requires network access to overpass-api.de (or a mirror) -- this will NOT
run inside a network-restricted sandbox. Run it from a normal machine or
inside the GitHub Action, which has full internet access.

A single "give me every bar in the continental US" query is too heavy for
a shared public Overpass instance, so each category is split into a grid
of smaller regional tiles, fetched one at a time, then merged. See
etl/colab_state_fetch.py for a state-by-state alternative that's more
reliable (smaller regions, resumable, no CI time limit) for the "core"
categories -- this tiled national fetch is the fallback/bulk option for
everything else.

Usage:
    python3 etl/fetch_osm_pois.py                 # fetch everything
    python3 etl/fetch_osm_pois.py --only bars golf # fetch a subset
    python3 etl/fetch_osm_pois.py --rows 4 --cols 6 # change tile grid size
"""
import argparse
import csv
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

TILE_ROWS = 4
TILE_COLS = 6

TILE_TIMEOUT_S = 45
REQUEST_TIMEOUT_S = 35
RETRIES_PER_MIRROR = 1
BACKOFF_S = 2
SLEEP_BETWEEN_REQUESTS_S = 3
COORD_PRECISION = 5  # ~1.1m -- far finer than any hex bucket needs

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
        'node["name"~"Topgolf",i]',
        'way["name"~"Topgolf",i]',
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


def clean_stale_raw_files(raw_dir):
    """Remove any data/raw/*.csv that no longer matches a known category,
    and any leftover data/raw/*.geojson from the old (pre-CSV) format."""
    if not os.path.isdir(raw_dir):
        return
    valid = {f"{name}.csv" for name in CATEGORIES}
    for path in glob.glob(os.path.join(raw_dir, "*.csv")):
        if os.path.basename(path) not in valid:
            print(f"Removing stale raw file: {path}")
            os.remove(path)
    for path in glob.glob(os.path.join(raw_dir, "*.geojson")):
        print(f"Removing old-format raw file (GeoJSON -> CSV migration): {path}")
        os.remove(path)


def build_tiles(bbox, rows, cols):
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
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "*/*",
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


def elements_to_points(elements):
    """Returns a set of (lon, lat) tuples, rounded and de-duplicated.
    No id, no tags -- just locations."""
    points = set()
    for el in elements:
        if el["type"] == "node":
            lat, lon = el["lat"], el["lon"]
        elif "center" in el:
            lat, lon = el["center"]["lat"], el["center"]["lon"]
        else:
            continue
        points.add((round(lon, COORD_PRECISION), round(lat, COORD_PRECISION)))
    return points


def load_existing(path):
    if not os.path.exists(path):
        return set()
    points = set()
    try:
        with open(path, newline="") as f:
            reader = csv.reader(f)
            next(reader, None)  # header
            for row in reader:
                if len(row) == 2:
                    points.add((float(row[0]), float(row[1])))
    except (OSError, ValueError):
        return set()
    return points


def fetch_category(name, filters, tiles, existing_path):
    all_points = load_existing(existing_path)
    baseline_count = len(all_points)
    failed_tiles = 0
    succeeded_tiles = 0

    for i, tile in enumerate(tiles, start=1):
        query = build_query(filters, tile)
        print(f"  tile {i}/{len(tiles)}...", end=" ", flush=True)
        try:
            payload = fetch_tile(query)
            tile_points = elements_to_points(payload.get("elements", []))
            all_points |= tile_points
            succeeded_tiles += 1
            print(f"+{len(tile_points)} (running total {len(all_points)})")
        except Exception as e:
            failed_tiles += 1
            print(f"FAILED ({e}) -- keeping any previous data for this area")
        time.sleep(SLEEP_BETWEEN_REQUESTS_S)

    return all_points, succeeded_tiles, failed_tiles, baseline_count


def write_csv(path, points):
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["lon", "lat"])
        for lon, lat in sorted(points):
            writer.writerow([lon, lat])


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
        out_path = os.path.join(args.out, f"{name}.csv")
        points, succeeded, failed, baseline_count = fetch_category(name, CATEGORIES[name], tiles, out_path)

        if succeeded == 0 and baseline_count == 0:
            print(f"  ALL {len(tiles)} tiles failed for '{name}' and no previous data exists -- skipping write.")
            any_category_totally_empty = True
            continue

        write_csv(out_path, points)
        print(f"  -> {out_path} ({len(points)} points; "
              f"{succeeded}/{len(tiles)} tiles refreshed this run, {failed} kept previous data)")

    if any_category_totally_empty:
        print("One or more categories have never successfully fetched -- see log above.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
