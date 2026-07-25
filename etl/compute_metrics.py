#!/usr/bin/env python3
"""
compute_metrics.py

Step 3 of the pipeline: aggregate raw POI points (from fetch_osm_pois.py)
and curated venue lists (venues.py) onto the hex grid (build_h3_grid.py),
and write the final data/hexes.geojson that the site loads.

Counts: number of POIs whose h3 cell (at the grid's resolution) matches
the hex. This is a point-in-hex count, not a "within N miles" radius --
see the README for why V1 works this way and what a radius-based version
would require.

Distances: for sports/casinos, the great-circle distance from the hex
center to the nearest venue.

Usage:
    python3 etl/compute_metrics.py --grid data/grid.json --raw data/raw --out data/hexes.geojson
"""
import argparse
import csv
import json
import math
import os

import h3

from venues import VENUES

POINT_CATEGORIES = [
    "bars", "breweries", "golf_courses", "boat_ramps", "fishing_access",
    "hardware_stores", "campgrounds", "bowling_pool_clubs",
]


def haversine_miles(lat1, lon1, lat2, lon2):
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def load_raw(raw_dir, name):
    """Raw POI files are compact CSV: a header row, then one 'lon,lat' row
    per point. Returns a list of (lon, lat) float tuples."""
    path = os.path.join(raw_dir, f"{name}.csv")
    if not os.path.exists(path):
        print(f"  (missing {path}, treating {name} as all-zero)")
        return []
    points = []
    with open(path, newline="") as f:
        reader = csv.reader(f)
        next(reader, None)  # header
        for row in reader:
            if len(row) == 2:
                points.append((float(row[0]), float(row[1])))
    return points


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", default="data/grid.json")
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--out", default="data/hexes.geojson")
    args = ap.parse_args()

    with open(args.grid) as f:
        grid = json.load(f)
    resolution = h3.get_resolution(grid[0]["h3"])

    counts = {cell["h3"]: {cat: 0 for cat in POINT_CATEGORIES} for cell in grid}

    for cat in POINT_CATEGORIES:
        points = load_raw(args.raw, cat)
        for lon, lat in points:
            cell = h3.latlng_to_cell(lat, lon, resolution)
            if cell in counts:
                counts[cell][cat] += 1

    casino_points = load_raw(args.raw, "casinos")  # list of (lon, lat)

    out_features = []
    for cell in grid:
        h3id = cell["h3"]
        clat, clng = cell["center"][1], cell["center"][0]

        props = {"h3": h3id, "h3_res": resolution, "state": cell.get("state"), **counts[h3id]}

        for league, venues in VENUES.items():
            if venues:
                dist = min(haversine_miles(clat, clng, vlat, vlon) for _, vlat, vlon in venues)
            else:
                dist = None
            props[f"{league}_miles"] = round(dist, 1) if dist is not None else None

        if casino_points:
            props["casino_miles"] = round(
                min(haversine_miles(clat, clng, plat, plon) for plon, plat in casino_points), 1
            )
        else:
            props["casino_miles"] = None

        out_features.append({
            "type": "Feature",
            "properties": props,
            "geometry": {"type": "Polygon", "coordinates": [cell["ring"]]},
        })

    fc = {"type": "FeatureCollection", "features": out_features}
    with open(args.out, "w") as f:
        json.dump(fc, f)
    print(f"Wrote {len(out_features)} cells to {args.out}")


if __name__ == "__main__":
    main()
