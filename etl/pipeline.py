#!/usr/bin/env python3
"""
pipeline.py

Runs the full real pipeline end to end. Requires network access (Overpass
API); will not run in a sandboxed/offline environment.

The GitHub Action calls the three steps individually rather than this
file, so it can commit data/raw/ progress between steps -- see
.github/workflows/build-data.yml. Use this for running the whole thing
locally in one shot.

Usage:
    python3 etl/pipeline.py --res 5
"""
import argparse
import subprocess
import sys


def run(cmd):
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--res", type=int, default=5)
    args = ap.parse_args()

    run([sys.executable, "etl/fetch_osm_pois.py"])
    run([sys.executable, "etl/build_h3_grid.py", "--res", str(args.res)])
    run([sys.executable, "etl/compute_metrics.py"])
    print("Pipeline complete. data/hexes.geojson updated.")


if __name__ == "__main__":
    main()
