/* Raw Data Explorer -- a second, independent map showing every individual
 * location behind the core categories, as toggleable translucent point
 * layers. No filtering, no hex aggregation, no suitability logic; this is
 * the "just the dots" view, separate from the main blob map above it.
 */

// Same CONUS-only extent the main map and pipeline use.
const EXPLORER_BBOX = [-124.7, 24.4, -66.8, 49.5];

// Core OSM-derived categories: raw CSV is just "lon,lat" (see
// fetch_osm_pois.py / colab_state_fetch.py -- no names, no tags, ever
// collected for these). Colors are muted but kept distinct so overlaps
// are readable when several layers are on at once.
const EXPLORER_POINT_LAYERS = [
  { id: "bars", label: "Bars, Pubs & Taprooms", file: "data/raw/bars.csv", color: "#c2703d" },
  { id: "golf_courses", label: "Golf Courses (incl. Topgolf)", file: "data/raw/golf_courses.csv", color: "#4b5d34" },
  { id: "boat_ramps", label: "Boat Ramps & Marinas", file: "data/raw/boat_ramps.csv", color: "#2f7d8f" },
  { id: "hardware_stores", label: "Hardware / Home Improvement", file: "data/raw/hardware_stores.csv", color: "#8a4b32" },
  { id: "casinos", label: "Casino / Gambling", file: "data/raw/casinos.csv", color: "#8a3d6b" },
];

// Sports venues are hand-curated (etl/venues.py), so unlike the OSM
// categories above, team names are known and worth keeping -- this one
// file has 3 real data columns, not 2.
const VENUES_LAYER = { id: "sports", label: "Pro Sports Venues", file: "data/venues.csv", color: "#3d5a8a" };

const explorerMap = new maplibregl.Map({
  container: "explorer-map",
  style: "https://tiles.openfreemap.org/styles/positron",
  bounds: EXPLORER_BBOX,
  fitBoundsOptions: { padding: 10 },
  minZoom: 2.5,
  maxZoom: 12,
});
explorerMap.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

function recolorExplorerBasemap() {
  const layers = explorerMap.getStyle().layers || [];
  for (const layer of layers) {
    const id = layer.id.toLowerCase();
    try {
      if (id.includes("water") && layer.type === "fill") {
        explorerMap.setPaintProperty(layer.id, "fill-color", "#d7cf9d");
      } else if ((id.includes("water") || id.includes("waterway")) && layer.type === "line") {
        explorerMap.setPaintProperty(layer.id, "line-color", "#b7a96c");
      }
    } catch (e) { /* layer doesn't support this property -- skip */ }
  }
}

// Simple 2-column "lon,lat" CSV parser (no quoting/escaping needed --
// these files are just numbers).
async function loadPointCSV(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status}`);
  const text = await res.text();
  const lines = text.trim().split("\n").slice(1); // drop header
  const features = [];
  for (const line of lines) {
    if (!line.trim()) continue;
    const [lon, lat] = line.split(",").map(Number);
    if (Number.isFinite(lon) && Number.isFinite(lat)) {
      features.push({ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: [lon, lat] } });
    }
  }
  return { type: "FeatureCollection", features };
}

// Venues CSV has 4 columns: league,team,lon,lat.
async function loadVenuesCSV(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status}`);
  const text = await res.text();
  const lines = text.trim().split("\n").slice(1);
  const features = [];
  for (const line of lines) {
    if (!line.trim()) continue;
    const [league, team, lon, lat] = line.split(",");
    const lonN = Number(lon), latN = Number(lat);
    if (Number.isFinite(lonN) && Number.isFinite(latN)) {
      features.push({
        type: "Feature",
        properties: { league: league.toUpperCase(), team },
        geometry: { type: "Point", coordinates: [lonN, latN] },
      });
    }
  }
  return { type: "FeatureCollection", features };
}

function addPointLayer(layerDef, geojson) {
  explorerMap.addSource(layerDef.id, { type: "geojson", data: geojson });
  explorerMap.addLayer({
    id: `${layerDef.id}-circle`,
    type: "circle",
    source: layerDef.id,
    layout: { visibility: "none" },
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 3, 1.5, 8, 4, 12, 7],
      "circle-color": layerDef.color,
      "circle-opacity": 0.55,
      "circle-stroke-width": 0.5,
      "circle-stroke-color": layerDef.color,
      "circle-stroke-opacity": 0.9,
    },
  });
}

function buildLegend(allLayers, counts) {
  const legend = document.getElementById("explorer-legend");
  allLayers.forEach(layerDef => {
    const row = document.createElement("label");
    row.className = "explorer-legend-item";
    const count = counts[layerDef.id];
    const countText = count === undefined ? "\u2014" : count.toLocaleString();
    row.innerHTML = `
      <input type="checkbox" id="explorer-toggle-${layerDef.id}" />
      <span class="explorer-swatch" style="background:${layerDef.color}"></span>
      <span class="explorer-legend-name">${layerDef.label}</span>
      <span class="explorer-legend-count">${countText}</span>
    `;
    legend.appendChild(row);

    const checkbox = row.querySelector("input");
    checkbox.addEventListener("change", () => {
      const layerId = `${layerDef.id}-circle`;
      if (explorerMap.getLayer(layerId)) {
        explorerMap.setLayoutProperty(layerId, "visibility", checkbox.checked ? "visible" : "none");
      }
    });
  });
}

function showExplorerPopup(feature, layerLabel) {
  const panel = document.getElementById("explorer-popup");
  const p = feature.properties;
  const detail = p.team ? `<div>${p.team} (${p.league})</div>` : `<div>${layerLabel}</div>`;
  panel.innerHTML = `${detail}<div style="margin-top:4px;color:var(--ink-soft)">click elsewhere to dismiss</div>`;
  panel.hidden = false;
}

explorerMap.on("load", async () => {
  recolorExplorerBasemap();

  const allLayers = [...EXPLORER_POINT_LAYERS, VENUES_LAYER];
  const counts = {};

  // Fetch and add each layer independently -- one missing/not-yet-collected
  // file (e.g. casinos still backfilling four states) shouldn't stop the
  // rest of the explorer from working.
  await Promise.all(allLayers.map(async layerDef => {
    try {
      const geojson = layerDef.id === "sports"
        ? await loadVenuesCSV(layerDef.file)
        : await loadPointCSV(layerDef.file);
      addPointLayer(layerDef, geojson);
      counts[layerDef.id] = geojson.features.length;

      explorerMap.on("click", `${layerDef.id}-circle`, (e) => {
        if (e.features.length) showExplorerPopup(e.features[0], layerDef.label);
      });
      explorerMap.on("mouseenter", `${layerDef.id}-circle`, () => (explorerMap.getCanvas().style.cursor = "pointer"));
      explorerMap.on("mouseleave", `${layerDef.id}-circle`, () => (explorerMap.getCanvas().style.cursor = ""));
    } catch (e) {
      console.warn(`Raw Data Explorer: couldn't load ${layerDef.file} (${e.message}) -- that category's checkbox will do nothing until it's added.`);
    }
  }));

  buildLegend(allLayers, counts);
});

explorerMap.on("click", (e) => {
  const panel = document.getElementById("explorer-popup");
  const hit = explorerMap.queryRenderedFeatures(e.point);
  if (!hit.some(f => f.layer.id.endsWith("-circle"))) panel.hidden = true;
});
