#!/usr/bin/env python3
"""
build_h3_grid.py

Step 2 of the pipeline: generate the national H3 hex grid that every
metric gets aggregated onto. Separate from compute_metrics.py so you can
regenerate the grid (e.g. change resolution) without re-fetching POIs.

The grid boundary comes from a real US country boundary GeoJSON
(github.com/johan/world.geo.json), not a hand-drawn approximation. That
file is a MultiPolygon covering the mainland, Alaska, Hawaii, and various
small islands -- CONUS_ONLY below picks out just the mainland ring by
finding the highest-vertex-count part, which is reliably the mainland
(233 points vs. Alaska's 135 and everything else in single digits/teens).
If the fetch fails (no network -- e.g. running in a sandboxed shell),
this falls back to a much cruder hand-drawn outline so the script still
produces *something*, with a loud warning that it did so.

Usage:
    python3 etl/build_h3_grid.py --res 5 --out data/grid.json
"""
import argparse
import json
import sys
import urllib.error
import urllib.request

import h3

from us_states import assign_state, fetch_states, nearest_state

BOUNDARY_URL = "https://raw.githubusercontent.com/johan/world.geo.json/master/countries/USA.geo.json"

# Only used if the real boundary can't be fetched. Deliberately crude --
# straight-line segments that cut across the Great Lakes/Maine border and
# bulge into Canada. Good enough to keep the script running offline, not
# good enough to ship real data with.
FALLBACK_CONUS_OUTLINE = [
    (49.5, -124.8), (49.0, -95.0), (49.0, -83.0), (45.0, -67.0),
    (41.0, -71.5), (35.0, -75.5), (30.5, -81.5), (25.0, -80.2),
    (25.8, -97.2), (29.5, -103.0), (31.8, -106.5), (31.3, -111.0),
    (32.5, -117.1), (42.0, -124.4), (49.5, -124.8),
]


def fetch_conus_ring():
    """Returns [(lat, lng), ...] for the CONUS mainland only."""
    req = urllib.request.Request(BOUNDARY_URL, headers={"User-Agent": "brotosphere-etl/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    geom = data["features"][0]["geometry"]
    parts = geom["coordinates"]  # MultiPolygon: list of polygons, each a list of rings

    # The mainland is reliably the part with the most vertices -- Alaska,
    # Hawaii, and other islands all have far fewer points in this file.
    mainland = max(parts, key=lambda part: len(part[0]))
    outer_ring = mainland[0]  # [lng, lat] pairs
    return [(lat, lng) for lng, lat in outer_ring]


def build_grid(resolution, ring):
    cells = h3.polygon_to_cells(h3.LatLngPoly(ring), resolution)
    out = []
    for cell in cells:
        boundary = h3.cell_to_boundary(cell)  # [(lat, lng), ...]
        lat, lng = h3.cell_to_latlng(cell)
        poly_ring = [[lo, la] for la, lo in boundary]
        poly_ring.append(poly_ring[0])
        out.append({"h3": cell, "center": [lng, lat], "ring": poly_ring})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--res", type=int, default=5,
                     help="H3 resolution. 3 ~ 12,000 sq mi/cell (fast, coarse). "
                          "5 ~ 250 sq mi/cell (closer to county-level, recommended). "
                          "6 is metro-area detail but is a much bigger file.")
    ap.add_argument("--out", default="data/grid.json")
    args = ap.parse_args()

    try:
        ring = fetch_conus_ring()
        print("Using real CONUS boundary from world.geo.json")
    except (urllib.error.URLError, KeyError, IndexError) as e:
        print(f"WARNING: couldn't fetch real boundary ({e}) -- "
              f"falling back to the crude hand-drawn outline.", file=sys.stderr)
        ring = FALLBACK_CONUS_OUTLINE

    grid = build_grid(args.res, ring)

    try:
        states = fetch_states()
        for cell in grid:
            lng, lat = cell["center"]
            cell["state"] = assign_state(lng, lat, states)
        misses = [c for c in grid if c["state"] is None]
        for cell in misses:
            lng, lat = cell["center"]
            cell["state"] = nearest_state(lng, lat, states)
        print(f"Tagged each cell with its state ({len(misses)} needed the nearest-state "
              f"fallback -- expected along jagged coastlines like the Great Lakes, "
              f"where the country outline and state outlines disagree slightly).")
    except (urllib.error.URLError, KeyError, IndexError) as e:
        print(f"WARNING: couldn't fetch state boundaries ({e}) -- "
              f"cells will have no 'state' property, so state-based exclusion "
              f"won't work until this succeeds on a later run.", file=sys.stderr)
        for cell in grid:
            cell["state"] = None

    with open(args.out, "w") as f:
        json.dump(grid, f)
    print(f"Wrote {len(grid)} cells at resolution {args.res} to {args.out}")


if __name__ == "__main__":
    main()
