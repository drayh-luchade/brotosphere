"""
us_states.py

Shared helper for tagging each hex with the US state its center falls in.
Used by build_h3_grid.py. Boundary source is a lightweight, pre-simplified
public GeoJSON (~87KB for all 52 states/territories, ~30-300 vertices per
state) -- plenty precise for "which state is this ~10-mile-wide hex
mostly in," not meant for anything needing parcel-level accuracy.

No shapely/geopandas -- just a plain ray-casting point-in-polygon test in
pure Python, with a bounding-box pre-check per state so most hexes only
ever run the real test against the one state they're actually in.
"""
import json
import urllib.request

STATES_URL = "https://raw.githubusercontent.com/PublicaMundi/MappingAPI/master/data/geojson/us-states.json"

STATE_NAME_TO_ABBR = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI",
    "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Puerto Rico": "PR", "Rhode Island": "RI",
    "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX",
    "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
    "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
}

# The 48 contiguous states + DC -- what the site actually covers, in a
# form the frontend can hardcode for the exclusion checkboxes without
# needing to fetch or parse any boundary data client-side (state
# exclusion is just a property match against the abbreviation each hex
# was already tagged with at build time).
CONUS_STATE_ABBRS = sorted(
    abbr for name, abbr in STATE_NAME_TO_ABBR.items()
    if name not in ("Alaska", "Hawaii", "Puerto Rico")
)


def _point_in_ring(x, y, ring):
    n = len(ring)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-15) + xi):
            inside = not inside
        j = i
    return inside


def _point_in_polygon_with_holes(x, y, rings):
    """rings[0] is the exterior, rings[1:] are holes."""
    if not _point_in_ring(x, y, rings[0]):
        return False
    return not any(_point_in_ring(x, y, hole) for hole in rings[1:])


def _bbox_of_rings(rings):
    xs = [p[0] for ring in rings for p in ring]
    ys = [p[1] for ring in rings for p in ring]
    return min(xs), min(ys), max(xs), max(ys)


def fetch_states():
    """Returns a list of {abbr, name, parts, bbox} -- parts is a list of
    ring-sets (one per Polygon, or per part of a MultiPolygon), each
    ring-set being [exterior, hole1, hole2, ...] in [lon, lat] order."""
    req = urllib.request.Request(STATES_URL, headers={"User-Agent": "brotosphere-etl/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    states = []
    for ft in data["features"]:
        name = ft["properties"].get("name")
        abbr = STATE_NAME_TO_ABBR.get(name)
        if not abbr:
            continue
        geom = ft["geometry"]
        if geom["type"] == "Polygon":
            parts = [geom["coordinates"]]
        else:  # MultiPolygon
            parts = geom["coordinates"]

        all_rings = [ring for part in parts for ring in part]
        states.append({
            "abbr": abbr,
            "name": name,
            "parts": parts,
            "bbox": _bbox_of_rings(all_rings),
        })
    return states


def assign_state(lon, lat, states):
    """Returns the state abbreviation whose boundary contains (lon, lat),
    or None if it doesn't fall inside any of them (e.g. a coastal hex
    just outside a simplified boundary)."""
    for state in states:
        minx, miny, maxx, maxy = state["bbox"]
        if not (minx <= lon <= maxx and miny <= lat <= maxy):
            continue
        for rings in state["parts"]:
            if _point_in_polygon_with_holes(lon, lat, rings):
                return state["abbr"]
    return None


def nearest_state(lon, lat, states):
    """Fallback for hexes that miss every polygon test above. This
    happens more than you'd expect along the Great Lakes shoreline and a
    few other jagged coastlines -- the country outline (build_h3_grid's
    233-point mainland ring) and this module's independently-simplified
    state boundaries don't agree on exactly where the coast is, so a hex
    that's genuinely inside the country can fall in the gap between the
    two. Only called for that small slice of edge cases, so it's fine to
    do a real (if approximate) nearest-vertex search rather than the much
    cruder "closest bbox center" -- precision matters most exactly on
    these coastal/border cells."""
    best_abbr, best_dist = None, float("inf")
    for state in states:
        minx, miny, maxx, maxy = state["bbox"]
        # cheap reject: skip states nowhere near this point before doing
        # the real vertex scan
        pad = 2.0  # degrees -- generous, this is just a pre-filter
        if not (minx - pad <= lon <= maxx + pad and miny - pad <= lat <= maxy + pad):
            continue
        for rings in state["parts"]:
            for ring in rings:
                for vx, vy in ring:
                    d = (lon - vx) ** 2 + (lat - vy) ** 2
                    if d < best_dist:
                        best_dist, best_abbr = d, state["abbr"]
    return best_abbr
