# ETL pipeline

Three steps, run in order, produce `data/hexes.geojson`:

```
etl/fetch_osm_pois.py   raw POIs (bars, golf courses, etc.) -> data/raw/*.geojson
etl/build_h3_grid.py    national H3 hex grid                -> data/grid.json
etl/compute_metrics.py  aggregate POIs + venues onto grid    -> data/hexes.geojson
```

`etl/pipeline.py` runs all three. `etl/venues.py` is a hand-curated list of
major-league sports venues, already filled in for all 124 NFL/NBA/MLB/NHL
teams — worth a periodic re-check since teams relocate and venues change
(see the note at the top of the file).

## Running it yourself

None of this runs inside a network-sandboxed environment — `fetch_osm_pois.py`
needs to reach the public Overpass API. Run it locally or let the GitHub
Action (`.github/workflows/build-data.yml`) do it monthly.

```bash
pip install h3
python3 etl/pipeline.py --res 5
```

`--res` is the H3 resolution. The shipped demo data uses resolution 3
(~12,000 sq mi/cell — coarse, fast, good for a first look at the whole
country). Resolution 5 (~250 sq mi/cell, roughly county-sized) is a better
default for real use; 6 gets you metro-area detail but produces a much
larger GeoJSON file. If the file grows past a few MB, look at converting
to [PMTiles](https://protomaps.com/docs/pmtiles) instead of raw GeoJSON.

## Why counts are per-hex, not per-radius

The site's sliders say things like "at least 6 bars." Right now that count
is *the number of bars OSM has tagged inside that specific hex* — not
"within N miles," even though the original spec called for an adjustable
radius per category. A true radius search means storing every POI's raw
coordinates (or a spatial index) and re-running a distance query every
time a slider moves, which is a much heavier client — probably a
vector-tile POI layer plus a WASM spatial index, rather than "look up a
number on a precomputed hex."

For V1, a hex is standing in for "the area around here," and making the
hex resolution finer (bump `--res`) is the cheap way to approximate a
tighter radius. True per-category adjustable radius is a real V1.1
project, not a small tweak.

## Extending

- **New category**: add tag filters to `CATEGORIES` in `fetch_osm_pois.py`,
  add the name to `POINT_CATEGORIES` in `compute_metrics.py`, add a matching
  entry to `FILTERS` in `js/app.js`.
- **State/county/polygon exclusion**: needs a boundary source (Census
  TIGER/Line shapefiles are the standard free option) joined against the
  hex grid at build time, plus a `state`/`county` property added to each
  hex feature so the frontend can filter on it.
- **Distance-to-nearest for a new point category** (like sports/casinos):
  follow the pattern in `compute_metrics.py` for casinos — load raw points,
  take the min haversine distance to each hex center.
