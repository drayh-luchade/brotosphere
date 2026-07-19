#!/usr/bin/env python3
"""
generate_sample_data.py

Produces SYNTHETIC demo data so the site has something to render out of the
box. This is a stand-in for the real pipeline (fetch_osm_pois.py ->
build_h3_grid.py -> compute_metrics.py). Nothing in here is real GIS data --
counts are randomly generated with a mild boost near a list of major metro
areas, just so the demo map doesn't look uniformly flat.

Run:
    python3 etl/generate_sample_data.py

Output:
    data/hexes.geojson
"""
import json
import math
import random

import h3

random.seed(42)

RESOLUTION = 3  # ~12,000 sq mi per cell -> ~600 cells for CONUS. Coarse
                # on purpose for a fast, lightweight V1 demo. The real
                # pipeline can run at res 5-6 for neighborhood-level detail.

# Rough CONUS bounding polygon (lat, lng) -- intentionally loose.
CONUS_OUTLINE = [
    (49.5, -124.8), (49.0, -95.0), (49.0, -83.0), (45.0, -67.0),
    (41.0, -71.5), (35.0, -75.5), (30.5, -81.5), (25.0, -80.2),
    (25.8, -97.2), (29.5, -103.0), (31.8, -106.5), (31.3, -111.0),
    (32.5, -117.1), (42.0, -124.4), (49.5, -124.8),
]

# A handful of metro centers used only to bias the fake counts so the demo
# map has some visual variation. Replace with real POI density in prod.
METROS = [
    (40.71, -74.01), (34.05, -118.24), (41.88, -87.63), (29.76, -95.37),
    (33.45, -112.07), (39.95, -75.16), (29.42, -98.49), (32.78, -96.80),
    (37.77, -122.42), (30.27, -97.74), (39.10, -84.51), (39.96, -82.99),
    (35.23, -80.84), (37.34, -121.89), (47.61, -122.33), (39.74, -104.99),
    (42.36, -71.06), (36.17, -115.14), (35.15, -90.05), (38.63, -90.20),
    (45.51, -122.68), (25.76, -80.19), (44.98, -93.27), (36.85, -76.29),
    (39.29, -76.61), (43.04, -87.91), (35.47, -97.52), (41.25, -95.94),
    (36.06, -79.79), (35.79, -78.64), (37.55, -77.46), (38.90, -77.04),
]


def great_circle_miles(lat1, lon1, lat2, lon2):
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def metro_boost(lat, lng):
    """0..1 boost factor, higher near a metro center."""
    nearest = min(great_circle_miles(lat, lng, mlat, mlng) for mlat, mlng in METROS)
    return max(0.0, 1.0 - nearest / 120.0)


def fake_count(lat, lng, base_lo, base_hi, boost_mult=3.0):
    boost = metro_boost(lat, lng)
    lo, hi = base_lo, base_hi + int(boost * boost_mult * base_hi)
    return random.randint(lo, max(lo, hi))


def fake_distance(lat, lng, near_lo=1, near_hi=40, far_lo=20, far_hi=180):
    """Distance-to-nearest style metric: shorter near metros."""
    boost = metro_boost(lat, lng)
    lo = near_lo + (1 - boost) * (far_lo - near_lo)
    hi = near_hi + (1 - boost) * (far_hi - near_hi)
    return round(random.uniform(lo, max(lo + 1, hi)), 1)


def build_features():
    cells = h3.polygon_to_cells(h3.LatLngPoly(CONUS_OUTLINE), RESOLUTION)
    features = []
    for cell in cells:
        lat, lng = h3.cell_to_latlng(cell)
        boundary = h3.cell_to_boundary(cell)  # list of (lat, lng)
        ring = [[lng, lat] for lat, lng in boundary]
        ring.append(ring[0])

        metrics = {
            "bars": fake_count(lat, lng, 0, 45),
            "breweries": fake_count(lat, lng, 0, 12),
            "golf_courses": fake_count(lat, lng, 0, 9),
            "boat_ramps": fake_count(lat, lng, 0, 14),
            "fishing_access": fake_count(lat, lng, 0, 20),
            "hardware_stores": fake_count(lat, lng, 0, 10),
            "campgrounds": fake_count(lat, lng, 0, 11),
            "bowling_pool_clubs": fake_count(lat, lng, 0, 8),
            "nfl_miles": fake_distance(lat, lng, 3, 60, 40, 400),
            "nba_miles": fake_distance(lat, lng, 3, 60, 40, 400),
            "mlb_miles": fake_distance(lat, lng, 3, 60, 40, 400),
            "nhl_miles": fake_distance(lat, lng, 3, 60, 40, 400),
            "casino_miles": fake_distance(lat, lng, 2, 40, 15, 250),
        }

        features.append({
            "type": "Feature",
            "properties": {"h3": cell, **metrics},
            "geometry": {"type": "Polygon", "coordinates": [ring]},
        })
    return features


def main():
    features = build_features()
    fc = {"type": "FeatureCollection", "features": features}
    out_path = "data/hexes.geojson"
    with open(out_path, "w") as f:
        json.dump(fc, f)
    print(f"Wrote {len(features)} hexes to {out_path}")


if __name__ == "__main__":
    main()
