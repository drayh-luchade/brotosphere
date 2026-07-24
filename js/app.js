/* Brotosphere V1.1 — client-side filtering over a precomputed H3 grid,
 * rendered as smoothed "blobs" (turf.dissolve + turf.polygonSmooth)
 * instead of individual hex outlines. No backend, no AI, no score.
 *
 * Every category field is a plain number input: blank = not applied,
 * a number = applied. A hex passes if it satisfies every filled-in
 * field. Excluded zones override everything, drawn on top.
 */

const DATA_URL = "data/hexes.geojson";
const SOURCE_ID = "hexes";          // invisible source, used only for click hit-testing
const HIT_LAYER = "hexes-hit";
const BLOB_BASE_SRC = "blob-base";  // the whole grid, dissolved once at load -- "the country"
const BLOB_PASS_SRC = "blob-pass";  // recomputed on every filter change
const BLOB_EXCL_SRC = "blob-excl";  // recomputed on every exclusion change

// Above this many features, skip smoothing (keep dissolve -- still no
// internal lines, just a jagged outer edge). Above the higher threshold,
// skip dissolving too and fall back to the raw hex layer for that status,
// so a very loose filter can't hang the browser trying to blob 20k+ cells.
const SMOOTH_MAX_FEATURES = 6000;
const DISSOLVE_MAX_FEATURES = 20000;
const BLOB_DEBOUNCE_MS = 350;

const JOKE_NUMBERS = [420, 69, 67];

// ---- filter catalog -------------------------------------------------
// type "min": pass when feature[prop] >= value
// type "max": pass when feature[prop] <= value
const FILTERS = [
  { id: "bars", label: "Bars, Pubs & Taprooms", icon: "\u{1F37A}", prop: "bars", type: "min", unit: "", placeholder: "6" },
  { id: "golf", label: "Golf Courses (incl. Topgolf)", icon: "\u26F3", prop: "golf_courses", type: "min", unit: "", placeholder: "2" },
  { id: "boating", label: "Boat Ramps & Marinas", icon: "\u{1F6A4}", prop: "boat_ramps", type: "min", unit: "", placeholder: "2" },
  { id: "hardware", label: "Hardware / Home Improvement", icon: "\u{1F6E0}", prop: "hardware_stores", type: "min", unit: "", placeholder: "2" },
  { id: "gambling", label: "Casino / Gambling", icon: "\u{1F3B0}", prop: "casino_miles", type: "max", unit: " mi", placeholder: "75" },
];

const SPORTS_LEAGUES = [
  { id: "nfl", label: "NFL", prop: "nfl_miles", type: "max", unit: " mi", placeholder: "50" },
  { id: "nba", label: "NBA", prop: "nba_miles", type: "max", unit: " mi", placeholder: "50" },
  { id: "mlb", label: "MLB", prop: "mlb_miles", type: "max", unit: " mi", placeholder: "50" },
  { id: "nhl", label: "NHL", prop: "nhl_miles", type: "max", unit: " mi", placeholder: "50" },
];

const ALL_FIELDS = [...FILTERS, ...SPORTS_LEAGUES];

const METRIC_DISPLAY = [
  { prop: "bars", label: "Bars" },
  { prop: "golf_courses", label: "Golf courses" },
  { prop: "boat_ramps", label: "Boat ramps" },
  { prop: "hardware_stores", label: "Hardware stores" },
  { prop: "nfl_miles", label: "Nearest NFL", suffix: " mi" },
  { prop: "nba_miles", label: "Nearest NBA", suffix: " mi" },
  { prop: "mlb_miles", label: "Nearest MLB", suffix: " mi" },
  { prop: "nhl_miles", label: "Nearest NHL", suffix: " mi" },
  { prop: "casino_miles", label: "Nearest casino", suffix: " mi" },
];

const state = {
  values: {},   // fieldId -> number | null  (null = field is blank / not applied)
  exclusion: { enabled: false, lat: null, lng: null, radiusMi: 30 },
};
ALL_FIELDS.forEach(f => { state.values[f.id] = null; });

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

// ---- easter egg --------------------------------------------------------
// Type the exact same joke number into every single field (all 9 main
// criteria plus all 4 leagues -- 13 fields total) and the map gives up
// on being a map.
function checkEasterEgg() {
  const vals = ALL_FIELDS.map(f => state.values[f.id]);
  if (vals.some(v => v === null)) return null;
  const first = vals[0];
  if (!vals.every(v => v === first)) return null;
  return JOKE_NUMBERS.includes(first) ? first : null;
}

// ---- build sidebar UI --------------------------------------------------
function buildFilterUI() {
  const container = document.getElementById("filters");

  FILTERS.forEach(f => {
    const item = document.createElement("div");
    item.className = "filter-item";
    item.id = `filter-${f.id}`;

    const verb = f.type === "min" ? "at least" : "within";
    item.innerHTML = `
      <div class="filter-row">
        <span class="filter-icon">${f.icon}</span>
        <span class="filter-name">${f.label}</span>
        <span class="filter-verb">${verb}</span>
        <input type="number" min="0" step="1" class="filter-num" id="num-${f.id}" placeholder="${f.placeholder}" />
        <span class="filter-unit">${f.unit}</span>
      </div>
    `;
    container.appendChild(item);

    const input = item.querySelector(`#num-${f.id}`);
    input.addEventListener("input", () => {
      const raw = input.value.trim();
      state.values[f.id] = raw === "" ? null : Number(raw);
      item.classList.toggle("active", raw !== "");
      onFiltersChanged();
    });
  });

  // Pro Sports: a group header (no field of its own) with four nested
  // per-league distance rows underneath.
  const sportsGroup = document.createElement("div");
  sportsGroup.className = "sports-group";
  sportsGroup.innerHTML = `
    <div class="sports-group-title">
      <span class="filter-icon">\u{1F3C8}</span>
      <span>Pro Sports \u2014 pick any leagues you want nearby</span>
    </div>
    <div class="sports-sub-list" id="sports-sub-list"></div>
  `;
  container.appendChild(sportsGroup);

  const subList = sportsGroup.querySelector("#sports-sub-list");
  SPORTS_LEAGUES.forEach(f => {
    const row = document.createElement("div");
    row.className = "sports-sub-row";
    row.id = `filter-${f.id}`;
    row.innerHTML = `
      <span class="filter-name">${f.label}</span>
      <span class="filter-verb">within</span>
      <input type="number" min="0" step="1" class="filter-num" id="num-${f.id}" placeholder="${f.placeholder}" />
      <span class="filter-unit">${f.unit}</span>
    `;
    subList.appendChild(row);

    const input = row.querySelector(`#num-${f.id}`);
    input.addEventListener("input", () => {
      const raw = input.value.trim();
      state.values[f.id] = raw === "" ? null : Number(raw);
      row.classList.toggle("active", raw !== "");
      onFiltersChanged();
    });
  });
}

function onFiltersChanged() {
  computeHexStates();      // fast -- runs immediately on every keystroke
  scheduleBlobRebuild();   // slow (turf) -- debounced
}

// ---- map setup -----------------------------------------------------
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

function setBlobStatus(text) {
  document.getElementById("blob-status").textContent = text;
}

const map = new maplibregl.Map({
  container: "map",
  style: "https://tiles.openfreemap.org/styles/positron",
  center: [-96, 39],
  zoom: 3.6,
  minZoom: 2.5,
  maxZoom: 12,
});

map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

// The stock "positron" basemap uses light blue water and blue-tinted road
// casings. Recolor anything blue-leaning to sit inside our warm palette.
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
let allFeatures = [];
let blobDebounceTimer = null;

map.on("load", async () => {
  recolorBasemap();

  const res = await fetch(DATA_URL);
  const geojson = await res.json();
  allFeatures = geojson.features;

  document.getElementById("cell-count-readout").textContent = `${allFeatures.length} CELLS`;
  setResolutionLabel(allFeatures[0]?.properties?.h3_res);

  // Invisible source/layer, purely for click hit-testing -- the actual
  // visuals are the blob layers below it.
  map.addSource(SOURCE_ID, { type: "geojson", data: geojson, promoteId: "h3" });
  map.addLayer({
    id: HIT_LAYER,
    type: "fill",
    source: SOURCE_ID,
    paint: { "fill-color": "#000", "fill-opacity": 0 },
  });

  // Blob layers, bottom to top: country silhouette, pass, excluded.
  addBlobLayer(BLOB_BASE_SRC, "rgba(150,138,104,0.28)", "#8f7f57", HIT_LAYER);
  addBlobLayer(BLOB_PASS_SRC, "rgba(75,93,52,0.6)", "#4b5d34", HIT_LAYER);
  addBlobLayer(BLOB_EXCL_SRC, "rgba(138,75,50,0.4)", "#8a4b32", HIT_LAYER);

  // Fit the real data extent instead of a guessed center/zoom -- this is
  // what was showing half of Canada and into Central America before.
  const bbox = turf.bbox(geojson);
  map.fitBounds(bbox, { padding: 20, duration: 0 });

  setBlobStatus("Building base map\u2026");
  setTimeout(() => {
    const baseBlob = dissolveAndSmooth(allFeatures, "base map");
    map.getSource(BLOB_BASE_SRC).setData(baseBlob);
    setBlobStatus("");
    dataLoaded = true;
    computeHexStates();
    rebuildBlobs();
  }, 0);

  map.on("click", HIT_LAYER, (e) => {
    if (!e.features.length) return;
    showPopup(e.features[0]);
  });
  map.on("mouseenter", HIT_LAYER, () => (map.getCanvas().style.cursor = "pointer"));
  map.on("mouseleave", HIT_LAYER, () => (map.getCanvas().style.cursor = ""));
});

function addBlobLayer(sourceId, fillColor, lineColor, beforeId) {
  map.addSource(sourceId, { type: "geojson", data: { type: "FeatureCollection", features: [] } });
  map.addLayer({
    id: `${sourceId}-fill`,
    type: "fill",
    source: sourceId,
    paint: { "fill-color": fillColor, "fill-opacity": 0.9 },
  }, beforeId);
  map.addLayer({
    id: `${sourceId}-line`,
    type: "line",
    source: sourceId,
    paint: { "line-color": lineColor, "line-width": 1 },
  }, beforeId);
}

// ---- hex pass/fail/excluded state (fast, runs on every keystroke) -----
function computeHexStates() {
  if (!dataLoaded && allFeatures.length === 0) return;

  allFeatures.forEach(ft => {
    const id = ft.properties.h3;
    let pass = true;
    for (const f of FILTERS) {
      const target = state.values[f.id];
      if (target === null) continue;
      const val = ft.properties[f.prop];
      if (f.type === "min" && val < target) { pass = false; break; }
      if (f.type === "max" && val > target) { pass = false; break; }
    }
    if (pass) {
      for (const f of SPORTS_LEAGUES) {
        const target = state.values[f.id];
        if (target === null) continue;
        if (ft.properties[f.prop] > target) { pass = false; break; }
      }
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

// ---- blob rendering (slow -- turf.js -- debounced) ---------------------
function scheduleBlobRebuild() {
  clearTimeout(blobDebounceTimer);
  setBlobStatus("Recalculating\u2026");
  blobDebounceTimer = setTimeout(rebuildBlobs, BLOB_DEBOUNCE_MS);
}

function rebuildBlobs() {
  if (!dataLoaded) return;

  const bruhEl = document.getElementById("bruh-overlay");
  const joke = checkEasterEgg();
  if (joke) {
    bruhEl.hidden = false;
    map.getSource(BLOB_PASS_SRC).setData({ type: "FeatureCollection", features: [] });
    map.getSource(BLOB_EXCL_SRC).setData({ type: "FeatureCollection", features: [] });
    document.getElementById("zoom-best-btn").disabled = true;
    setBlobStatus(`${joke} everywhere. bold strategy.`);
    return;
  }
  bruhEl.hidden = true;

  const passFeatures = [];
  const exclFeatures = [];
  allFeatures.forEach(ft => {
    const fs = map.getFeatureState({ source: SOURCE_ID, id: ft.properties.h3 });
    if (fs.excluded) exclFeatures.push(ft);
    else if (fs.pass) passFeatures.push(ft);
  });

  const passBlob = dissolveAndSmooth(passFeatures, "pass");
  const exclBlob = dissolveAndSmooth(exclFeatures, "excluded");

  map.getSource(BLOB_PASS_SRC).setData(passBlob);
  map.getSource(BLOB_EXCL_SRC).setData(exclBlob);
  setBlobStatus("");

  updateZoomBestButton(passBlob);
}

function dissolveAndSmooth(features, label) {
  const empty = { type: "FeatureCollection", features: [] };
  if (!features.length) return empty;

  if (features.length > DISSOLVE_MAX_FEATURES) {
    console.warn(`${label}: ${features.length} features is too many to blob smoothly -- showing raw hex shapes instead.`);
    return { type: "FeatureCollection", features };
  }

  let fc = turf.featureCollection(features.map(f => turf.polygon(f.geometry.coordinates)));
  try {
    fc = turf.dissolve(fc);
  } catch (e) {
    console.warn(`${label}: dissolve failed, showing un-merged hexes`, e);
    return { type: "FeatureCollection", features };
  }

  if (features.length <= SMOOTH_MAX_FEATURES) {
    try {
      fc = turf.polygonSmooth(fc, { iterations: 2 });
    } catch (e) {
      console.warn(`${label}: smoothing failed, showing dissolved-but-jagged shape`, e);
    }
  }
  return fc;
}

// ---- zoom to best match -------------------------------------------------
function updateZoomBestButton(passBlob) {
  const btn = document.getElementById("zoom-best-btn");
  if (!passBlob.features.length) {
    btn.disabled = true;
    return;
  }
  btn.disabled = false;
}

document.getElementById("zoom-best-btn").addEventListener("click", () => {
  const src = map.getSource(BLOB_PASS_SRC);
  if (!src) return;
  const data = src._data || src.serialize().data;
  if (!data.features.length) return;

  // Among the (possibly several, disconnected) blob pieces, zoom to
  // whichever single one covers the most area.
  let best = null;
  let bestArea = -1;
  for (const ft of data.features) {
    const a = turf.area(ft);
    if (a > bestArea) { bestArea = a; best = ft; }
  }
  const bbox = turf.bbox(best);
  map.fitBounds(bbox, { padding: 40, maxZoom: 9, duration: 600 });
});

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
  onFiltersChanged();
});

exclRadius.addEventListener("input", () => {
  state.exclusion.radiusMi = Number(exclRadius.value);
  exclRadiusOut.textContent = `${exclRadius.value} mi`;
  onFiltersChanged();
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
    onFiltersChanged();
  } catch (err) {
    geocodeStatus.textContent = "Geocoding failed. Check your connection and try again.";
  }
});

// ---- reset -------------------------------------------------------------
document.getElementById("reset-btn").addEventListener("click", () => {
  ALL_FIELDS.forEach(f => {
    state.values[f.id] = null;
    const input = document.getElementById(`num-${f.id}`);
    if (input) input.value = "";
    const row = document.getElementById(`filter-${f.id}`);
    if (row) row.classList.remove("active");
  });
  exclChk.checked = false;
  exclRow.classList.remove("enabled");
  state.exclusion = { enabled: false, lat: null, lng: null, radiusMi: 30 };
  exclInput.value = "";
  geocodeStatus.textContent = "";
  onFiltersChanged();
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
