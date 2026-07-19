#!/usr/bin/env python3
"""
build_h3_grid.py

Step 2 of the pipeline: generate the national H3 hex grid that every
metric gets aggregated onto. Separate from compute_metrics.py so you can
regenerate the grid (e.g. change resolution) without re-fetching POIs.

Usage:
    python3 etl/build_h3_grid.py --res 5 --out data/grid.json
"""
import argparse
import json

import h3

# Loose CONUS outline (lat, lng). Swap in a real state/country boundary
# file if you want a tighter fit -- this is intentionally approximate.
CONUS_OUTLINE = [
    (49.5, -124.8), (49.0, -95.0), (49.0, -83.0), (45.0, -67.0),
    (41.0, -71.5), (35.0, -75.5), (30.5, -81.5), (25.0, -80.2),
    (25.8, -97.2), (29.5, -103.0), (31.8, -106.5), (31.3, -111.0),
    (32.5, -117.1), (42.0, -124.4), (49.5, -124.8),
]


def build_grid(resolution):
    cells = h3.polygon_to_cells(h3.LatLngPoly(CONUS_OUTLINE), resolution)
    out = []
    for cell in cells:
        boundary = h3.cell_to_boundary(cell)  # [(lat, lng), ...]
        lat, lng = h3.cell_to_latlng(cell)
        ring = [[lo, la] for la, lo in boundary]
        ring.append(ring[0])
        out.append({"h3": cell, "center": [lng, lat], "ring": ring})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--res", type=int, default=5,
                     help="H3 resolution. 3 ~ 12,000 sq mi/cell (fast, coarse). "
                          "5 ~ 250 sq mi/cell (closer to county-level, recommended). "
                          "6 is metro-area detail but is a much bigger file.")
    ap.add_argument("--out", default="data/grid.json")
    args = ap.parse_args()

    grid = build_grid(args.res)
    with open(args.out, "w") as f:
        json.dump(grid, f)
    print(f"Wrote {len(grid)} cells at resolution {args.res} to {args.out}")


if __name__ == "__main__":
    main()
