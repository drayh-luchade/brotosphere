/* Brotosphere V1 — client-side filtering over a precomputed H3 grid.
 * No backend, no AI, no score. Every hex either satisfies every enabled
 * criterion (green) or it doesn't (gray). Excluded zones override both.
 */

const DATA_URL = "data/hexes.geojson";
const SOURCE_ID = "hexes";
const FILL_LAYER = "hexes-fill";
const LINE_LAYER = "hexes-line";

// ---- filter catalog -------------------------------------------------
// type "min": pass when feature[prop] >= value
// type "max": pass when feature[prop] <= value
const FILTERS = [
  { id: "bars", label: "Bars, Pubs & Taprooms", icon: "\u{1F37A}", prop: "bars", type: "min", min: 1, max: 40, step: 1, default: 6, unit: "" },
  { id: "breweries", label: "Breweries & Distilleries", icon: "\u{1F943}", prop: "breweries", type: "min", min: 1, max: 15, step: 1, default: 2, unit: "" },
  { id: "golf", label: "Golf Courses", icon: "\u26F3", prop: "golf_courses", type: "min", min: 1, max: 10, step: 1, default: 2, unit: "" },
  { id: "boating", label: "Boat Ramps & Marinas", icon: "\u{1F6A4}", prop: "boat_ramps", type: "min", min: 1, max: 12, step: 1, default: 2, unit: "" },
  { id: "fishing", label: "Fishing Access", icon: "\u{1F3A3}", prop: "fishing_access", type: "min", min: 1, max: 20, step: 1, default: 3, unit: "" },
  { id: "hardware", label: "Hardware / Home Improvement", icon: "\u{1F6E0}", prop: "hardware_stores", type: "min", min: 1, max: 10, step: 1, default: 2, unit: "" },
  { id: "camping", label: "Campgrounds & Public Land", icon: "\u{1F3D5}", prop: "campgrounds", type: "min", min: 1, max: 12, step: 1, default: 2, unit: "" },
  { id: "bargames", label: "Bar Games (bowling, pool, fraternal clubs)", icon: "\u{1F3B3}", prop: "bowling_pool_clubs", type: "min", min: 1, max: 10, step: 1, default: 2, unit: "" },
  { id: "sports", label: "Pro Sports (any major league)", icon: "\u{1F3C8}", prop: "sports_min_miles", type: "max", min: 10, max: 400, step: 5, default: 100, unit: " mi" },
  { id: "gambling", label: "Casino / Gambling", icon: "\u{1F3B0}", prop: "casino_miles", type: "max", min: 10, max: 250, step: 5, default: 75, unit: " mi" },
];

const METRIC_DISPLAY = [
  { prop: "bars", label: "Bars" },
  { prop: "breweries", label: "Breweries" },
  { prop: "golf_courses", label: "Golf courses" },
  { prop: "boat_ramps", label: "Boat ramps" },
  { prop: "fishing_access", label: "Fishing access" },
  { prop: "hardware_stores", label: "Hardware stores" },
  { prop: "campgrounds", label: "Campgrounds" },
  { prop: "bowling_pool_clubs", label: "Bar games" },
  { prop: "nfl_miles", label: "Nearest NFL", suffix: " mi" },
  { prop: "nba_miles", label: "Nearest NBA", suffix: " mi" },
  { prop: "mlb_miles", label: "Nearest MLB", suffix: " mi" },
  { prop: "nhl_miles", label: "Nearest NHL", suffix: " mi" },
  { prop: "casino_miles", label: "Nearest casino", suffix: " mi" },
];

const state = {
  enabled: {},          // filterId -> bool
  values: {},           // filterId -> number
  exclusion: { enabled: false, lat: null, lng: null, radiusMi: 30 },
};
FILTERS.forEach(f => { state.enabled[f.id] = false; state.values[f.id] = f.default; });

// ---- geometry helper --------------------------------------------------
function milesBetween(lat1, lon1, lat2, lon2) {
  const R = 3958.8;
  const toRad = d => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

// ---- build sidebar UI --------------------------------------------------
function buildFilterUI() {
  const container = document.getElementById("filters");
  FILTERS.forEach(f => {
    const item = document.createElement("div");
    item.className = "filter-item";
    item.id = `filter-${f.id}`;

    const head = document.createElement("label");
    head.className = "filter-head";
    head.innerHTML = `
      <input type="checkbox" id="chk-${f.id}" />
      <span class="filter-icon">${f.icon}</span>
      <span class="filter-name">${f.label}</span>
    `;

    const body = document.createElement("div");
    body.className = "filter-body";
    const verb = f.type === "min" ? "At least" : "Within";
    body.innerHTML = `
      <div class="field-row">
        <label for="rng-${f.id}">${verb}</label>
        <input type="range" id="rng-${f.id}" min="${f.min}" max="${f.max}" step="${f.step}" value="${f.default}" />
        <output id="out-${f.id}"></output>
      </div>
    `;

    item.appendChild(head);
    item.appendChild(body);
    container.appendChild(item);

    const chk = head.querySelector(`#chk-${f.id}`);
    const rng = body.querySelector(`#rng-${f.id}`);
    const out = body.querySelector(`#out-${f.id}`);

    const renderOut = () => {
      const v = state.values[f.id];
      out.textContent = f.type === "min" ? `${v}${f.unit}` : `${v}${f.unit}`;
    };
    renderOut();

    chk.addEventListener("change", () => {
      state.enabled[f.id] = chk.checked;
      item.classList.toggle("enabled", chk.checked);
      applyFilters();
    });

    rng.addEventListener("input", () => {
      state.values[f.id] = Number(rng.value);
      renderOut();
      applyFilters();
    });
  });
}

// ---- map setup -----------------------------------------------------
// Average H3 cell area by resolution, converted to sq mi -- used only to
// label the corner plate. (H3's own docs give these in km^2; res 5 is the
// pipeline's current default.)
const H3_AVG_AREA_SQ_MI = { 2: 33500, 3: 4784, 4: 683, 5: 97.6, 6: 13.9, 7: 1.99, 8: 0.285 };

function setResolutionLabel(res) {
  const el = document.getElementById("plate-scale-readout");
  if (res === undefined || res === null) {
    el.textContent = "H3 RES. \u2014";
    return;
  }
  const area = H3_AVG_AREA_SQ_MI[res];
  el.textContent = area
    ? `H3 RES. ${res} \u00b7 ~${area.toLocaleString()} SQ MI/CELL`
    : `H3 RES. ${res}`;
}

const map = new maplibregl.Map({
  container: "map",
  style: "https://tiles.openfreemap.org/styles/positron",
  center: [-96, 39],
  zoom: 3.6,
  minZoom: 2.5,
  maxZoom: 10,
});

map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

// The stock "positron" basemap uses light blue water and blue-tinted road
// casings. Recolor anything blue-leaning to sit inside our warm palette
// instead. Matches on layer id/type rather than a hardcoded list, so it
// keeps working if OpenFreeMap tweaks their style layers.
function recolorBasemap() {
  const layers = map.getStyle().layers || [];
  for (const layer of layers) {
    const id = layer.id.toLowerCase();
    try {
      if (id.includes("water") && layer.type === "fill") {
        map.setPaintProperty(layer.id, "fill-color", "#d7cf9d");
      } else if (id.includes("water") && layer.type === "line") {
        map.setPaintProperty(layer.id, "line-color", "#b7a96c");
      } else if (id.includes("waterway") && layer.type === "line") {
        map.setPaintProperty(layer.id, "line-color", "#b7a96c");
      }
    } catch (e) {
      // Layer doesn't support this paint property — skip it.
    }
  }
}

let dataLoaded = false;

map.on("load", async () => {
  recolorBasemap();

  const res = await fetch(DATA_URL);
  const geojson = await res.json();

  // derive a combined "nearest pro sports" field client-side
  geojson.features.forEach(ft => {
    const p = ft.properties;
    p.sports_min_miles = Math.min(p.nfl_miles, p.nba_miles, p.mlb_miles, p.nhl_miles);
  });

  document.getElementById("cell-count-readout").textContent = `${geojson.features.length} CELLS`;
  setResolutionLabel(geojson.features[0]?.properties?.h3_res);

  map.addSource(SOURCE_ID, {
    type: "geojson",
    data: geojson,
    promoteId: "h3",
  });

  map.addLayer({
    id: FILL_LAYER,
    type: "fill",
    source: SOURCE_ID,
    paint: {
      "fill-color": [
        "case",
        ["boolean", ["feature-state", "excluded"], false], "rgba(138,75,50,0.35)",
        ["boolean", ["feature-state", "pass"], false], "rgba(75,93,52,0.55)",
        "rgba(150,138,104,0.28)",
      ],
      "fill-opacity": 0.85,
    },
  });

  map.addLayer({
    id: LINE_LAYER,
    type: "line",
    source: SOURCE_ID,
    paint: {
      "line-color": [
        "case",
        ["boolean", ["feature-state", "excluded"], false], "#8a4b32",
        ["boolean", ["feature-state", "pass"], false], "#4b5d34",
        "#8f7f57",
      ],
      "line-width": 0.6,
    },
  });

  dataLoaded = true;
  applyFilters();

  map.on("click", FILL_LAYER, (e) => {
    if (!e.features.length) return;
    showPopup(e.features[0]);
  });
  map.on("mouseenter", FILL_LAYER, () => (map.getCanvas().style.cursor = "pointer"));
  map.on("mouseleave", FILL_LAYER, () => (map.getCanvas().style.cursor = ""));
});

function applyFilters() {
  if (!dataLoaded) return;
  const src = map.getSource(SOURCE_ID);
  const geojson = src._data || src.serialize().data;
  const features = geojson.features;

  const activeFilters = FILTERS.filter(f => state.enabled[f.id]);

  features.forEach(ft => {
    const id = ft.properties.h3;
    let pass = true;
    for (const f of activeFilters) {
      const val = ft.properties[f.prop];
      const target = state.values[f.id];
      if (f.type === "min" && val < target) { pass = false; break; }
      if (f.type === "max" && val > target) { pass = false; break; }
    }

    let excluded = false;
    if (state.exclusion.enabled && state.exclusion.lat != null) {
      const [lng, lat] = centroidOf(ft);
      const d = milesBetween(lat, lng, state.exclusion.lat, state.exclusion.lng);
      excluded = d <= state.exclusion.radiusMi;
    }

    map.setFeatureState({ source: SOURCE_ID, id }, { pass, excluded });
  });
}

function centroidOf(feature) {
  const ring = feature.geometry.coordinates[0];
  let x = 0, y = 0;
  for (const [lng, lat] of ring) { x += lng; y += lat; }
  return [x / ring.length, y / ring.length];
}

// ---- popup -----------------------------------------------------------
function showPopup(feature) {
  const p = feature.properties;
  const panel = document.getElementById("hex-popup");
  const rows = METRIC_DISPLAY.map(m => {
    const v = p[m.prop];
    const display = m.suffix ? `${v}${m.suffix}` : v;
    return `<div class="hex-popup-row"><span>${m.label}</span><span class="v">${display}</span></div>`;
  }).join("");

  panel.innerHTML = `
    <div class="hex-popup-head">
      <span>CELL ${p.h3}</span>
      <button class="hex-popup-close" id="hex-popup-close" aria-label="Close">&times;</button>
    </div>
    <div class="hex-popup-body">${rows}</div>
  `;
  panel.hidden = false;
  document.getElementById("hex-popup-close").addEventListener("click", () => {
    panel.hidden = true;
  });
}

// ---- exclusion zone controls ------------------------------------------
const exclChk = document.getElementById("excl-address-enabled");
const exclRow = exclChk.closest(".exclusion-row");
const exclInput = document.getElementById("excl-address-input");
const exclGo = document.getElementById("excl-address-go");
const exclRadius = document.getElementById("excl-address-radius");
const exclRadiusOut = document.getElementById("excl-address-radius-out");
const geocodeStatus = document.getElementById("geocode-status");

exclRadiusOut.textContent = `${exclRadius.value} mi`;

exclChk.addEventListener("change", () => {
  state.exclusion.enabled = exclChk.checked;
  exclRow.classList.toggle("enabled", exclChk.checked);
  if (!exclChk.checked) {
    state.exclusion.lat = null;
    geocodeStatus.textContent = "";
  }
  applyFilters();
});

exclRadius.addEventListener("input", () => {
  state.exclusion.radiusMi = Number(exclRadius.value);
  exclRadiusOut.textContent = `${exclRadius.value} mi`;
  applyFilters();
});

exclGo.addEventListener("click", async () => {
  const q = exclInput.value.trim();
  if (!q) return;
  geocodeStatus.textContent = "Locating\u2026";
  try {
    // Uses OpenStreetMap Nominatim, a free public geocoder. For anything
    // beyond light demo traffic, self-host or use a commercial geocoder —
    // see Nominatim's usage policy before scaling this up.
    const url = `https://nominatim.openstreetmap.org/search?format=json&limit=1&q=${encodeURIComponent(q)}`;
    const res = await fetch(url);
    const results = await res.json();
    if (!results.length) {
      geocodeStatus.textContent = "Couldn't find that place. Try a more specific address.";
      return;
    }
    state.exclusion.lat = parseFloat(results[0].lat);
    state.exclusion.lng = parseFloat(results[0].lon);
    geocodeStatus.textContent = `Excluding ${state.exclusion.radiusMi} mi around: ${results[0].display_name.split(",").slice(0, 3).join(",")}`;
    applyFilters();
  } catch (err) {
    geocodeStatus.textContent = "Geocoding failed. Check your connection and try again.";
  }
});

// ---- reset -------------------------------------------------------------
document.getElementById("reset-btn").addEventListener("click", () => {
  FILTERS.forEach(f => {
    state.enabled[f.id] = false;
    state.values[f.id] = f.default;
    document.getElementById(`chk-${f.id}`).checked = false;
    document.getElementById(`rng-${f.id}`).value = f.default;
    document.getElementById(`filter-${f.id}`).classList.remove("enabled");
    document.getElementById(`out-${f.id}`).textContent = `${f.default}${f.unit}`;
  });
  exclChk.checked = false;
  exclRow.classList.remove("enabled");
  state.exclusion = { enabled: false, lat: null, lng: null, radiusMi: 30 };
  exclInput.value = "";
  geocodeStatus.textContent = "";
  applyFilters();
});

// ---- sidebar toggle (mobile) --------------------------------------------
document.getElementById("sidebar-toggle").addEventListener("click", () => {
  document.getElementById("sidebar").classList.toggle("open");
});

// ---- about overlay -------------------------------------------------------
const aboutOverlay = document.getElementById("about-overlay");
document.getElementById("about-toggle").addEventListener("click", () => (aboutOverlay.hidden = false));
document.getElementById("about-close").addEventListener("click", () => (aboutOverlay.hidden = true));
document.getElementById("about-close-2").addEventListener("click", () => (aboutOverlay.hidden = true));
aboutOverlay.addEventListener("click", (e) => { if (e.target === aboutOverlay) aboutOverlay.hidden = true; });

buildFilterUI();
