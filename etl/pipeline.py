#!/usr/bin/env python3
"""
pipeline.py

Runs the full real pipeline end to end. This is what the monthly GitHub
Action calls. Requires network access (Overpass API); will not run in a
sandboxed/offline environment.

Usage:
    python3 etl/pipeline.py --res 5
"""
import argparse
import glob
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
from fetch_osm_pois import CATEGORIES  # noqa: E402


def run(cmd):
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def clean_stale_raw_files(raw_dir="data/raw"):
    """Remove any data/raw/*.geojson that no longer matches a known
    category (e.g. you renamed or deleted one in fetch_osm_pois.py)."""
    if not os.path.isdir(raw_dir):
        return
    valid = {f"{name}.geojson" for name in CATEGORIES} | {"casinos.geojson"}
    for path in glob.glob(os.path.join(raw_dir, "*.geojson")):
        if os.path.basename(path) not in valid:
            print(f"Removing stale raw file: {path}")
            os.remove(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--res", type=int, default=5)
    args = ap.parse_args()

    clean_stale_raw_files()
    run([sys.executable, "etl/fetch_osm_pois.py"])
    run([sys.executable, "etl/build_h3_grid.py", "--res", str(args.res)])
    run([sys.executable, "etl/compute_metrics.py"])
    print("Pipeline complete. data/hexes.geojson updated.")


if __name__ == "__main__":
    main()
