/* Circle to Char — national results (docs/national.html).
   Reads data/national/summary.json, plants_<tag>.json, fields/<R>.json and manure.json, data/cement.geojson, and one
   constrained biochar figure from data/scenarios/scenarios.json. Every figure on the page comes from those files:
   a missing or malformed key hides or degrades its own element, and nothing throws. */
"use strict";

/* ---------- Colours and classes: the same values as the --c-* tokens in style.css ---------- */
const COL = { 1: "#eda100", 6: "#b23a00", 2: "#3b7dd8", 3: "#2e9e5b", 4: "#4a2c0f", 5: "#9aa0a6", 7: "#8e6bbf", 8: "#d1c4e9", 9: "#e0c9a6", 0: "#d0d0d0" };
// manure #cc1c88 (= --c-manure): checked pair by pair with the dataviz validator against every colour on this map
// (CVD ΔE at least 8.9, normal vision at least 17.0); manure and litter cells are also drawn as squares, unlike every round mark
const MARK = { region: "#ffd166", casing: "#1d2327", off: "#999999", soil: "#0f6e6a", cement: "#5b2c83", litter: "#e87ba4", manure: "#cc1c88" };
const RING = new Set([7, 8]);                  // one season observed: drawn as rings, so they never read as summer-only
const EDGE = { 9: "#7a5c2e", 0: "#5d6870" };   // pale classes get a dark edge so they show on desert imagery
const CODE = { winter_only: 1, wheat_rotation: 6, summer_only: 2, year_round: 3, palm_grove: 4, partly_seen_active: 7, idle: 5, partly_seen_inactive: 8, radar_unusable: 9, unseen: 0 };
const KEY_OF = Object.fromEntries(Object.entries(CODE).map(([k, c]) => [c, k]));
const NAME = { winter_only: "Winter only (wheat)", wheat_rotation: "Wheat, then summer crop", summer_only: "Summer only", year_round: "Year-round (fodder)", palm_grove: "Palm groves",
  partly_seen_active: "One season observed: farmed", idle: "Not detected by radar", partly_seen_inactive: "One season observed: not detected",
  radar_unusable: "Radar not usable (quality check)", unseen: "Not covered by radar" };
const FARMED = ["winter_only", "wheat_rotation", "summer_only", "year_round", "palm_grove", "partly_seen_active"];
const STATUS = { "no fields": "no fields mapped", "no radar": "no usable NISAR pass", error: "failed", "not run": "not processed" };
const FEED = { straw: "wheat straw", fronds: "palm fronds", manure: "manure", litter: "poultry litter" };
const LEVELS = ["low", "central", "high"];
const SIZES = [10, 25, 50];
const TABS = ["overview", "lenses", "official", "biochar", "method"];
const NO_HOVER = window.matchMedia ? matchMedia("(hover: none)").matches : false;
const COARSE = window.matchMedia ? matchMedia("(pointer: coarse)").matches : false;

const S = { level: "central", size: 50, data: {}, sc: null, manure: [], plants: [], plantsTag: null, plantsFailed: false,
  seq: 0, plantSeq: 0, current: null, fieldState: "idle", fieldsOf: null, rects: {}, base: {}, layers: {}, home: null, hintGone: false,
  openPopup: null, hadPopup: false, fkOpen: null };

/* ---------- Small helpers (never throw on missing data) ---------- */
const $ = (id) => document.getElementById(id);
const ok = (v) => typeof v === "number" && isFinite(v);
const obj = (v) => (v && typeof v === "object" && !Array.isArray(v)) ? v : null;
const arr = (v) => Array.isArray(v) ? v : [];
const get = (o, path) => path.split(".").reduce((a, k) => (a == null ? undefined : a[k]), o);
const fmt = (v, d = 0) => (v == null || v === "" || isNaN(v)) ? "–" : Number(v).toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d });
const pct = (x, d = 0) => ok(x) ? fmt(100 * x, d) + "%" : "–";
const esc = (t) => String(t == null ? "" : t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const cap = (t) => t ? String(t).charAt(0).toUpperCase() + String(t).slice(1) : "";
const list = (xs) => xs.length < 2 ? xs.join("") : xs.slice(0, -1).join(", ") + " and " + xs[xs.length - 1];
const span = (a, b, div = 1, d = 0) => {   // word joiners keep a range on one line; equal ends read as one value
  if (!ok(a) || !ok(b)) return null;
  const lo = fmt(Math.min(a, b) / div, d), hi = fmt(Math.max(a, b) / div, d);
  return lo === hi ? `${lo} either way` : `${lo}⁠–⁠${hi}`;
};
// data notes for the page: drop parentheticals that only name files, scripts or audit ids
const plain = (t) => String(t || "").replace(/\s*\((?:[^()]*\.(?:tif|py|csv|json)\b[^()]*|audit [^()]*)\)/g, "");
// URLs in source notes become links labelled by their host, so a long address never widens a phone page
const linkify = (t) => esc(t).replace(/https?:\/\/[^\s<]+[^\s<.,;:)]/g, (u) => {
  const host = u.replace(/^https?:\/\//, "").split(/[/?#]/)[0].replace(/^www\./, "");
  return `<a href="${u}" rel="noopener" title="${u}">${host}</a>`;
});
const sentence = (t) => { const x = cap(String(t || "").trim()); return x && !/[.!?]$/.test(x) ? x + "." : x; };
const chk = (id) => { const e = $(id); return !!(e && e.checked); };
// a renderer that throws logs the error and, given its container id, replaces "Loading…" with a failure line
const safe = (name, fn, box) => {
  try { return fn(); } catch (e) {
    if (window.console) console.error("national: " + name, e);
    const el = box && $(box);
    if (el) el.innerHTML = `<p class="loadfail">This section could not be drawn from the data.</p>`;
  }
};
async function j(p) { const r = await fetch(p); if (!r.ok) throw new Error(`${p} (${r.status})`); return r.json(); }

/* ---------- Data accessors ---------- */
const D = () => S.data || {};
const SUM = () => obj(D().summary) || {};
const PAR = () => obj(D().params) || {};
const regions = () => arr(D().regions).filter((r) => obj(r) && r.id != null);
const bboxOf = (r) => Array.isArray(r.bbox) && r.bbox.length === 4 && r.bbox.every(ok) ? r.bbox : null;
const seasonsOf = (r) => Array.isArray(r.seasons_classified) ? r.seasons_classified : ["winter", "summer"];
const isUsed = (r) => r.status === "ok" && seasonsOf(r).length > 0;
const farmedOf = (r) => ok(r.farmed_ha) ? r.farmed_ha : FARMED.reduce((t, k) => t + (ok(r[k + "_ha"]) ? r[k + "_ha"] : 0), 0);
const centreOf = (r) => { if (ok(r.lat) && ok(r.lon)) return [r.lat, r.lon]; const b = bboxOf(r); return b ? [(b[1] + b[3]) / 2, (b[0] + b[2]) / 2] : null; };
const pv = (k, lv = "central") => { const v = PAR()[k]; return ok(v) ? v : (obj(v) && ok(v[lv]) ? v[lv] : null); };
function counts() {
  const R = regions(), n = (st) => R.filter((r) => r.status === st).length;
  const withRadar = R.filter(isUsed).length;
  return { all: R.length, tried: R.length - n("not run"), withRadar, rejected: n("ok") - withRadar, n };
}
function tiers() {   // classification range (thresholds moved) and the radar + Sentinel-2 tier
  const s = SUM(), cr = obj(s.classification_range), sh = obj(cr && cr.shift_db);
  const d = sh && ok(sh.plus_1db) ? Math.abs(sh.plus_1db) : 1;
  return { cr, lo: cr && obj(cr.plus_1db), hi: cr && obj(cr.minus_1db), corners: cr && obj(cr.corners), thr: `±${fmt(d, d % 1 ? 1 : 0)} dB`,
    s2: obj(get(s, "s2_filled.radar_plus_s2_seasons")), s2only: obj(get(s, "s2_filled.s2_only_fields")), s2all: obj(get(s, "s2_filled.combined")) };
}
function effDate(iso) {   // the fodder-halt date and whether it is already in force
  const d = iso ? new Date(iso + "T00:00:00Z") : null;
  if (!d || isNaN(d)) return null;
  return { txt: d.toLocaleDateString("en-GB", { timeZone: "UTC", day: "numeric", month: "long", year: "numeric" }), past: Date.now() >= d.getTime() };
}

/* ====================================================================================================
   Map
   ==================================================================================================== */
let map = null;
function makeMap() {
  if (typeof L === "undefined") return;
  map = L.map("map", { zoomSnap: 0.25, renderer: L.canvas({ tolerance: COARSE ? 6 : 1 }) }).setView([24.5, 44.5], 5);
  L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
    maxZoom: 17, attribution: "Imagery © Esri, Maxar, Earthstar Geographics" }).addTo(map);
  // A click that closes an open popup only dismisses it. This listener is registered before any popup's own
  // preclick handler (which closes the popup), so it still sees the popup open.
  map.on("preclick", () => { S.hadPopup = !!S.openPopup; });
  map.on("click", onMapClick);
  map.on("popupopen", (e) => { S.openPopup = e.popup; Object.values(S.rects).forEach((x) => x.closeTooltip && x.closeTooltip()); });
  map.on("popupclose", (e) => { if (S.openPopup === e.popup) S.openPopup = null; });
  // the popup's details element changes its height: re-lay it out and keep it in view
  document.addEventListener("toggle", (e) => { const p = S.popup; if (e.target.closest && e.target.closest(".leaflet-popup") && p && p.isOpen()) p.update(); }, true);
}

function fitOpts() {   // keep the data clear of the floating tools card (desktop only)
  const tools = $("tools"), floating = window.innerWidth > 860 && tools;
  return { padding: [16, 16], paddingBottomRight: [16, (floating ? tools.offsetHeight + 30 : 0) + 16] };
}
function fit(bounds, after) {   // after: runs once the fitted view has settled
  if (!map || !bounds) return;
  const go = () => { if (after) map.once("moveend", after); map.fitBounds(bounds, fitOpts()); };
  // a fit started during a zoom animation (a double-click) is dropped: wait until that animation has fully ended
  if (map._animatingZoom) map.once("moveend", () => setTimeout(go, 0)); else go();
}
function restack() {   // draw order, bottom to top: region boxes, manure cells, fields, biochar plants, cement plants
  if (!map) return;
  ["manure", "fields", "plants", "cement"].forEach((k) => { const l = S.layers[k]; if (l && map.hasLayer(l) && l.bringToFront) l.bringToFront(); });
}
function setHint(text, isError) {
  const h = $("hint");
  if (!h) return;
  if (text == null) { h.remove(); S.hintGone = true; return; }
  h.textContent = text;
  h.classList.toggle("error", !!isError);
}

/* ---------- Region boxes ---------- */
function regionTip(r) {
  const sc = seasonsOf(r);
  if (isUsed(r)) return `${esc(r.id)}: ${fmt(farmedOf(r))} ha farmed by radar${sc.length === 1 ? ` (only the ${esc(sc[0])} season observed)` : ""}`;
  if (r.status === "ok") return `${esc(r.id)}: radar not usable (quality check); ${fmt(r.field_ha)} ha of fields mapped`;
  return `${esc(r.id)} (${esc(STATUS[r.status] || r.status || "not processed")})`;
}
function popupHtml(r) {
  if (r.status !== "ok") return `<b>${esc(r.id)}</b>: ${esc(STATUS[r.status] || r.status || "not processed")}`;
  const v = obj(r.validation) || {}, sc = seasonsOf(r), n0 = (x) => ok(x) ? x : 0;
  const vs = (k) => obj(v[k]) && sc.includes(k) ? `agreement ${pct(ok(v[k].area_agreement) ? v[k].area_agreement : v[k].agreement)}, kappa ${fmt(v[k].kappa, 2)}` : "not classified";
  const row = (a, b) => `<tr><th scope="row">${a}</th><td>${b}</td></tr>`;
  return `<b>${esc(r.id)}</b>${isUsed(r) ? "" : " · radar not usable (quality check)"}
    <table class="pop">${row("Farmed by radar", isUsed(r) ? `${fmt(farmedOf(r))} ha` : "–")}${row("Fields mapped", `${fmt(r.fields)} fields, ${fmt(r.field_ha)} ha`)}
      ${row("Water", `${ok(r.water_m3) ? fmt(r.water_m3 / 1e6) : "–"} Mm³/y`)}${row("Straw · fronds", `${fmt(r.straw_t)} · ${fmt(r.fronds_t)} t`)}</table>
    <details class="pop-more"><summary>Classes, radar check and dates</summary>
    Wheat ${fmt(n0(r.winter_only_ha) + n0(r.wheat_rotation_ha))} ha (incl. rotation) · summer only ${fmt(r.summer_only_ha)} ha<br>
    Year-round ${fmt(r.year_round_ha)} ha · palms ${fmt(r.palm_grove_ha)} ha<br>
    One season observed ${fmt(n0(r.partly_seen_active_ha) + n0(r.partly_seen_inactive_ha))} ha (${fmt(r.partly_seen_active_ha)} ha farmed in the season observed)<br>
    Not detected by radar ${fmt(r.idle_ha)} ha${r.radar_unusable_ha ? ` · radar not usable ${fmt(r.radar_unusable_ha)} ha` : ""} · not covered by radar ${fmt(r.unseen_ha)} ha<br>
    Radar vs Sentinel-2${v.basis ? " (this region's own fields)" : ""}: winter ${vs("winter")}; summer ${vs("summer")}<br>
    Radar dates: ${arr(r.dates).map(esc).join(", ") || "–"}</details>`;
}
function drawRegions() {
  if (!map) return;
  const g = L.featureGroup();
  S.rects = {}; S.base = {};
  const ext = [];
  regions().forEach((r) => {
    const b = bboxOf(r);
    if (!b) return;
    const bounds = [[b[1], b[0]], [b[3], b[2]]], u = isUsed(r);
    if (r.status === "ok") ext.push(bounds[0], bounds[1]);
    if (u) L.rectangle(bounds, { color: MARK.casing, weight: 4, opacity: 0.35, fill: false, interactive: false }).addTo(g);
    const base = u ? { color: MARK.region, weight: 1.5, opacity: 1, fillColor: MARK.region, fillOpacity: 0.08, dashArray: null }
      : { color: MARK.off, weight: 1, opacity: 1, fillColor: MARK.off, fillOpacity: 0.02, dashArray: "4 4" };
    const rect = L.rectangle(bounds, Object.assign({ interactive: !NO_HOVER }, base));
    if (!NO_HOVER) {   // Leaflet opens tooltips on tap, so touch screens get the popup only
      rect.bindTooltip(regionTip(r), { sticky: true, direction: "top", offset: [0, -8] });
      rect.on("mouseover", () => rect.setStyle({ fillOpacity: 0.2 }));
      rect.on("mouseout", () => rect.setStyle({ fillOpacity: S.base[r.id].fillOpacity }));
    }
    S.rects[r.id] = rect; S.base[r.id] = base;
    rect.addTo(g);
  });
  S.layers.regions = g;
  S.home = ext.length ? L.latLngBounds(ext) : null;
  if (chk("showregions")) g.addTo(map);
}
function highlight(r, on) {
  const rect = r && S.rects[r.id];
  if (!rect) return;
  rect.setStyle(on ? { weight: 3, color: "#fff" } : S.base[r.id]);
}
function pickRegion(ll) {   // by position: smallest processed box under the point, else the nearest processed centre within 24 px, else any box
  const R = regions(), inside = (r) => { const b = bboxOf(r); return b && ll.lng >= b[0] && ll.lng <= b[2] && ll.lat >= b[1] && ll.lat <= b[3]; };
  const area = (r) => { const b = bboxOf(r); return (b[2] - b[0]) * (b[3] - b[1]); };
  const hit = R.filter((r) => r.status === "ok" && inside(r)).sort((a, b) => area(a) - area(b));
  if (hit.length) return hit[0];
  const p = map.latLngToContainerPoint(ll);
  let best = null, bd = 24;
  R.filter((r) => r.status === "ok").forEach((r) => { const c = centreOf(r); if (!c) return; const d = map.latLngToContainerPoint(c).distanceTo(p); if (d <= bd) { bd = d; best = r; } });
  if (best) return best;
  return R.filter((r) => r.status !== "ok" && inside(r)).sort((a, b) => area(a) - area(b))[0] || null;
}
function onMapClick(e) {
  const closed = S.hadPopup;   // this click closed a popup (Leaflet closes it on preclick)
  S.hadPopup = false;
  if (!S.layers.regions || !map.hasLayer(S.layers.regions)) return;   // boxes hidden: the Region list still works
  const oe = e.originalEvent;
  // Leaflet hands clicks on small markers to the map with the marker's own centre as latlng: use the pointer position
  const ll = oe && "clientX" in oe ? map.mouseEventToLatLng(oe) : e.latlng;
  const r = pickRegion(ll);
  // a click that closed a popup only dismisses it, unless it picks a different processed region
  if (closed && (!r || r.status !== "ok" || (S.current && S.current.id === r.id))) return;
  if (!r) return;
  if (r.status === "ok") selectRegion(r); else regionPopup(r);
}
function regionPopup(r) {
  const c = centreOf(r);
  if (!map || !c) return;
  const box = document.createElement("div");   // a node, not a string, so update() keeps the details element's open state
  box.innerHTML = popupHtml(r);
  S.popup = L.popup({ maxWidth: 300, minWidth: 220, maxHeight: Math.max(160, map.getSize().y - 56), autoPanPadding: [16, 16] }).setLatLng(c).setContent(box).openOn(map);
}
async function selectRegion(r) {
  if (!r) return back();
  if (!map) return;
  if (S.current && S.current.id === r.id) { regionPopup(r); return; }   // clicks on its own fields reach the map too: no refetch
  const tok = ++S.seq;
  if (S.current) highlight(S.current, false);
  S.current = r;
  highlight(r, true);
  syncRegionSelect(r.id);
  regionPopup(r);
  if (!S.hintGone) setHint(null);
  S.fieldState = "loading";
  renderFieldKey();
  let rows;
  try { rows = await j(`data/national/fields/${encodeURIComponent(r.id)}.json`); }
  catch (e) { if (tok === S.seq) { S.fieldState = "error"; renderFieldKey(); } return; }
  if (tok !== S.seq) return;   // a newer selection took over
  drawFields(r, arr(rows));
  S.fieldState = "loaded";
  renderFieldKey();
  const b = bboxOf(r);
  if (!b) return;
  // after the zoom to the region, pan once more so the region's popup is not cut off at the top
  fit(L.latLngBounds([[b[1], b[0]], [b[3], b[2]]]), () => { const p = S.popup; if (tok === S.seq && p && p.isOpen()) p.update(); });
}
function back() {
  S.seq++;   // drop any field load in flight
  clearFields();
  if (S.current) highlight(S.current, false);
  S.current = null;
  S.fieldState = "idle";
  syncRegionSelect("");
  renderFieldKey();   // first, so the fit pads for the card at its new height
  if (map) { map.closePopup(); fit(S.home); }
}
function fillRegionSelect() {
  const sel = $("region");
  if (!sel) return;
  const R = regions().filter((r) => r.status === "ok");
  const used = R.filter(isUsed).sort((a, b) => farmedOf(b) - farmedOf(a));
  const rej = R.filter((r) => !isUsed(r)).sort((a, b) => String(a.id).localeCompare(String(b.id)));
  sel.innerHTML = `<option value="">All regions</option>` +
    (used.length ? `<optgroup label="Radar results (largest farmed area first)">${used.map((r) => `<option value="${esc(r.id)}">${esc(r.id)} · ${fmt(farmedOf(r))} ha farmed</option>`).join("")}</optgroup>` : "") +
    (rej.length ? `<optgroup label="Radar failed the quality check">${rej.map((r) => `<option value="${esc(r.id)}">${esc(r.id)} · radar not usable</option>`).join("")}</optgroup>` : "");
  sel.value = "";
  sel.disabled = !map;
  sel.onchange = () => { const r = R.find((x) => String(x.id) === sel.value); if (r) selectRegion(r); else back(); };
}
function syncRegionSelect(id) { const sel = $("region"); if (sel && sel.value !== String(id)) sel.value = String(id); }

/* ---------- Fields of the selected region ---------- */
function fieldStyle(ha, c) {
  const r = Math.max(2, Math.min(9, Math.sqrt(ok(ha) ? ha : 1) / 1.6));
  if (RING.has(c)) return { radius: Math.max(3, r), stroke: true, color: COL[c], weight: 2, opacity: 1, fillColor: "#fff", fillOpacity: 0.9 };
  if (EDGE[c]) return { radius: r, stroke: true, color: EDGE[c], weight: 1, opacity: 0.9, fillColor: COL[c], fillOpacity: 0.9 };
  return { radius: r, stroke: false, fillColor: COL[c] || COL[0], fillOpacity: 0.85 };
}
const className = (c) => NAME[KEY_OF[c]] || "Field";
function fieldHtml(f, r) {
  const k = KEY_OF[f.c];
  const s2 = ok(f.s2) && f.s2 !== f.c ? `<br>Radar + Sentinel-2 tier: ${esc(className(f.s2))}` : "";
  return `<b>${esc(className(f.c))}</b><br>${fmt(f.ha, 1)} ha · ${esc(r.id)} · ${FARMED.includes(k) ? "in the farmed total" : "not in the farmed total"}${s2}`;
}
function drawFields(r, rows) {
  clearFields();
  const g = L.featureGroup();
  let n = 0;
  rows.forEach((row) => {
    if (!Array.isArray(row) || row.length < 4 || !ok(row[0]) || !ok(row[1])) return;
    const m = L.circleMarker([row[1], row[0]], Object.assign({ bubblingMouseEvents: false }, fieldStyle(row[2], row[3])));
    m.f = { ha: row[2], c: row[3], s2: row[4] };
    g.addLayer(m);
    n++;
  });
  g.on("click", (e) => {
    const m = e.layer;
    if (m && m.f) L.popup({ maxWidth: 260, autoPanPadding: [16, 16] }).setLatLng(m.getLatLng()).setContent(fieldHtml(m.f, r)).openOn(map);
  });
  if (!NO_HOVER) g.on("mouseover", (e) => {   // tooltips are bound on first hover only (thousands of fields)
    const m = e.layer;
    if (m && m.f && !m.getTooltip()) m.bindTooltip(`${esc(className(m.f.c))} · ${fmt(m.f.ha, 1)} ha`, { direction: "top", offset: [0, -4] }).openTooltip();
  });
  S.layers.fields = g.addTo(map);
  S.fieldsOf = { id: r.id, n };
  restack();
}
function clearFields() {
  if (S.layers.fields && map) map.removeLayer(S.layers.fields);
  S.layers.fields = null;
  S.fieldsOf = null;
}

/* ---------- Biochar plants: one marker per site ---------- */
const plantTag = (size) => `central_${size}kt`;
function plantLine(p, size) {
  const feeds = ["straw", "fronds", "manure", "litter"].filter((f) => ok(p["feed_" + f]) && p["feed_" + f] > 0)
    .map((f) => `${f} ${fmt(p["feed_" + f])}`).join(" · ");
  return `Plant ${esc(p.plant)}: ${size} kt/y · ${fmt(p.net_removal_tco2)} t CO₂/y net of transport, via ${esc(p.best_outlet)}${p.best_outlet === "cement" ? ` (${esc(p.cement_name)}, ${fmt(p.cement_km)} km)` : ""}${feeds ? `<br>feed: ${feeds} t` : ""}`;
}
function plantMarker(ps, size) {
  const top = ps.slice().sort((a, b) => (b.net_removal_tco2 || 0) - (a.net_removal_tco2 || 0))[0];
  const net = ps.reduce((t, p) => t + (ok(p.net_removal_tco2) ? p.net_removal_tco2 : 0), 0);
  const tip = ps.length === 1 ? plantLine(top, size)
    : `<b>One site, ${ps.length} plants</b> (${fmt(size * ps.length)} kt/y in all, ${fmt(net)} t CO₂/y net of transport)<br>` + ps.map((p) => plantLine(p, size)).join("<br>");
  return L.circleMarker([top.lat, top.lon], { radius: 4 + Math.sqrt(size * ps.length) / 1.5, color: "#fff", weight: 2, opacity: 1,
    fillColor: top.best_outlet === "cement" ? MARK.cement : MARK.soil, fillOpacity: 0.95 }).bindTooltip(tip);
}
async function drawPlants() {
  const tok = ++S.plantSeq, size = S.size, tag = plantTag(size);
  let plants = null;
  // the export publishes a plants file only for the siting runs in the summary
  if (obj(get(D(), `siting.${tag}`))) { try { plants = arr(await j(`data/national/plants_${tag}.json`)); } catch (e) { plants = null; } }
  if (tok !== S.plantSeq) return;   // a newer size took over; this response is stale
  if (S.layers.plants && map) map.removeLayer(S.layers.plants);
  S.plants = plants || [];
  S.plantsTag = tag;
  S.plantsFailed = plants == null;
  if (map) {
    const sites = new Map();
    S.plants.forEach((p) => {
      if (!obj(p) || !ok(p.lat) || !ok(p.lon)) return;
      const k = p.lat.toFixed(4) + "," + p.lon.toFixed(4);
      if (!sites.has(k)) sites.set(k, []);
      sites.get(k).push(p);
    });
    S.layers.plants = L.featureGroup([...sites.values()].map((ps) => plantMarker(ps, size)));
    if (chk("showplants")) S.layers.plants.addTo(map);
    restack();
  }
  renderLegend();
}

/* ---------- Cement plants: a hollow ring with a white halo, always on top ---------- */
function addCement(gj) {
  if (!map) return;
  const g = L.featureGroup();
  arr(gj && gj.features).forEach((f) => {
    const c = get(f, "geometry.coordinates");
    if (!Array.isArray(c) || !ok(c[0]) || !ok(c[1])) return;
    const p = obj(f.properties) || {}, ll = [c[1], c[0]];
    const who = [p.owner_name, p.city].filter((x) => x).map(esc).join(", ") || "name not listed";
    L.circleMarker(ll, { radius: 7, color: "#fff", weight: 5, opacity: 0.85, fill: false, interactive: false }).addTo(g);
    L.circleMarker(ll, { radius: 7, color: MARK.cement, weight: 2.5, opacity: 1, fill: false })
      .bindTooltip(`Cement plant: ${who}${ok(p.cap) ? ` · capacity ${fmt(p.cap, p.cap % 1 ? 2 : 0)} Mt/y` : ""}`).addTo(g);
  });
  S.layers.cement = g;
  if (chk("showcement")) g.addTo(map);
  restack();
}

/* ---------- Modelled manure and litter: every cell, summed to a 0.25° grid, drawn as squares ---------- */
// A circle marker drawn as a square on the canvas renderer (a circle on any other renderer), so the grid cells never
// read as plants, fields or cement plants. Hit-testing follows the square.
let SquareMarker = null;
function squareMarker(ll, opts) {
  if (!SquareMarker) SquareMarker = L.CircleMarker.extend({
    _updatePath() {
      const R = this._renderer;
      if (!R._ctx) { R._updateCircle(this); return; }
      if (!R._drawing || this._empty()) return;
      const p = this._point, ctx = R._ctx, r = Math.max(Math.round(this._radius), 1);
      ctx.beginPath();
      ctx.rect(p.x - r, p.y - r, 2 * r, 2 * r);
      R._fillStroke(ctx, this);
    },
    _containsPoint(p) { const r = this._radius + this._clickTolerance(); return Math.abs(p.x - this._point.x) <= r && Math.abs(p.y - this._point.y) <= r; },
  });
  return new SquareMarker(ll, opts);
}
function drawManure() {
  if (!map) return;
  const bins = new Map();
  arr(S.manure).forEach((m) => {
    if (!Array.isArray(m) || m.length < 4 || !ok(m[0]) || !ok(m[1])) return;
    const gx = Math.round(m[0] / 0.25) * 0.25, gy = Math.round(m[1] / 0.25) * 0.25, k = gx.toFixed(2) + "," + gy.toFixed(2);
    let b = bins.get(k);
    if (!b) bins.set(k, b = { lon: gx, lat: gy, lt: 0, mt: 0 });
    b.lt += ok(m[2]) ? m[2] : 0;
    b.mt += ok(m[3]) ? m[3] : 0;
  });
  const cells = [...bins.values()].filter((b) => b.lt + b.mt > 0).sort((a, b) => (b.lt + b.mt) - (a.lt + a.mt));   // small cells drawn last, on top
  const tmax = cells.length ? cells[0].lt + cells[0].mt : 1;
  S.layers.manure = L.featureGroup(cells.map((b) => {
    const r = Math.max(1.5, 8 * Math.sqrt((b.lt + b.mt) / tmax));   // half the side; area grows with dry tonnes
    return squareMarker([b.lat, b.lon], {
      radius: r, stroke: r >= 3, color: "#fff", weight: 0.75, opacity: 0.85,   // tiny cells without a rim, or the rim is all one sees
      fillColor: b.lt > b.mt ? MARK.litter : MARK.manure, fillOpacity: 0.85 })
      .bindTooltip(`0.25° cell, modelled: manure ${fmt(b.mt)} t, poultry litter ${fmt(b.lt)} t dry a year${b.lt > 0 ? " (litter is not credited)" : ""}`);
  }));
  if (chk("showmanure")) S.layers.manure.addTo(map);
  restack();
}

/* ---------- Layer toggles and the map key ---------- */
function toggleLayer(k, on) {
  const l = S.layers[k];
  if (map && l) { if (on) { l.addTo(map); restack(); } else map.removeLayer(l); }
  renderLegend();
}
function glyph(c) {
  if (RING.has(c)) return `<i class="ring" style="--c:${COL[c]}" aria-hidden="true"></i>`;
  if (EDGE[c]) return `<i class="dot edge" style="--c:${COL[c]};--e:${EDGE[c]}" aria-hidden="true"></i>`;
  return `<i class="dot" style="--c:${COL[c]}" aria-hidden="true"></i>`;
}
function renderLegend() {
  const set = (id, html) => { const e = $(id); if (e) e.innerHTML = html; };
  const dot = (c, label) => `<li><i class="dot" style="--c:${c}" aria-hidden="true"></i>${label}</li>`;
  set("k-regions", `<li><i class="box" style="--c:${MARK.region}" aria-hidden="true"></i>radar results</li><li><i class="dash" aria-hidden="true"></i>radar failed the quality check, or not processed</li>`);
  set("k-plants", S.plantsFailed ? `<li class="kn">no plant list in this data export</li>`
    : dot(MARK.soil, "char to soil") + dot(MARK.cement, "char to cement") + `<li class="kn">size shows capacity; one per site</li>`);
  set("k-cement", `<li><i class="ring" style="--c:${MARK.cement}" aria-hidden="true"></i>cement plant</li>`);
  const sq = (c, label) => `<li><i class="sq" style="--c:${c}" aria-hidden="true"></i>${label}</li>`;
  set("k-manure", sq(MARK.manure, "mostly manure") + sq(MARK.litter, "mostly poultry litter (not credited)") + `<li class="kn">one square per 0.25° cell; size grows with dry tonnes</li>`);
  [["showregions", "k-regions"], ["showplants", "k-plants"], ["showcement", "k-cement"], ["showmanure", "k-manure"]]
    .forEach(([c, k]) => { const e = $(k); if (e) e.hidden = !chk(c); });
  renderFieldKey();
}
function renderFieldKey() {
  const st = $("fieldstatus"), fk = $("fieldkey"), bb = $("backbtn"), kb = $("keybtn"), bar = $("fieldbar"), tools = $("tools"), r = S.current;
  if (!st || !fk) return;
  if (bb) bb.hidden = !r;
  if (kb) kb.hidden = true;
  if (bar) bar.hidden = !!map && !r && !S.hintGone;   // before the first region, the hint over the map says it
  if (tools) tools.classList.toggle("has-fields", !!r);   // desktop: the layer keys fold away while a region is open
  fk.hidden = true;
  if (!map) { st.textContent = "The map did not load; the figures in the panel do not need it."; return; }
  if (!r) { st.textContent = "Click or tap a yellow box, or choose a region, to load its fields."; return; }
  if (S.fieldState === "loading") { st.textContent = `Loading fields for ${r.id}…`; return; }
  if (S.fieldState === "error") { st.textContent = `Could not load the fields for ${r.id}.`; return; }
  if (!S.fieldsOf || S.fieldsOf.id !== r.id) { st.textContent = ""; return; }
  st.innerHTML = `<b>Fields in ${esc(r.id)}</b> · ${fmt(S.fieldsOf.n)} fields${isUsed(r) ? "" : " (radar not usable: quality check)"}`;
  const item = (k) => `<li>${glyph(CODE[k])}${NAME[k]}</li>`;
  fk.innerHTML = `<p class="key-h">Farmed (in the total)</p><ul class="key">${FARMED.map(item).join("")}</ul>` +
    `<p class="key-h">Not in the total: not detected, or no usable radar view</p><ul class="key">${Object.keys(CODE).filter((k) => !FARMED.includes(k)).map(item).join("")}</ul>`;
  // The key can be folded away so the floating card stays short. It starts open unless the map is short (desktop),
  // and then stays as the viewer left it.
  if (S.fkOpen == null) S.fkOpen = !(window.innerWidth > 860 && map.getSize().y < 680);
  fk.hidden = !S.fkOpen;
  if (kb) {
    kb.hidden = false;
    kb.setAttribute("aria-expanded", S.fkOpen ? "true" : "false");
    kb.textContent = S.fkOpen ? "Hide field key" : "Show field key";
  }
}
function toggleFieldKey() {
  S.fkOpen = !S.fkOpen;
  renderFieldKey();
}

/* ====================================================================================================
   Panel: tabs, estimate switch
   ==================================================================================================== */
function openTab(n, opts) {
  if (!TABS.includes(n)) return;
  const o = opts || {};
  document.querySelectorAll(".tabs [data-tab]").forEach((b) => {
    const on = b.dataset.tab === n;
    b.classList.toggle("on", on);
    b.setAttribute("aria-selected", on ? "true" : "false");
    b.tabIndex = on ? 0 : -1;
  });
  document.querySelectorAll("aside .tab").forEach((p) => p.classList.toggle("on", p.id === "tab-" + n));
  if (o.hash !== false) { try { history.replaceState(null, "", "#" + n); } catch (e) { /* sandboxed: keep going */ } }
  if (o.scroll === false) return;
  const aside = document.querySelector("aside"), tabs = document.querySelector(".tabs"), panel = $("tab-" + n);
  if (window.innerWidth > 860) { if (aside) aside.scrollTop = 0; }
  else if (tabs && panel) {   // phones: if the page is scrolled into the panel, bring its top back under the sticky tabs
    const gap = panel.getBoundingClientRect().top - tabs.getBoundingClientRect().bottom;
    if (gap < 0) window.scrollBy(0, gap);
  }
}
function initTabs() {
  const btns = [...document.querySelectorAll(".tabs [data-tab]")];
  btns.forEach((b) => b.addEventListener("click", () => openTab(b.dataset.tab)));
  const bar = document.querySelector(".tabs");
  if (bar) bar.addEventListener("keydown", (e) => {
    const i = btns.indexOf(document.activeElement);
    if (i < 0) return;
    const to = e.key === "ArrowRight" ? (i + 1) % btns.length : e.key === "ArrowLeft" ? (i - 1 + btns.length) % btns.length
      : e.key === "Home" ? 0 : e.key === "End" ? btns.length - 1 : -1;
    if (to < 0) return;
    e.preventDefault();
    btns[to].focus();
    openTab(btns[to].dataset.tab);
  });
  const fromHash = () => { const h = decodeURIComponent(location.hash.slice(1)); if (TABS.includes(h)) openTab(h, { hash: false }); };
  window.addEventListener("hashchange", fromHash);
  fromHash();
}
function levelSeg(labelId) {
  return `<div class="seg level" role="group" aria-labelledby="${labelId}">${LEVELS.map((l) =>
    `<button type="button" data-level="${l}" aria-pressed="${S.level === l}"${S.level === l ? ' class="on"' : ""}>${cap(l)}</button>`).join("")}</div>`;
}
function setLevel(l, from) {
  if (!LEVELS.includes(l)) return;
  if (l !== S.level) {
    S.level = l;
    safe("overview", renderOverview, "ov");
    safe("lenses", renderLenses, "lens");
  }
  document.querySelectorAll(".level button[data-level]").forEach((x) => {
    const on = x.dataset.level === l;
    x.classList.toggle("on", on);
    x.setAttribute("aria-pressed", on ? "true" : "false");
  });
  if (from) { const b = document.querySelector(`#${from} .level button[data-level="${l}"]`); if (b) b.focus(); }   // keep focus after the re-render
}

/* ====================================================================================================
   Overview
   ==================================================================================================== */
function kpi(label, unit, key, div, d) {
  const s = SUM(), v = obj(s[key]), L_ = S.level, t = tiers();
  if (!v) return "";
  const corn = t.corners && obj(t.corners[key]);
  const rows = [
    ["Factor range", span(v.low, v.high, div, d)],
    t.lo && t.hi ? [`Threshold<span class="lg"> ${t.thr}</span>`, span(get(t.lo, `${key}.${L_}`), get(t.hi, `${key}.${L_}`), div, d)] : null,
    corn ? ["Both at once", span(corn.low, corn.high, div, d)] : null,
  ].filter((x) => x && x[1]);
  return `<div class="kpi"><div class="kpi-label">${label}</div><div class="kpi-value">${fmt(ok(v[L_]) ? v[L_] / div : null, d)}<span class="kpi-unit">${unit}</span></div>` +
    (rows.length ? `<dl class="kpi-range">${rows.map(([a, b]) => `<div><dt>${a}</dt><dd>${b}</dd></div>`).join("")}</dl>` : "") + `</div>`;
}
function swatch(c) {
  if (RING.has(c)) return `<span class="swatch ring" style="--c:${COL[c]}" aria-hidden="true"></span>`;
  return `<span class="swatch${EDGE[c] ? " edge" : ""}" style="background:${COL[c]};--e:${EDGE[c] || "transparent"}" aria-hidden="true"></span>`;
}
function energyCallout() {
  const s = SUM(), ph = obj(s.pumping_head), sh = obj(s.shield_no_energy);
  const notes = obj(ph && ph.notes) || obj(D().lift_notes) || obj(D().lift) || {};
  const eff = pv("pump_wire_to_water_eff");
  const why = [];
  if (ok(eff)) why.push(`the pump is a well-run one (${pct(eff)} wire to water)`);
  if (sh && ok(sh.field_ha_with_water)) why.push(`the Arabian Shield regions get no pumping energy, although their ${fmt(sh.field_ha_with_water)} ha of watered fields take ${pct(get(sh, "share_of_water.central"))} of the water` +
    (ok(get(sh, "indicative_elec_kwh_at_fallback_lift.central")) ? ` (about ${fmt(sh.indicative_elec_kwh_at_fallback_lift.central / 1e9, 2)} TWh more at the fallback head, not in any total)` : ""));
  else if (notes._shield) why.push("the Arabian Shield regions get no pumping energy");
  if (typeof notes._age === "string") why.push("the depths to water are older measurements, and water levels have fallen since");
  const joined = why.length < 2 ? why.join("") : why.slice(0, -1).join("; ") + "; and " + why[why.length - 1];
  const head = ph && ph.rule ? ` Pumping ${esc(ph.rule)}.` : " Pumping energy uses regional depth to water (no drawdown).";
  return `<p class="callout">Electricity, summer load and CO₂ are modelled, not metered${why.length ? `, and likely lower bounds: ${joined}` : ""}.${head} (<a href="#method">Method tab</a>)</p>`;
}
function s2Block() {
  const s = SUM(), t = tiers(), L_ = S.level, f = obj(get(s, "s2_filled")) || {};
  if (!t.s2) return "";
  const cols = [["Radar", s], ["Radar + Sentinel-2", t.s2]].concat(t.s2all ? [["With Sentinel-2-only fields", t.s2all]] : []);
  const cell = (o, key, div, d) => { const v = key === "farmed_ha" ? o.farmed_ha : get(o, `${key}.${L_}`); return `<td class="num">${ok(v) ? fmt(v / div, d) : "–"}</td>`; };
  const rows = [["Farmed, ha", "farmed_ha", 1, 0], ["Water, bn m³ / yr", "water_m3", 1e9, 2], ["Electricity, TWh / yr", "elec_kwh", 1e9, 2],
    ["Summer load, MW", "summer_pumping_avg_mw", 1, 0], ["Pumping CO₂ (grid), Mt / yr", "co2_t_grid", 1e6, 2],
    ["Wheat straw, kt dry / yr", "straw_t_dry", 1e3, 0], ["Palm fronds, kt dry / yr", "fronds_t_dry", 1e3, 0]];
  const caps = obj(f.caps), capped = arr(caps && caps.regions_capped);
  const unc = get(t.s2, `straw_t_dry_uncapped.${L_}`);
  const scopes = [["Radar + Sentinel-2", t.s2], ["Sentinel-2-only fields", t.s2only], ["With Sentinel-2-only fields", t.s2all]].filter(([, o]) => o && o.scope);
  return `<h3>Radar + Sentinel-2 (context)</h3>
    <p class="note">A second tier, published next to the radar-only figures and never replacing them. Sentinel-2 fills winters the radar missed and seasons it did not observe; the area it adds is measured by Sentinel-2, not by the radar.${t.s2all ? " The last column also classifies, from Sentinel-2 alone, fields with no usable radar season, and counts them all as farmed: an upper bound for those fields." : ""}${capped.length ? ` Straw on wheat that only Sentinel-2 sees is capped at GASTAT's 2024 wheat area in each region (the cap binds in ${list(capped.map(esc))})${ok(unc) ? `; uncapped it would be ${fmt(unc / 1e3)} kt` : ""}.` : ""} At the ${esc(L_)} estimate:</p>
    <table class="s2t"><tr><th></th>${cols.map(([h]) => `<th class="num">${h}</th>`).join("")}</tr>
      ${rows.map(([label, key, div, d]) => `<tr><td>${label}</td>${cols.map(([, o]) => cell(o, key, div, d)).join("")}</tr>`).join("")}</table>
    ${scopes.length || f.rule ? `<details class="more"><summary>How the tier is built</summary>${scopes.map(([h, o]) => `<p><b>${h}:</b> ${esc(sentence(o.scope))}</p>`).join("")}${f.rule ? `<p>${esc(sentence(f.rule))}</p>` : ""}${caps && caps.rule ? `<p><b>Straw cap:</b> ${esc(sentence(caps.rule))}</p>` : ""}</details>` : ""}`;
}
function reproBlock() {
  const rp = obj(SUM().reproducibility), w = obj(rp && rp.winter), su = obj(rp && rp.summer);
  if (!w || !su || !ok(w.agreement) || !ok(su.agreement)) return "";
  const big = [].concat(arr(w.largest_disagreements).map((x) => ["winter", x]), arr(su.largest_disagreements).map((x) => ["summer", x])).filter(([, x]) => obj(x));
  return `<h3>Reproducibility: fields seen by two boxes</h3>
    <p>Where two neighbouring boxes map the same fields (${fmt(rp.field_pairs)} field pairs, ${fmt(rp.field_pairs_ha)} ha), each copy is classified against its own box's desert background and threshold. The two radar calls agree on <b>${pct(w.agreement, 1)}</b> of the shared area in winter (kappa ${fmt(w.kappa, 2)}) and <b>${pct(su.agreement, 1)}</b> in summer (kappa ${fmt(su.kappa, 2)})${ok(get(w, "s2_control.agreement")) && ok(get(su, "s2_control.agreement")) ? `; Sentinel-2's flags for the same fields agree on ${pct(w.s2_control.agreement, 1)} and ${pct(su.s2_control.agreement, 1)}` : ""}.${ok(w.disagreement_over_mean_active) && ok(su.disagreement_over_mean_active) ? ` The area the boxes disagree on equals ${pct(w.disagreement_over_mean_active)} (winter) and ${pct(su.disagreement_over_mean_active)} (summer) of the area they call farmed, so a region's farmed area depends partly on which box classifies it.` : ""} The threshold range under the figures shows how far the national totals move when every region's threshold shifts.</p>
    ${big.length || rp.rule ? `<details class="more"><summary>Largest disagreements, and the rule</summary>${big.length ? `<table><tr><th>Season</th><th>Boxes</th><th class="num">Shared ha</th><th class="num">Farmed ha, each box</th></tr>${big.map(([k, x]) => `<tr><td>${k}${x.same_radar_dates ? "" : "*"}</td><td>${esc(x.box_a)} / ${esc(x.box_b)}</td><td class="num">${fmt(x.ha)}</td><td class="num">${fmt(x.active_ha_box_a)} / ${fmt(x.active_ha_box_b)}</td></tr>`).join("")}</table><p>* the two boxes used different radar dates; all others used the same scenes.</p>` : ""}${rp.rule ? `<p>${esc(sentence(rp.rule))}</p>` : ""}</details>` : ""}`;
}
function renderOverview() {
  const el = $("ov");
  if (!el) return;
  const s = SUM(), a = obj(s.area_ha_by_class) || {}, act = obj(s.active_ha) || {}, nob = obj(s.season_not_observed_ha) || {};
  const farmed = ok(s.farmed_ha) ? s.farmed_ha : FARMED.some((k) => ok(a[k])) ? FARMED.reduce((t, k) => t + (ok(a[k]) ? a[k] : 0), 0) : null;
  const c = counts(), t = tiers(), v = obj(D().validation) || {};
  const other = Object.keys(STATUS).filter((k) => k !== "not run" && c.n(k)).map((k) => `${c.n(k)} ${STATUS[k]}`)
    .concat(c.rejected ? [`${c.rejected} where the radar failed the quality check`] : []).join("; ");
  const facts = [
    t.lo && t.hi && span(t.lo.farmed_ha, t.hi.farmed_ha) ? `<div><dt>Radar threshold ${t.thr}</dt><dd>${span(t.lo.farmed_ha, t.hi.farmed_ha)} ha</dd></div>` : "",
    t.s2 && ok(t.s2.farmed_ha) ? `<div><dt>Radar + Sentinel-2</dt><dd>${fmt(t.s2.farmed_ha)} ha</dd></div>` : "",
  ].join("");
  const cov = obj(s.coverage);
  let covTxt = "";
  if (cov) {
    const P = obj(cov.processed), RR = obj(cov.radar_results), B = obj(cov.both_seasons), W = obj(cov.winter_classified), Su = obj(cov.summer_classified), F = obj(cov.fields);
    const parts = [];
    if (P && ok(P.share)) parts.push(`the ${fmt(P.boxes)} processed regions hold ~${pct(P.share)} of the ESA WorldCover cropland and tree cover in the ${fmt(cov.boxes)} region boxes`);
    if (RR && ok(RR.share)) parts.push(`the ${fmt(RR.boxes)} with radar results hold ~${pct(RR.share)}${B && ok(B.share) ? ` (both seasons: ${fmt(B.boxes)} regions, ~${pct(B.share)}${W && Su && ok(W.share) && ok(Su.share) ? `; winter ${pct(W.share)}, summer ${pct(Su.share)}` : ""})` : ""}`);
    if (parts.length) covTxt = `<p class="note"><b>Coverage:</b> ${parts.join(", and ")}.${F && ok(F.one_season_or_more_share) && ok(F.both_seasons_share) ? ` By field area, the radar classifies at least one season on ${pct(F.one_season_or_more_share)} of the mapped fields and both seasons on ${pct(F.both_seasons_share)}.` : ""}</p>`;
  }
  const allK = Object.keys(CODE).filter((k) => ok(a[k]) && a[k] > 0), mx = Math.max(1, ...allK.map((k) => a[k]));
  const bar = (k) => `<div class="bar-row"><div class="bar-head">${swatch(CODE[k])}<span>${NAME[k]}</span><span class="num">${fmt(a[k])} ha</span></div><div class="bar-fill" style="--c:${COL[CODE[k]]};width:${(100 * a[k] / mx).toFixed(1)}%"></div></div>`;
  const fRows = FARMED.filter((k) => allK.includes(k)), oRows = allK.filter((k) => !FARMED.includes(k));
  const wfIdle = get(s, "s2_filled.fills.winter_fill.by_radar_class.idle");
  const ph = obj(s.pumping_head);
  const sw = "in the southwest the threshold fails on rocky ground, and some mapped patches there are rain-greened natural vegetation";
  const seasons = ["winter", "summer"].filter((k) => obj(v[k]) && v[k].agreement != null);
  const capTxt = [`<b>Low / Central / High</b> set every factor to its low, central or high bound at once (<a href="#method">Method tab</a>).`,
    `Under each figure: the factor range (those bounds)` + (t.lo && t.hi ? `, the range with the radar's farmed / not-farmed threshold moved ${t.thr} in every region at this estimate` : "") +
    (t.corners ? `, and both at once` : "") + `; none is a probability interval.`,
    `The map, Official stats and the Biochar headline use central values.`].join(" ");
  el.innerHTML = `<p class="lead">Radar finds <b>${fmt(farmed)} ha</b> farmed in 2025/26 (winter ${fmt(act.winter)} ha, summer ${fmt(act.summer)} ha) out of ${fmt(s.field_ha)} ha of fields mapped from Sentinel-2${c.all ? `, in the ${fmt(c.tried)} largest of ${fmt(c.all)} farming regions (${fmt(c.withRadar)} with radar results${other ? "; " + other : ""})` : ""}.</p>
    ${facts ? `<dl class="facts ov-facts">${facts}</dl>` : ""}
    <div class="estimate"><span class="est-label" id="est-ov">Estimate</span>${levelSeg("est-ov")}</div>
    <p class="note est-cap">${capTxt}</p>
    <div class="kpis">
      ${kpi("Irrigation water pumped", "billion m³ / year", "water_m3", 1e9, 2)}
      ${kpi("Pumping electricity", "TWh / year", "elec_kwh", 1e9, 2)}
      ${kpi("Summer pumping load", "MW average, Jun–Sep", "summer_pumping_avg_mw", 1, 0)}
      ${kpi("Pumping CO₂ (grid)", "Mt CO₂e / year", "co2_t_grid", 1e6, 2)}
      ${kpi("Wheat straw (radar)", "kt dry / year", "straw_t_dry", 1e3, 0)}
      ${kpi("Palm fronds (radar + WorldCover)", "kt dry / year", "fronds_t_dry", 1e3, 0)}
    </div>
    ${energyCallout()}
    ${covTxt}
    <p class="note"><a href="scenarios.html#floor">Scenarios</a> shows this record with the southwest set apart (the radar floor), Monte Carlo ranges and what-ifs.</p>
    ${s2Block()}
    <h3>Field classes (radar)</h3>
    ${fRows.length ? `<div class="bar-group">Farmed (in the total)</div>${fRows.map(bar).join("")}` : ""}
    ${oRows.length ? `<div class="bar-group sep">Not in the total</div>${oRows.map(bar).join("")}` : ""}
    <p class="note">"Not detected by radar": green in Sentinel-2 at some point in 2025/26 but below the radar threshold in every season observed. Most are fields the radar missed (winter dates come before the canopy; the threshold is conservative), not idle land${ok(wfIdle) ? `: Sentinel-2 sees ${fmt(wfIdle)} ha of them green in winter and not in summer, which the radar + Sentinel-2 tier counts as winter crops` : ""}${s.quality_check ? "" : `; ${sw}`}. "One season observed": the radar had no usable look at the field in the other season (no pass then, the pass missed the field, or that season failed the quality check); winter is unknown on ${fmt(nob.winter)} ha and summer on ${fmt(nob.summer)} ha of these fields.${s.quality_check ? ` "Radar not usable": the quality check rejected every season the radar had in the region (${esc(s.quality_check_rule)}); ${sw}.` : ""}</p>
    <h3>Radar vs Sentinel-2 (pooled over regions)</h3>
    ${seasons.length ? seasons.map((k) => `<p><b>${cap(k)}</b> (${fmt(v[k].regions)} regions, ${fmt(v[k].validated_ha)} ha): agreement ${pct(v[k].agreement)} against ${pct(v[k].chance_agreement)} by chance, kappa <b>${fmt(v[k].kappa, 2)}</b>. Of the area Sentinel-2 saw green, radar found <b>${pct(v[k].recall)}</b>; of the area radar called farmed, <b>${pct(v[k].precision)}</b> was green in Sentinel-2.</p>`).join("") : "<p>No pooled validation in this export.</p>"}
    <p class="note">Winter is checked against Sentinel-2 over the radar's own winter dates (late November to January); summer against Sentinel-2 for June–October.${s.quality_check ? ` Quality check applied: ${esc(s.quality_check_rule)}.` : ""} The radar threshold needs no training labels: each region's comes from its own bare desert on the same dates. Field outlines, the wheat/fodder split (spring check) and palm groves use Sentinel-2 and ESA WorldCover, so these checks against Sentinel-2 test consistency, not an independent ground truth. Water, energy and straw are likely underestimates: fields the radar did not detect, and seasons it did not observe, get none (radar false alarms and the derived summer-crop depth push the other way). ${ph && ph.rule ? `Pumping ${esc(ph.rule)}; pumping energy is not estimated` : "Pumping energy uses regional depth to water (no drawdown) and is not estimated"} for the Arabian Shield regions (Makkah, Madinah, Asir, Jazan, Najran, Al-Baha).</p>
    ${reproBlock()}`;
}

/* ====================================================================================================
   Why it matters (lenses)
   ==================================================================================================== */
function renderLenses() {
  const el = $("lens");
  if (!el) return;
  const s = SUM(), L_ = S.level, a = obj(s.area_ha_by_class) || {}, o = obj(s.vs_official) || {}, t = tiers();
  const off = arr(D().official).filter(obj), m = obj(D().mwan) || {}, fh = obj(D().fodder_halt);
  const lv = (key, div, d) => { const x = get(s, `${key}.${L_}`); return ok(x) ? fmt(x / div, d) : "–"; };
  const items = [];

  // Groundwater
  const w = obj(s.water_m3), mewa = o.mewa_agri_groundwater_m3, corn = t.corners && obj(t.corners.water_m3);
  let mewaTxt = ok(mewa) ? `MEWA's official estimate for all farms: ${fmt(mewa / 1e9, 2)} bn m³` : "";
  if (ok(mewa) && w && ok(w.low) && ok(w.high)) {
    const where = (lo, hi) => mewa < lo ? "below" : mewa > hi ? "above" : "inside";
    const f1 = where(w.low, w.high), f2 = corn && ok(corn.low) && ok(corn.high) ? where(corn.low, corn.high) : null;
    mewaTxt += `, ${f1} the factor range` + (f2 ? (f2 === f1 ? ` and ${f2} the range with the threshold moved as well` : ` but ${f2} the range with the threshold moved as well`) : "");
  }
  items.push(["Groundwater accounting", `${lv("water_m3", 1e9, 2)} bn m³/y pumped for the mapped fields the radar saw farmed, likely an underestimate${mewaTxt ? ` (${mewaTxt})` : ""}.${t.s2 && ok(get(t.s2, `water_m3.${L_}`)) ? ` With Sentinel-2 filling the winters and seasons the radar missed (radar + Sentinel-2 tier): ${fmt(t.s2.water_m3[L_] / 1e9, 2)} bn m³.` : ""} Field by field from the radar dates of each season; NISAR revisits every 12 days, so the record can be updated as passes arrive.`]);

  // Grid planning
  items.push(["Grid planning", `Irrigation pumping averages ~${lv("summer_pumping_avg_mw", 1, 0)} MW through June–September, on top of the air-conditioning peak; ${lv("elec_kwh", 1e9, 2)} TWh a year in total. Likely a lower bound: no pumping energy for the Arabian Shield regions, and depths to water from older measurements (<a href="#method">Method tab</a>).`]);

  // Food security
  const wheat = ok(s.wheat_ha) ? s.wheat_ha : (ok(a.winter_only) || ok(a.wheat_rotation) ? (a.winter_only || 0) + (a.wheat_rotation || 0) : null);
  const over = arr(get(s, "s2_filled.vs_official.overshoots")).filter((x) => obj(x) && x.tier === "radar_plus_s2_seasons" && x.metric === "wheat_ha");
  items.push(["Food security", `${fmt(wheat)} ha of wheat-pattern fields${ok(o.gastat_wheat_ha) ? `, against GASTAT's ${fmt(o.gastat_wheat_ha)} ha of wheat in 2024` : ""}: an independent check, and a lower bound. The radar's winter dates come before the wheat peak, most of the Eastern Province had no winter pass, and boxes that failed the quality check or were not processed are missing. Both wheat classes need radar activity on the early-winter dates; summer radar and the late-spring Sentinel-2 brown-down only split winter-only fields from rotations.${t.s2 && ok(t.s2.wheat_ha) ? ` The radar + Sentinel-2 tier finds ${fmt(t.s2.wheat_ha)} ha of wheat-pattern fields${over.length ? `, above GASTAT's whole-region figure in ${list(over.map((x) => x.region === "Eastern" ? "the Eastern Province" : esc(x.region)))}, so straw on wheat that only Sentinel-2 sees is capped at GASTAT's wheat area` : ""}.` : ""}`]);

  // Fields to check
  const wfIdle = get(s, "s2_filled.fills.winter_fill.by_radar_class.idle");
  items.push(["Fields to check", `${fmt(a.idle || 0)} ha of mapped fields were green in Sentinel-2 this year but not detected by radar in either season. Most are radar misses rather than idle land, so this is a list for ground checks, not yet for land restoration; they get no water in the totals.${ok(wfIdle) ? ` Sentinel-2 sees ${fmt(wfIdle)} ha of them green in winter and not in summer.` : ""}`]);

  // Fodder policy
  if (fh && Array.isArray(fh.regions) && fh.regions.length) {
    const inHalt = off.filter((r) => fh.regions.includes(r.region));
    const sum = (rows, k) => rows.reduce((tt, r) => tt + (ok(r[k]) ? r[k] : 0), 0);
    const yr = sum(inHalt, "radar_year_round_ha"), part = sum(inHalt, "radar_partly_seen_ha"), gf = sum(inHalt, "gastat_fodder_ha");
    const s2r = arr(get(s, "s2_filled.vs_official.regions")).filter((r) => obj(r) && fh.regions.includes(r.region));
    const s2yr = s2r.length ? sum(s2r, "seasons_year_round_ha") : null;
    const act = a.partly_seen_active;
    const e = effDate(fh.effective), names = list(fh.regions.map((r) => r === "Eastern" ? "the Eastern Province" : esc(r)));
    const lead = !e ? `MEWA is halting perennial fodder cultivation in ${names}` : e.past ? `MEWA has halted perennial fodder cultivation since ${e.txt} in ${names}` : `MEWA halts perennial fodder cultivation from ${e.txt} in ${names}`;
    const link = /^https?:\/\//.test(fh.url || "") ? ` (<a href="${esc(fh.url)}" rel="noopener">MEWA announcement</a>)` : "";
    items.push(["Fodder policy", `${lead}${link}. In those regions the radar's 2025/26 record holds ${fmt(yr)} ha of year-round fields, a field-level baseline before the rule${gf ? `, against GASTAT's ${fmt(gf)} ha of fodder there in 2024 (perennial and seasonal)` : ""}${ok(s2yr) ? `; the radar + Sentinel-2 tier finds ${fmt(s2yr)} ha` : ""}. The radar saw another ${fmt(part)} ha in one season only; of these, only fields farmed in the season it saw could be perennial fodder that it cannot tell from a seasonal crop${ok(act) ? ` (${fmt(act)} ha of such fields nationally)` : ""}. NISAR passes from summer 2027 can show which of them switch to seasonal crops. <a href="scenarios.html#fodder">The baseline, field by field, in Scenarios</a>.`]);
  }

  // Waste inventory (mwan.streams_source: the KAPSARC DP64 authors' 2030 estimates from MWAN 2023 data, back-cast to 2024)
  const st = obj(m.streams_2024_mt) || {};
  items.push(["Waste inventory audit", `MWAN's national waste inventory puts agricultural waste at ${ok(m.agri_total_kt) ? fmt(m.agri_total_kt / 1e3, 2) : "–"} Mt a year (${esc(m.agri_total_year || "–")}), graded ${m.confidence ? `"${esc(m.confidence)}" confidence${m.confidence_legend ? ` (${esc(m.confidence_legend)})` : ""}` : "low confidence because it rests on international benchmark factors"}. The radar gives a partial, field-level check: ${lv("straw_t_dry", 1e3, 0)} kt of baled wheat straw and ${lv("fronds_t_dry", 1e3, 0)} kt of palm fronds a year (dry) on the fields it maps, against ${m.streams_source ? "KAPSARC DP64's estimates from MWAN data (its authors' 2030 figures from MWAN's 2023 data, back-cast here to 2024; not MWAN's own) of " : "MWAN's "}${fmt(st.grain_residue, 2)} Mt of grain residue and ${fmt(st.date_palm, 2)} Mt of date palm residue; stream by stream in the <a href="#biochar">Biochar tab</a>.`]);

  // Carbon removal
  const c = obj(get(D(), `siting.central_${S.size}kt`)), lo = obj(get(D(), `siting.low_${S.size}kt`)), hi = obj(get(D(), `siting.high_${S.size}kt`));
  const cr = c && lo && hi ? span(lo.net_removal_tco2, hi.net_removal_tco2, 1e6, 2) : null;
  const litOut = c && !(get(c, "credited_by_feed_tco2.litter") > 0);
  items.push(["Carbon removal deployment", `Where biochar plants can be filled, how big, which outlet, and how much CO₂ they remove net of transport (<a href="#biochar">Biochar tab</a>).${c && c.credited !== false && ok(c.net_removal_tco2) ? ` With ${S.size} kt/y plants: ${fmt(c.plants)} plants, ${fmt(c.net_removal_tco2 / 1e6, 2)} Mt CO₂ a year net of transport${cr ? ` (all-low / all-high corners ${cr})` : ""}, a technical potential${litOut ? " with poultry litter left out" : ""}.` : ""}`]);

  items.push(["Next", "Loan and insurance checks that a field was planted; carbon-credit feedstock verification; ground sinking from radar interferometry; alerts when a circle switches on or off."]);
  el.innerHTML = `<p class="lead">One radar record, many decisions:</p>
    <div class="estimate"><span class="est-label" id="est-lens">Estimate</span>${levelSeg("est-lens")}</div>
    <p class="note est-cap">The water, energy and residue figures below follow the estimate (every factor at its low, central or high bound; <a href="#method">Method tab</a>).</p>` +
    items.map(([h, txt]) => `<div class="plant"><b>${h}</b><br>${txt}</div>`).join("");
}

/* ====================================================================================================
   Official stats
   ==================================================================================================== */
function renderOfficial() {
  const el = $("off");
  if (!el) return;
  const s = SUM(), o = arr(D().official).filter(obj), vs = obj(s.vs_official) || {}, a = obj(s.area_ha_by_class) || {}, P = PAR();
  const n0 = (x) => ok(x) ? x : 0;
  const rows = o.map((r) => `<tr><td>${esc(r.region)}</td>
    <td class="num">${fmt(r.radar_wheat_ha)}</td><td class="num">${fmt(r.gastat_wheat_ha)}</td>
    <td class="num">${fmt(r.radar_year_round_ha)}</td><td class="num">${fmt(r.gastat_fodder_ha)}</td>
    <td class="num">${ok(r.palms_est_low) ? `${fmt(r.palms_est_low / 1e6, 1)}–${fmt(r.palms_est_high / 1e6, 1)}` : "–"}</td><td class="num">${ok(r.gastat_palms) ? fmt(r.gastat_palms / 1e6, 1) : "–"}</td>
    <td class="num">${ok(r.water_m3_central) ? fmt(r.water_m3_central / 1e9, 2) : "–"}</td><td class="num">${ok(r.mewa_agri_groundwater_m3) ? fmt(r.mewa_agri_groundwater_m3 / 1e9, 2) : "–"}</td>
    <td class="num">${fmt(r.radar_partly_seen_ha)}</td><td class="num">${fmt(r.radar_unusable_ha)}</td></tr>`).join("");
  // National row: radar columns from the summary's own class totals, so every tab shows the same figure
  const has = (k) => ok(a[k]);
  const nat = {
    wheat: ok(s.wheat_ha) ? s.wheat_ha : has("winter_only") ? n0(a.winter_only) + n0(a.wheat_rotation) : vs.radar_wheat_ha,
    yr: ok(s.year_round_ha) ? s.year_round_ha : has("year_round") ? a.year_round : vs.radar_year_round_ha,
    part: has("partly_seen_active") || has("partly_seen_inactive") ? n0(a.partly_seen_active) + n0(a.partly_seen_inactive) : o.reduce((t, r) => t + n0(r.radar_partly_seen_ha), 0),
    unus: has("radar_unusable") ? a.radar_unusable : o.reduce((t, r) => t + n0(r.radar_unusable_ha), 0),
  };
  const sumRows = (k) => o.reduce((t, r) => t + n0(r[k]), 0);
  const rounding = Math.abs(sumRows("radar_wheat_ha") - n0(nat.wheat)) + Math.abs(sumRows("radar_year_round_ha") - n0(nat.yr)) +
    Math.abs(sumRows("radar_partly_seen_ha") - n0(nat.part)) + Math.abs(sumRows("radar_unusable_ha") - n0(nat.unus)) > 0;
  const water = Array.isArray(vs.water_m3) ? vs.water_m3[1] : get(s, "water_m3.central");
  const pal = Array.isArray(vs.palms_est) ? `${fmt(vs.palms_est[0] / 1e6, 1)}–${fmt(vs.palms_est[1] / 1e6, 1)}` : "–";
  const pph = obj(P.palms_per_ha);
  const src = obj(D().official_sources) || {};
  const sources = src.G24 || src.M24 ? `Sources: ${[src.G24, src.M24].filter(Boolean).map(linkify).join("; ")}.`
    : "Sources: GASTAT Agricultural Statistics 2024 (wheat, fodder, date palms by region); MEWA Statistical Book 2024 pp.62–63 (agricultural groundwater use by region).";
  // the radar + Sentinel-2 tier against the same figures
  const tr = arr(get(s, "s2_filled.vs_official.regions")).filter(obj), ov = arr(get(s, "s2_filled.vs_official.overshoots")).filter((x) => obj(x) && x.tier === "radar_plus_s2_seasons");
  const MET = { wheat_ha: "wheat", year_round_ha: "year-round (fodder)", water_m3_central: "water (central)" };
  const tierBlock = tr.length ? `<details class="more"><summary>The radar + Sentinel-2 tier against the same figures</summary>
      <table class="off"><tr><th>Region</th><th class="num">Wheat ha (radar + S2)</th><th class="num">GASTAT wheat ha</th><th class="num">Year-round ha (radar + S2)</th><th class="num">GASTAT fodder ha</th><th class="num">Water bn m³ (radar + S2, central)</th><th class="num">MEWA farm groundwater bn m³</th></tr>
      ${tr.map((r) => `<tr><td>${esc(r.region)}</td><td class="num">${fmt(r.seasons_wheat_ha)}</td><td class="num">${fmt(r.gastat_wheat_ha)}</td><td class="num">${fmt(r.seasons_year_round_ha)}</td><td class="num">${fmt(r.gastat_fodder_ha)}</td><td class="num">${Array.isArray(r.seasons_water_m3) ? fmt(r.seasons_water_m3[1] / 1e9, 2) : "–"}</td><td class="num">${ok(r.mewa_agri_groundwater_m3) ? fmt(r.mewa_agri_groundwater_m3 / 1e9, 2) : "–"}</td></tr>`).join("")}</table>
      <p>${ov.length ? `Above the official whole-region figure, although the boxes cover only part of each region's farmland: ${ov.map((x) => `${esc(x.region)} ${MET[x.metric] || esc(x.metric)} ${ok(x.ratio) ? fmt(x.ratio, 2) + "×" : ""}`).join("; ")}. ` : ""}Wheat here is the uncapped wheat pattern; straw on Sentinel-2-filled wheat is capped at GASTAT's area. Sentinel-2 adds area the radar did not measure, so this tier is context, not a radar result.</p></details>` : "";
  el.innerHTML = `<p class="lead">How do the radar estimates compare with official 2024 statistics, region by region?</p>
    <table class="off"><tr><th>Region</th><th class="num">Radar wheat ha</th><th class="num">GASTAT wheat ha</th><th class="num">Radar year-round ha</th><th class="num">GASTAT fodder ha</th>
    <th class="num">Palms est. (M)</th><th class="num">GASTAT palms (M)</th><th class="num">Water est. (bn m³, central)</th><th class="num">MEWA farm groundwater (bn m³)</th><th class="num">One season observed ha</th><th class="num">Radar not usable ha</th></tr>${rows}
    <tr class="total"><th>National</th><th class="num">${fmt(nat.wheat)}</th><th class="num">${fmt(vs.gastat_wheat_ha)}</th><th class="num">${fmt(nat.yr)}</th><th class="num">${fmt(vs.gastat_fodder_ha)}</th>
    <th class="num">${pal}</th><th class="num">${ok(vs.gastat_palms) ? fmt(vs.gastat_palms / 1e6, 1) : "–"}</th>
    <th class="num">${ok(water) ? fmt(water / 1e9, 2) : "–"}</th><th class="num">${ok(vs.mewa_agri_groundwater_m3) ? fmt(vs.mewa_agri_groundwater_m3 / 1e9, 2) : "–"}</th><th class="num">${fmt(nat.part)}</th><th class="num">${fmt(nat.unus)}</th></tr></table>
    <p class="note">${sources} Radar covers only the mapped fields in the boxes processed, while official figures are whole-region totals${o.some((r) => r.fields === 0) ? ` (regions with no mapped fields show radar zeros)` : ""}. Radar classes are not crop types: "wheat" = farmed in winter only, or in winter and summer but brown in late spring (harvest, from Sentinel-2); "year-round" (green through spring) approximates perennial fodder. Radar's winter dates end in December or January, before the wheat peak, so winter area is a lower bound; where a region had no winter pass ("one season observed"), radar cannot split wheat from fodder at all. Palm count = radar palm-grove area × ${pph && ok(pph.low) && ok(pph.high) ? `${fmt(pph.low)}–${fmt(pph.high)}` : "100–270"} palms/ha; nationally the radar groves capture only part of the Kingdom's palms, but in some regions they include other orchards (olives in Al-Jouf, fruit orchards in Jazan), where the estimate can exceed the official count.${rounding ? " Region rows are rounded separately, so their radar columns can differ from the National row by a hectare." : ""}</p>
    ${tierBlock}`;
}

/* ====================================================================================================
   Biochar
   ==================================================================================================== */
function renderBiochar() {
  const el = $("bio");
  if (!el) return;
  const st = obj(D().siting) || {}, z = S.size, T = (k) => obj(st[k]), P = PAR(), s = SUM();
  const cred = (x) => !!x && x.credited !== false && ok(x.net_removal_tco2);
  const c = T(`central_${z}kt`), r = T(`central_radar_${z}kt`), b = T(`central_boxes_${z}kt`), s2 = T(`central_radar_s2_${z}kt`);
  const lo = T(`low_${z}kt`), hi = T(`high_${z}kt`), rlo = T(`low_radar_${z}kt`), rhi = T(`high_radar_${z}kt`);
  const upOf = (tag) => Object.keys(st).map((k) => obj(st[k])).find((x) => x && x.credited === false && x.upside_of === tag);
  const up = upOf(`central_${z}kt`), upb = upOf(`central_boxes_${z}kt`);
  // plant sizes (kt/y) at which a kind of run exists: from size_t, else from the tag's _<n>kt ending
  const sizesOf = (pred) => [...new Set(Object.keys(st).filter((k) => obj(st[k]) && pred(st[k]))
    .map((k) => ok(st[k].size_t) ? st[k].size_t / 1000 : Number((String(k).match(/_(\d+)kt$/) || [])[1])).filter(ok))].sort((a, b) => a - b);
  const upSizes = sizesOf((x) => x.credited === false && /^central_\d+kt$/.test(String(x.upside_of || "")));
  const s2Sizes = sizesOf((x) => x.residue_tier === "radar_s2" && x.credited !== false && (x.level == null || x.level === "central"));
  let sc = obj(get(S.sc, "scenarios.C1_F3"));
  if (sc && (ok(sc.plant_size_t) ? sc.plant_size_t !== z * 1000 : z !== 50)) sc = null;
  if (sc && (sc.credited === false || sc.upside_of)) sc = null;   // an uncredited upside is never shown as a credited result
  const mt = (x) => ok(x) ? fmt(x / 1e6, 2) : "–";
  const corners = (a1, b1) => cred(a1) && cred(b1) ? span(a1.net_removal_tco2, b1.net_removal_tco2, 1e6, 2) : null;
  const plantsTxt = (x) => ok(x.plants) ? `${fmt(x.plants)} plants${ok(x.distinct_sites) && x.distinct_sites < x.plants ? ` on ${fmt(x.distinct_sites)} sites` : ""}` : "";
  const creditedFeeds = (x) => { const cb = obj(x && x.credited_by_feed_tco2); return cb ? Object.keys(cb).filter((f) => ok(cb[f]) && cb[f] > 0) : (Array.isArray(x && x.feeds) ? x.feeds : null); };
  const litterIn = (x) => { const fs = creditedFeeds(x); return fs ? fs.includes("litter") : !!(x && x.feeds === "all"); };
  const extra = (x) => { const fs = creditedFeeds(x); const e = fs ? fs.filter((f) => f !== "straw" && f !== "fronds") : null; return e && e.length ? list(e.map((f) => FEED[f] || esc(f))) : "manure and litter"; };
  const ct = counts(), html = [];

  // Lead: the case on the map (all credited feeds)
  if (c) {
    const cr = corners(lo, hi), fu = obj(c.feed_used_by_feed_t), unc = obj(c.uncredited_supply_by_feed_t) || {};
    const radarShare = fu && ok(c.feed_used_t) && c.feed_used_t > 0 ? ((fu.straw || 0) + (fu.fronds || 0)) / c.feed_used_t : null;
    const share = radarShare == null ? "" : radarShare < 0.01 ? fmt(100 * radarShare, 1) + "%" : pct(radarShare);
    const tierTxt = c.residue_tier === "radar_s2" ? "from the radar + Sentinel-2 record, not radar-measured" : "radar-measured";
    html.push(`<p class="lead"><span class="big">${fmt(c.plants)}</span> plants of ${z} kt/y${ok(c.distinct_sites) && c.distinct_sites < c.plants ? ` on ${fmt(c.distinct_sites)} sites` : ""} could be filled within ${fmt(c.radius_km)} km, using <b>${mt(c.feed_used_t)} Mt</b> of ${mt(c.supply_t)} Mt of dry residue that can be credited, removing <b>${mt(c.net_removal_tco2)} Mt CO₂ a year</b> net of transport${cr ? ` (all-low / all-high corners ${cr} Mt)` : ""}${c.capped ? " (the run stopped at its plant cap)" : ""}.</p>`);
    // the litter upside runs exist only at some sizes: say "below" only when one is listed below
    html.push(`<p>${share ? `<b>${share}</b> of that feed is ${tierTxt} (wheat straw, palm fronds); the rest is modelled ${litterIn(c) ? "manure and litter" : "manure"}. ` : ""}${litterIn(c)
      ? `These figures still credit poultry litter, whose char may fail Puro's H/C<sub>org</sub> eligibility gate on the organic-carbon basis.`
      : `Poultry litter${ok(unc.litter) && unc.litter > 0 ? ` (${mt(unc.litter)} Mt dry a year in this coverage)` : ""} is not credited: its char fails Puro's H/C<sub>org</sub> eligibility gate on the organic-carbon basis (rule 3.5.1), ${up && ok(up.net_removal_tco2) ? "so it appears below only as a hypothetical upper bound" : upSizes.length ? `and its hypothetical upper bound is computed at ${list(upSizes.map((x) => x + " kt/y"))} only` : "and no hypothetical upper bound is published in this export"}.`}</p>`);
    // the siting corners hold road circuity and the truck factor at central (their basis says so, and overrides pins them)
    const held = [lo, hi].some((x) => x && (/held at central/i.test(String(x.basis || "")) || (obj(x.overrides) && ("road_circuity" in x.overrides || "truck_kgco2e_per_tkm" in x.overrides))));
    const cornerTxt = held ? "The corners set the supply, char-yield and char-carbon, H/C and soil-temperature factors to their least or most favourable values at once, with road circuity and the truck emission factor held at central, so they bracket removal; they are not probability intervals."
      : "The corners set every factor to its least or most favourable value at once; they are not probability intervals.";
    html.push(`<p class="note">This is a technical potential: stored char carbon × the Puro.earth 2025 soil persistence model (used for cement too, rule 6.2.4), net of transport (truck emissions) only; production and embodied emissions and leakage are not subtracted, and farmland's capacity to absorb char is not limited (soil and cement outlets take all the char offered, which the scenarios page calls the gross case).${cr ? " " + cornerTxt : ""}</p>`);
  } else {
    const stale = obj(get(D(), "siting_check.stale")), nStale = stale ? Object.keys(stale).length : 0;
    html.push(`<p class="lead">No national siting is published in this data export${nStale ? `: the ${fmt(nStale)} siting runs on file were written before the current inputs, so the export left them out` : ""}. The supply, soil-use status and waste-inventory comparison below do not depend on it; constrained cases are on the <a href="scenarios.html#biochar">scenarios page</a>.</p>`);
  }

  // Cases at this size
  const caseLi = (label, value, meta, cls) => `<li class="case${cls ? " " + cls : ""}"><div class="case-head"><span class="case-label">${label}</span><span class="case-value">${value}</span></div>${meta.filter(Boolean).map((x) => `<div class="case-meta">${x}</div>`).join("")}</li>`;
  const items = [], upItems = [];   // upItems: the uncredited upside, listed apart and never among the credited cases
  if (cred(r)) { const rc = corners(rlo, rhi); items.push(caseLi("Radar-measured wheat straw and palm fronds only", mt(r.net_removal_tco2), [[plantsTxt(r), rc ? `corners ${rc}` : ""].filter(Boolean).join(" · ")])); }
  if (cred(s2)) items.push(caseLi("Straw and fronds from the radar + Sentinel-2 record", mt(s2.net_removal_tco2), [plantsTxt(s2),
    "Sentinel-2 adds winter crops the radar missed and seasons it did not observe, and counts fields with no usable radar season as farmed (an upper value; straw capped at GASTAT's wheat area, fronds not); not radar-measured"]));
  if (cred(b)) items.push(caseLi(`Adding modelled ${extra(b)} inside the ${ct.tried ? fmt(ct.tried) + " " : ""}processed regions only`, mt(b.net_removal_tco2), [plantsTxt(b), "every stream on the radar's coverage"]));
  if (cred(c)) {
    // plants_outside_boxes counts plants by where their site lies; feed_outside_boxes_t by where the feed lies
    const outTxt = ok(c.plants_outside_boxes) && ok(c.feed_outside_boxes_t) && ok(c.feed_used_t) && c.feed_used_t > 0
      ? `${fmt(c.plants_outside_boxes)} of the plants are sited outside the processed regions (a plant just outside can still draw its feed from inside), and ${pct(c.feed_outside_boxes_t / c.feed_used_t)} of the feed comes from outside them` : "";
    items.push(caseLi(`Adding modelled ${extra(c)} for the whole Kingdom <span class="tag">On the map</span>`, mt(c.net_removal_tco2), [[plantsTxt(c), corners(lo, hi) ? `corners ${corners(lo, hi)}` : ""].filter(Boolean).join(" · "), outTxt], "headline"));
  }
  if (up && ok(up.net_removal_tco2)) {   // as on the scenarios page: own list, value in brackets, labelled hypothetical
    const inc = cred(c) ? up.net_removal_tco2 - c.net_removal_tco2 : null;
    upItems.push(caseLi("With poultry litter, if its char passed the gate", `<span class="hyp">(${mt(up.net_removal_tco2)})</span><span class="hyp-l">hypothetical</span>`,
      [[ok(inc) ? `a hypothetical upper bound: ${inc >= 0 ? "+" : "−"}${mt(Math.abs(inc))} Mt over the case on the map` : "a hypothetical upper bound", plantsTxt(up)].filter(Boolean).join(" · "),
        upb && ok(upb.net_removal_tco2) ? `inside the processed regions only: ${mt(upb.net_removal_tco2)} Mt, also hypothetical${plantsTxt(upb) ? ` (${plantsTxt(upb)})` : ""}` : ""], "upside"));
  }
  if (sc && ok(sc.credited_tco2)) {
    const lit = ok(get(sc, "feed_used_by_feed_t.litter")) && sc.feed_used_by_feed_t.litter > 0;
    items.push(caseLi(`Outlets limited: farmland and cement take only limited char${lit ? " (includes poultry litter)" : ""}`, mt(sc.credited_tco2), [[ok(sc.plants) ? `${fmt(sc.plants)} plants` : "", `<a href="scenarios.html#biochar">details in Scenarios</a>`].filter(Boolean).join(" · ")]));
  }
  if (items.length || upItems.length) {
    // runs made at other sizes only: say where they are
    const kts = (xs) => list(xs.map((x) => fmt(x))) + " kt/y";
    const absent = [!cred(s2) && s2Sizes.length ? ["radar + Sentinel-2", s2Sizes] : null, !(up && ok(up.net_removal_tco2)) && upSizes.length ? ["litter-upside", upSizes] : null].filter(Boolean);
    const onlyTxt = !absent.length ? "" : absent.length === 2 && kts(absent[0][1]) === kts(absent[1][1])
      ? ` The ${absent[0][0]} and ${absent[1][0]} runs were made at ${kts(absent[0][1])} only.`
      : " " + absent.map(([n, xs]) => `The ${n} ${n === "litter-upside" ? "runs were" : "run was"} made at ${kts(xs)} only.`).join(" ");
    const basis = [["Radar-measured", r], ["Radar + Sentinel-2", s2], ["Inside the processed regions", b], ["Whole Kingdom (on the map)", c], ["All-low corner", lo], ["All-high corner", hi],
      ["Radar-measured, all-low corner", rlo], ["Radar-measured, all-high corner", rhi], ["Litter upside", up], ["Litter upside inside the processed regions", upb]].filter(([, x]) => x && x.basis);
    html.push(`<h3>Cases at ${z} kt/y <span class="h-sub">Mt CO₂ a year, net of transport</span></h3>${items.length ? `<ul class="cases">${items.join("")}</ul>` : ""}${upItems.length ? `<p class="cases-sub">Not credited: a hypothetical upper bound, kept out of the cases above</p><ul class="cases cases-up">${upItems.join("")}</ul>` : ""}
      <p class="note">Separate runs, not a range.${onlyTxt}</p>
      ${basis.length ? `<details class="more"><summary>What each case includes</summary>${basis.map(([h, x]) => `<p><b>${h}:</b> ${esc(caseText(x.basis))}</p>`).join("")}</details>` : ""}`);
  }

  // Residue supply (central, dry)
  const sup = obj(c && c.supply_by_feed_t) || {}, unc = obj(c && c.uncredited_supply_by_feed_t) || {}, ra = obj(D().residue_audit) || {};
  const fallback = { straw: get(s, "straw_t_dry.central"), fronds: get(s, "fronds_t_dry.central"), litter: ra.litter_app_t, manure: ra.manure_app_t };
  const amount = (f) => ok(sup[f]) ? sup[f] : ok(unc[f]) ? unc[f] : fallback[f];
  const hc = (f) => pv(`h_c_org_${f}`);
  const credTxt = (f) => {
    if (c) return ok(sup[f]) && sup[f] > 0 ? "yes" : f in unc ? "no: char fails the H/C<sub>org</sub> gate" : "–";
    return ok(hc(f)) ? (hc(f) < 0.7 ? "yes" : "no: char fails the H/C<sub>org</sub> gate") : "–";
  };
  const birds = get(P, "gastat_2024_totals.values.broilers_produced");
  const SUP = [["straw", "Wheat straw", "Radar wheat fields (winter only, and wheat-then-summer rotations) × baled straw per ha"],
    ["fronds", "Palm fronds", "Radar-active palm groves (WorldCover trees) × palms/ha × fronds/palm; radar groves cover only part of the Kingdom's palms"],
    ["manure", "Cattle, sheep, goat manure", "Modelled for the whole Kingdom: FAO GLW4 pattern × GASTAT 2024 herds × total solids per head × collectable share"],
    ["litter", "Poultry litter", `Modelled for the whole Kingdom: GASTAT 2024 broilers produced${ok(birds) ? ` (${fmt(birds / 1e9, 2)} bn)` : ""} × bedded litter per bird, plus laying hens × manure per hen, spread by the FAO GLW4 chicken pattern`]];
  html.push(`<h3>Residue supply (central, dry)</h3><table class="stack"><tr><th>Stream</th><th class="num">kt / year</th><th>Credited</th></tr>
    ${SUP.map(([f, label, how]) => `<tr class="main"><td>${label}</td><td class="num">${ok(amount(f)) ? fmt(amount(f) / 1e3) : "–"}</td><td>${credTxt(f)}</td></tr><tr class="src"><td colspan="3">${how}</td></tr>`).join("")}</table>`);

  // Soil use of each char (params._soil_use)
  const su = obj(P._soil_use);
  if (su) {
    const SU = [["straw", "Wheat straw"], ["fronds", "Palm fronds"], ["cattle_manure", "Cattle manure"], ["sheep_goat_manure", "Sheep and goat manure"], ["litter", "Poultry litter"]];
    const keys = SU.filter(([k]) => obj(su[k])).concat(Object.keys(su).filter((k) => obj(su[k]) && !SU.some(([x]) => x === k)).map((k) => [k, cap(k.replaceAll("_", " "))]));
    html.push(`<h3>Can each char go on farmland?</h3>
      <table><tr><th>Feed</th><th>Soil use (Puro Table 3.3)</th><th>Outlet</th></tr>${keys.map(([k, label]) => `<tr><td>${label}</td><td>${esc(su[k].status || "–")}${su[k].contaminants ? `; contaminants ${esc(su[k].contaminants)}` : ""}</td><td>${esc(su[k].outlet || "–")}</td></tr>`).join("")}</table>
      <p class="note">Status against Puro.earth 2025 Table 3.3 (WBC-Agro limits, rules 3.6.9–3.6.11). Char used in cement or concrete (Table 3.2, BE3) needs only a heavy-metal declaration (WBC-Material; its PAH, PCB and PCDD/F limits still apply) and is credited with the same soil model (rule 6.2.4). The siting applies no contaminant screen: it credits every feed that passes the H/C<sub>org</sub> gate (rule 3.5.1), with the outlet chosen by haul.</p>
      <details class="more"><summary>Evidence for each feed, and Saudi regulation</summary>${keys.map(([k, label]) => su[k].note ? `<p><b>${label}:</b> ${esc(sentence(caseText(su[k].note)))}</p>` : "").join("")}${su.regulation ? `<p><b>Regulation:</b> ${esc(sentence(su.regulation))}</p>` : ""}</details>`);
  }

  html.push(auditTable());

  // Plants of the case on the map
  if (c) {
    const tag = plantTag(z), ret = obj(P.cement_retention);
    const plants = S.plantsTag === tag ? S.plants.filter(obj) : null;
    const pos = new Map();   // site key -> plant numbers
    (plants || []).forEach((p) => { if (ok(p.lat) && ok(p.lon)) { const k = p.lat.toFixed(4) + "," + p.lon.toFixed(4); if (!pos.has(k)) pos.set(k, []); pos.get(k).push(p.plant); } });
    const row = (p) => {
      const f = { straw: p.feed_straw, fronds: p.feed_fronds, litter: p.feed_litter, manure: p.feed_manure };
      const main = Object.entries(f).filter(([, x]) => ok(x)).sort((x, y) => y[1] - x[1])[0];
      const k = ok(p.lat) && ok(p.lon) ? p.lat.toFixed(4) + "," + p.lon.toFixed(4) : null, mates = k && pos.get(k) ? pos.get(k).filter((n) => n !== p.plant) : [];
      return `<tr><td class="num">${esc(p.plant)}</td><td>${ok(p.lat) ? p.lat.toFixed(2) + "°N " + p.lon.toFixed(2) + "°E" : "–"}${p.kind === "cement" && p.name ? ` (${esc(p.name)})` : ""}${mates.length ? `<br><span class="mate">same site as #${mates.map(esc).join(", #")}</span>` : ""}</td><td class="num">${fmt(p.net_removal_tco2)}</td><td>${esc(p.best_outlet)}${p.best_outlet === "cement" ? " · " + fmt(p.cement_km) + " km" : ""}</td><td>${main ? main[0] : "–"}</td></tr>`;
    };
    const head = `<tr><th class="num" title="order placed">#</th><th>Where</th><th class="num">t CO₂/y net of transport</th><th>Outlet</th><th>Main feed</th></tr>`;
    let table = "";
    if (plants == null) table = `<p class="note">${S.plantsFailed ? "The plant list for this case is not in this data export." : "Loading the plant list…"}</p>`;
    else if (plants.length) {
      const first = plants.slice(0, 40), rest = plants.slice(40);
      table = `<table>${head}${first.map(row).join("")}</table>${rest.length ? `<details class="more"><summary>Show the other ${fmt(rest.length)} plants (of ${fmt(plants.length)})</summary><table>${head}${rest.map(row).join("")}</table></details>` : ""}`;
    }
    html.push(`<h3>Plants of the case on the map</h3>
      <p>Char in cement is credited like char in soil (Puro rule 6.2.4), so a plant sends its char to a cement plant only when that is the shorter haul: ${fmt(c.cement_outlet_plants)} of ${fmt(c.plants)} do.${ok(c.cement_retained_tco2) && c.cement_retained_tco2 > 0 ? ` Their char would hold ${mt(c.cement_retained_tco2)} Mt CO₂ a year in concrete over 60–80 years${ret && ok(ret.central) ? ` (at ${fmt(ret.central, 2)} retention, within a ${fmt(ret.low, 2)}–${fmt(ret.high, 2)} envelope; reported, not credited)` : " (reported, not credited)"}.` : ""} Median transport cost ${ok(c.median_transport_share) ? fmt(100 * c.median_transport_share, 1) + "%" : "–"} of the removal. Plants are numbered in the order the greedy siting placed them; several can share one site, which the map draws as one marker.</p>
      ${table}`);
    html.push(persistenceNote(c, up));
  } else {
    html.push(`<p class="note">Camels are not included (no gridded data). Constrained cases (how much char farmland and cement can absorb, which chars cement may take, cement dosage) are on the <a href="scenarios.html#biochar">scenarios page</a>.</p>`);
  }
  el.innerHTML = html.join("");
}
// siting notes name runs by their tags: say which case on this page they are
const caseText = (t) => String(t || "").replace(/\bcentral_boxes_\d+kt\b/g, "the inside-the-processed-regions case").replace(/\bcentral_\d+kt\b/g, "the whole-Kingdom case").replace(/\b(\d+) C\b/g, "$1 °C");
function persistenceNote(c, up) {
  const pe = obj(c.persistence) || {}, upe = obj(up && up.persistence) || {}, P = PAR();
  const hl = obj(P.h_c_org_litter), t30 = pv("soil_temp_c"), hm = pv("h_c_org_manure");
  const cb = obj(c.credited_by_feed_tco2) || {}, litCred = ok(cb.litter) && cb.litter > 0;
  const lvls = hl ? [hl.low, hl.central, hl.high].filter(ok) : [];
  let litter;
  if (litCred || (ok(pe.litter) && pe.litter > 0)) {   // an export that still credits litter
    litter = `, litter ${fmt(pe.litter, 2)}. Litter char's H/C is ${hl && ok(hl.upside) ? fmt(hl.upside, 2) : "0.69"} on total carbon; on the organic-carbon basis Puro's 0.70 eligibility gate uses it is higher, so its eligibility is uncertain${litCred ? ` (litter carries ${fmt(cb.litter / 1e6, 2)} Mt of the credited removal before transport)` : ""}`;
  } else {
    litter = `; poultry litter earns nothing: its char's H/C is ${hl && ok(hl.upside) ? fmt(hl.upside, 2) : "below 0.70"} on total carbon but ${lvls.length ? `about ${fmt(Math.min(...lvls), 2)}–${fmt(Math.max(...lvls), 2)}` : "at or above 0.70"} on the organic-carbon basis Puro's gate uses (strictly below 0.70 required, rule 3.5.1)${ok(upe.litter) ? `; the hypothetical upside gives it a persistence of ${fmt(upe.litter, 2)}` : ""}`;
  }
  return `<p class="note">Persistence follows Puro's soil model (PF = M − a·H/C<sub>org</sub>, 200 years${ok(t30) ? `, ${fmt(t30)} °C soil` : ""}): straw ${fmt(pe.straw, 2)}, fronds ${fmt(pe.fronds, 2)}, manure ${fmt(pe.manure, 2)}${litter}. Manure char's H/C (${ok(hm) ? fmt(hm, 2) : "–"}, an assumed class value) also varies widely across measured chars, so its eligibility is uncertain${ok(cb.manure) ? ` (manure carries ${fmt(cb.manure / 1e6, 2)} Mt of the credited removal before transport)` : ""}. Camels are not included (no gridded data). Plant sizes are scenarios; the ${fmt(c.radius_km)} km haul limit is an assumption. Constrained cases (how much char farmland and cement can absorb, which chars cement may take, cement dosage) are on the <a href="scenarios.html#biochar">scenarios page</a>.</p>`;
}
function auditTable() {
  const a = obj(D().residue_audit), m = obj(D().mwan);
  if (!a || !m) return "";
  const kt = (t) => ok(t) ? fmt(t / 1e3) : "–", st = obj(m.streams_2024_mt) || {}, mt = (v) => fmt(v, 2);
  const est = m.streams_source ? "the estimate" : "MWAN";
  const rows = [
    ["Wheat straw", kt(a.straw_app_t), kt(a.straw_national_t), `${mt(st.grain_residue)} (all grain residue)`, `Radar maps ${fmt(a.radar_wheat_ha)} of GASTAT's ${fmt(a.official_wheat_ha)} ha of wheat; the app counts baled wheat straw only, ${est} all cereal residue`],
    ["Palm fronds", kt(a.fronds_app_t), kt(a.fronds_national_t), mt(st.date_palm), `Radar groves hold a small part of GASTAT's ${ok(a.palms_official) ? fmt(a.palms_official / 1e6, 1) : "–"} M palms; ${est} counts all palm residue`],
    ["Poultry litter", kt(a.litter_app_t), kt(a.litter_app_t), `${mt(st.broiler)} (broilers)`, `${m.streams_source ? "The estimate's" : "MWAN's"} tonnage is of the order of the birds' fresh (wet) droppings, about 4–5 kg per bird; the app counts dry bedded litter and layer manure (supply only: litter is not credited)`],
    ["Manure", kt(a.manure_app_t), `${kt(a.manure_excreted_t)} excreted`, mt(st.manure), `The app keeps the collectable part (about half; grazing animals' manure is not collected); ${m.streams_source ? "the estimate's" : "MWAN's"} basis is not stated`],
  ];
  return `<h3>Against the national waste inventory</h3>
    <table class="stack"><tr><th>Stream</th><th class="num">This app, kt dry (central)</th><th class="num">Same factors, national statistics, kt dry</th><th class="num">${m.streams_source ? "KAPSARC DP64 estimate from MWAN data (2030 figure back-cast to 2024)" : "MWAN-based estimate 2024"}, Mt</th></tr>
      ${rows.map(([n, x1, x2, x3, why]) => `<tr class="main"><td>${n}</td><td class="num">${x1}</td><td class="num">${x2}</td><td class="num">${x3}</td></tr><tr class="src"><td colspan="4">${why}</td></tr>`).join("")}</table>
    <p class="note">Source: ${esc(m.source)}. MWAN puts agricultural waste at ${ok(m.agri_total_kt) ? fmt(m.agri_total_kt / 1e3, 2) : "–"} Mt (${esc(m.agri_total_year)}), graded "${esc(m.confidence)}" (${esc(m.confidence_legend)}). ${m.streams_source ? `The stream figures are not MWAN's own: ${esc(sentence(m.streams_source))}` : `Stream values: ${esc(m.streams_basis)}.`}</p>`;
}

/* ====================================================================================================
   Method
   ==================================================================================================== */
const FACTOR = {
  plant_sizes_t_dry: "Plant sizes (t dry feed a year)", min_load_fraction: "Minimum plant load (share of capacity)",
  wheat_grain_yield_t_ha: "Wheat grain yield (t/ha)", straw_t_dry_per_ha: "Baled wheat straw (t dry/ha)", collectable_fraction: "Collectable share of the straw",
  straw_dry_matter: "Straw dry matter (for transport)", alfalfa_collectable_residue_t_ha: "Collectable alfalfa residue (t/ha)",
  irrigation_mm_winter_only: "Irrigation depth, seasonal fields (mm)", irrigation_mm_year_round: "Irrigation depth, year-round fields (mm)",
  irrigation_mm_summer_crop: "Irrigation depth, summer crops (mm)", pivot_application_efficiency: "Pivot application efficiency",
  pumping_lift_m: "Depth to water, Qassim wells (m)", pump_wire_to_water_eff: "Pump wire-to-water efficiency",
  grid_kgco2e_per_kwh: "Grid emission factor (kg CO₂e/kWh)", diesel_water_kwh_per_litre: "Diesel pump work (kWh of water work per litre)",
  diesel_kgco2e_per_litre: "Diesel emission factor (kg CO₂e/L)", road_circuity: "Road circuity (road ÷ straight-line distance)",
  truck_kgco2e_per_tkm: "Truck emission factor (kg CO₂e per t·km)", char_yield_dry: "Straw char yield (dry)", char_c_org: "Straw char organic carbon",
  cement_retention: "Char carbon kept in cement (reported, not credited)", palms_per_ha: "Palms per hectare",
  palm_residue_kg_dry_per_palm: "Palm fronds (kg dry per palm a year)", palm_char_yield_dry: "Frond char yield (dry)", palm_char_c_org: "Frond char organic carbon",
  layer_manure_kg_dry_per_hen: "Layer manure (kg dry per hen a year)", cattle_manure_kg_dry_per_head: "Cattle manure (kg dry per head a year)",
  small_ruminant_manure_kg_dry_per_head: "Sheep and goat manure (kg dry per head a year)", collectable_share_cattle: "Collectable share, cattle manure",
  collectable_share_small_ruminants: "Collectable share, sheep and goat manure", collectable_share_poultry: "Collectable share, poultry",
  litter_char_yield_dry: "Litter char yield (dry)", litter_char_c_org: "Litter char organic carbon", manure_char_yield_dry: "Manure char yield (dry)",
  manure_char_c_org: "Manure char organic carbon", soil_temp_c: "Soil temperature (°C)", h_c_org_straw: "Straw char H/C (organic carbon)",
  h_c_org_fronds: "Frond char H/C (organic carbon)", h_c_org_litter: "Litter char H/C (organic carbon)", h_c_org_manure: "Manure char H/C (organic carbon)",
  palm_frond_dry_matter: "Frond dry matter (for transport)", litter_dry_matter: "Litter dry matter (for transport)", manure_dry_matter: "Manure dry matter (for transport)",
  broiler_litter_kg_dry_per_bird: "Broiler litter (kg dry per bird produced)", layers_on_hand: "Laying hens on hand",
  pivot_pressure_head_m: "Pivot pressure head (m, centre pivots other than palm groves)", drawdown_m: "Drawdown below the static water level (m)",
};
const LIFT = { WadiDawasir: "Wadi Dawasir", _fallback: "Other regions (fallback)" };
function num(x) {   // whole numbers in full, small fractions with up to four decimals, the rest with two
  if (!ok(x)) return "–";
  if (Number.isInteger(x)) return fmt(x);
  return Math.abs(x) < 1 ? x.toLocaleString("en-US", { maximumFractionDigits: 4 }) : x.toLocaleString("en-US", { maximumFractionDigits: 2 });
}
function renderMethod() {
  const el = $("meth");
  if (!el) return;
  const P = PAR(), s = SUM(), c = counts(), cov = obj(s.coverage) || {}, fm = obj(D().field_mask) || {};
  const fsz = obj(s.field_size), wcf = obj(s.worldcover_filter), ph = obj(s.pumping_head), cr = obj(s.classification_range), su = obj(P._soil_use);
  const show = (x) => Array.isArray(x) ? x.filter(ok).map((y) => fmt(y / 1000)).join("/") + " kt" : num(x);
  const factors = Object.entries(P).filter(([k, v]) => !k.startsWith("_") && obj(v) && v.source && !v.values);
  const rows = factors.map(([k, v]) => `<tr class="main"><td>${FACTOR[k] || esc(cap(k.replaceAll("_", " ")))}</td><td class="num">${show(v.low)}</td><td class="num">${show(v.central)}</td><td class="num">${show(v.high)}</td></tr><tr class="src"><td colspan="4">${linkify(sentence(v.source))}</td></tr>`).join("");
  const liftSrc = obj(D().lift) || {};
  const lift = Object.entries(liftSrc).filter(([, v]) => obj(v)).map(([k, v]) => `<tr class="main"><td>${esc(LIFT[k] || k)}</td><td class="num">${num(v.low)}</td><td class="num">${num(v.central)}</td><td class="num">${num(v.high)}</td></tr><tr class="src"><td colspan="4">${linkify(sentence(v.source))}</td></tr>`).join("");
  const notes = obj(D().lift_notes) || Object.fromEntries(Object.entries(liftSrc).filter(([, v]) => typeof v === "string"));
  const liftNotes = ["_shield", "_age"].map((k) => notes[k]).filter((x) => typeof x === "string" && x);
  const P1 = obj(cov.processed), RR = obj(cov.radar_results);
  const wc = (r) => (ok(r.worldcover_crop_ha) ? r.worldcover_crop_ha : 0) + (ok(r.worldcover_tree_ha) ? r.worldcover_tree_ha : 0);
  const wcAll = regions().reduce((t, r) => t + wc(r), 0);
  const procShare = P1 && ok(P1.share) ? P1.share : wcAll > 0 ? regions().filter((r) => r.status !== "not run").reduce((t, r) => t + wc(r), 0) / wcAll : null;
  const comp = obj(ph && ph.elec_kwh_by_component), mh = obj(ph && ph.mean_head_m);
  const compRows = comp ? [["static_depth", "Static depth to water"], ["drawdown", "Drawdown"], ["pivot_pressure", "Pivot pressure"]].filter(([k]) => obj(comp[k]))
    .map(([k, label]) => `<tr><td>${label}</td><td class="num">${fmt(comp[k].low / 1e9, 2)}</td><td class="num">${fmt(comp[k].central / 1e9, 2)}</td><td class="num">${fmt(comp[k].high / 1e9, 2)}</td></tr>`).join("") : "";
  // the deep dive's run settings (config.json res_m 20, s2_fields.py MAX_SCENES 30 and no WorldCover filter, six HV
  // dates 1 Nov-31 Dec in timeseries.json, winter window to 31 Jan) against region_pipeline.py's (40 m, 8 scenes,
  // up to 3 winter dates, Sentinel-2 winter to 15 Mar). scripts/transfer_national_flags.py copies the spring check from
  // a national field covering at least half of a deep field, and computes tree cover from each deep field's own pixels
  // (national_flags.json tree_frac_source: all "wc", none "nat")
  const deep = "The Qassim deep dive is run separately, so its figures for the same fields differ: the same NDVI on a 20 m grid with up to 30 scenes per tile and orbit and no WorldCover filter, six winter radar dates from 1 November rather than up to three, and a Sentinel-2 winter window ending 31 January rather than 15 March. It takes the spring check from this run wherever a national field covers at least half of a deep field, and its palm class uses each field's own ESA WorldCover tree cover, as this run does.";
  const pgp = obj(ph && ph.palm_grove_pivots), pgpKwh = obj(pgp && pgp.pressure_elec_kwh_not_charged);
  // electricity in one unit per sentence: TWh when the central value is 0.1 TWh or more, else GWh (never "0.00 TWh")
  const kwhTxt = (o) => {
    if (!o || !ok(o.central)) return "";
    const tw = o.central >= 1e8, f = (x) => tw ? fmt(x / 1e9, 2) : fmt(x / 1e6), u = tw ? "TWh" : "GWh";
    return `about ${f(o.central)} ${u} a year at central${ok(o.low) && ok(o.high) ? ` (${f(o.low)}–${f(o.high)} ${u} from low to high)` : ""}`;
  };
  // the reason is added only when the printed pivot rule leaves it out (newer exports end it with the palm-grove reason)
  const why = /palm/i.test(String(ph && ph.pivot_rule || "")) ? "" : ", since palm groves are not sprinkler pivots";
  const pgpTxt = pgp && ok(pgp.ha) ? ` Pivot-shaped palm groves (${ok(pgp.fields) ? `${fmt(pgp.fields)} fields, ` : ""}${fmt(pgp.ha)} ha) get no pivot pressure${why}${kwhTxt(pgpKwh) ? `; charging it on their water outside the Arabian Shield would add ${kwhTxt(pgpKwh)}, in no total` : ""}.` : "";
  const sh = obj(s.shield_no_energy), shKwh = obj(sh && sh.indicative_elec_kwh_at_fallback_lift);
  const shTxt = shKwh && ok(shKwh.central) ? ` At the fallback head (fallback static depth + drawdown + pivot pressure, as for other regions without a depth source) instead of a nominal lift, the same Arabian Shield water would take ${kwhTxt(shKwh)}, also in no total (the figure the Overview gives).` : "";
  el.innerHTML = `<ol class="steps">
    <li><b>Regions</b>: clusters of at least 1,500 ha of cropland and tree cover in ESA WorldCover 2021, cut into ${c.all ? fmt(c.all) : "–"} boxes; the ${c.tried ? fmt(c.tried) : "–"} largest, processed here, hold ~${pct(procShare)} of the cropland and tree cover in those boxes${RR && ok(RR.share) ? `, and the ${fmt(RR.boxes)} where the radar passed its quality check ~${pct(RR.share)}` : ""}.${cov.rule ? ` <details class="more"><summary>How coverage is counted</summary><p>${esc(sentence(cov.rule))}</p></details>` : ""}</li>
    <li><b>Fields</b> from ESA Sentinel-2: NDVI above ${fmt(ok(fm.green) ? fm.green : 0.4, 2)} (surface reflectance, offset-corrected) in a seasonal maximum of up to 8 scenes per tile and orbit, on a 40 m grid. ${fsz && fsz.rule ? `${esc(sentence(plain(fsz.rule)))}${ok(fsz.fields_under_3ha) ? ` ${fmt(fsz.fields_under_3ha)} fields, ${pct(fsz.share_of_field_area_under_3ha, 1)} of the field area, are under 3 ha.` : ""}` : "Patches of 3 ha or more."}${fm.lc_filter && fm.lc_filter !== "none" ? ` Patches whose ESA WorldCover majority is shrubland or grassland are dropped${fm.lc_filter === "natural_nonpivot" ? " unless they are centre pivots of 10 ha or more" : ""}.` : ""}${wcf && wcf.rule ? ` ${esc(sentence(plain(wcf.rule)))}${ok(wcf.fields) ? ` That drops ${fmt(wcf.fields)} fields, ${fmt(wcf.ha)} ha.` : ""}` : ""} ${deep}</li>
    <li><b>NISAR</b> L-band HV backscatter on the best-covering track: up to 3 winter and 4 summer dates; some regions have summer passes only. A field is farmed in a season when its peak, measured above the same scene's bare-desert median, beats a desert-patch tail threshold: median + 3 × (median − 16th percentile) of field-sized desert patches' seasonal peaks, which about 13–14% of bare-desert patches still exceed. A benchmark on these data shows the skill comes from normalising each scene to its own desert: pooled over quality-checked regions and at the same desert false-alarm rate, it beats one national raw-backscatter threshold (benchmark-set kappa 0.24 vs 0.17 in winter, 0.44 vs 0.27 in summer; the winter advantage holds at every threshold, the summer one at this operating point), and it beats NISAR-style temporal variability at every cut.${cr && cr.rule ? ` <b>Threshold range:</b> ${esc(sentence(cr.rule))}` : ""}${cr && cr.corners_rule ? ` <b>Both at once:</b> ${esc(sentence(cr.corners_rule))}` : ""}${obj(s.reproducibility) ? " Fields mapped by two neighbouring boxes are classified by each, as a reproducibility check (Overview tab)." : ""}</li>
    <li><b>Palm groves</b>: fields with at least 30% WorldCover tree cover, radar-active in every season observed.</li>
    <li><b>Manure and litter</b>: GASTAT 2024 poultry production and herd counts × per-animal factors, spread by the FAO GLW4 livestock pattern (modelled, not radar), for the whole Kingdom.${su && obj(su.litter) && su.litter.status === "excluded" ? " Poultry-litter char fails Puro's H/C<sub>org</sub> gate, so litter is not credited." : ""}</li>
    <li><b>Water, energy</b>: area × irrigation depth ÷ pivot efficiency, with published depths for winter and year-round fields and a derived depth (half the perennial) for summer crops. ${ph && ph.rule ? `Pumping electricity = water × ρg × head ÷ pump efficiency, with ${esc(ph.rule)}${ph.pivot_rule ? `; ${esc(plain(ph.pivot_rule))}` : ""}${mh && ok(mh.central) ? `; mean head ${fmt(mh.central)} m at central` : ""}.${pgpTxt} Arabian Shield fields get water but no energy.` : "Lift by region."}</li>
    ${obj(s.s2_filled) ? `<li><b>Radar + Sentinel-2 tier</b>: published next to the radar-only figures and never replacing them; Sentinel-2 fills winters the radar missed and seasons it did not observe, and the area it adds is measured by Sentinel-2, not by the radar.${s.s2_filled.rule ? ` <details class="more"><summary>The full rule</summary><p>${esc(sentence(plain(s.s2_filled.rule)))}</p></details>` : ""}</li>` : ""}
    <li><b>Siting</b>: greedy placement of plants that remove the most CO₂ net of transport. Removal is credited with the Puro.earth 2025 soil persistence model for farmland and for cement alike (H/C<sub>org</sub> below 0.70 required, on the organic-carbon basis${su && obj(su.litter) && su.litter.status === "excluded" ? "; poultry-litter char fails it" : ""}); char goes to farmland or to the nearest operating cement plant, whichever removes more net of transport (with both credited alike, the shorter haul). The all-low and all-high corners set the supply, char-yield and char-carbon, H/C and soil-temperature factors to their least or most favourable values at once, with road circuity and the truck emission factor held at central; they are not probability intervals.</li></ol>
    <h3>Depth to groundwater (m)</h3>${lift ? `<table class="stack"><tr><th>Area</th><th class="num">Low</th><th class="num">Central</th><th class="num">High</th></tr>${lift}</table>` : "<p>No depth table in this export.</p>"}
    ${liftNotes.length || shTxt ? `<p class="note">${liftNotes.map((x) => esc(sentence(x))).join(" ")}${shTxt}</p>` : ""}
    ${ph && ph.rule ? `<p class="note">These are static depths to groundwater: no pumping levels are published, so drawdown and pivot pressure are added from the factors below.</p>`
      : get(D(), "official_sources.lift") ? `<p class="note">${esc(sentence(plain(D().official_sources.lift)))}</p>` : ""}
    ${compRows ? `<h3>Pumping electricity by part of the head (TWh / year)</h3><table><tr><th>Part</th><th class="num">Low</th><th class="num">Central</th><th class="num">High</th></tr>${compRows}</table><p class="note">Radar-only electricity for the fields outside the Arabian Shield; the three parts add up to the total.${pgp ? " Pivot pressure is charged on centre pivots other than palm groves." : ""}</p>` : ""}
    <h3>Factors</h3>
    <details class="more" open><summary>All ${fmt(factors.length)} factors with their low, central and high values and sources</summary><table class="stack"><tr><th>Factor</th><th class="num">Low</th><th class="num">Central</th><th class="num">High</th></tr>${rows}</table></details>
    <p class="note">Data: NASA-ISRO NISAR (ASF DAAC), ESA Sentinel-2 and WorldCover (Microsoft Planetary Computer), FAO GLW4 2020, SFI cement database with OpenStreetMap and Climate TRACE corrections, GASTAT and MEWA 2024 statistics, geoBoundaries. AI tools (Claude) assisted with code and text.</p>`;
}

/* ====================================================================================================
   Start
   ==================================================================================================== */
function readControls() {   // a Back that skips the page cache can restore the form controls: start from what they show
  const z = Number(($("size") || {}).value);
  S.size = SIZES.includes(z) ? z : 50;
  syncRegionSelect("");
}
function wireControls() {
  const on = (id, fn) => { const e = $(id); if (e) e.addEventListener("change", fn); };
  on("showregions", (e) => toggleLayer("regions", e.target.checked));
  on("showplants", (e) => toggleLayer("plants", e.target.checked));
  on("showcement", (e) => toggleLayer("cement", e.target.checked));
  on("showmanure", (e) => toggleLayer("manure", e.target.checked));
  on("size", (e) => {
    const z = Number(e.target.value);
    if (!SIZES.includes(z)) return;
    S.size = z;
    drawPlants().then(() => safe("biochar", renderBiochar, "bio"));
    safe("biochar", renderBiochar, "bio");
    safe("lenses", renderLenses, "lens");
  });
  const bb = $("backbtn"), kb = $("keybtn");
  if (bb) bb.addEventListener("click", back);
  if (kb) kb.addEventListener("click", toggleFieldKey);
  document.addEventListener("click", (e) => {
    const b = e.target.closest && e.target.closest(".level button[data-level]");
    if (!b) return;
    const host = b.closest("[id]");
    setLevel(b.dataset.level, host && (host.id === "ov" || host.id === "lens") ? host.id : null);
  });
}
function renderAll() {
  safe("overview", renderOverview, "ov");
  safe("lenses", renderLenses, "lens");
  safe("official", renderOfficial, "off");
  safe("biochar", renderBiochar, "bio");
  safe("method", renderMethod, "meth");
}
async function init() {
  initTabs();
  readControls();
  wireControls();
  safe("map", makeMap);
  renderLegend();
  let N = null;
  try { N = await j("data/national/summary.json"); } catch (e) {
    setHint(`Could not load the national results (${e.message}).`, true);
    ["ov", "lens", "off", "bio", "meth"].forEach((id) => { const x = $(id); if (x) x.innerHTML = `<p class="loadfail">Could not load the national results. Reload the page to try again.</p>`; });
    return;
  }
  S.data = obj(N) || {};
  safe("regions", drawRegions);
  safe("select", fillRegionSelect);
  renderAll();
  renderLegend();
  if (map) {
    map.invalidateSize();
    if (S.home) map.fitBounds(S.home, fitOpts());
    setHint("Click or tap a yellow box to load its fields");
  } else setHint("The map library did not load; the figures in the panel do not need it.", true);
  // the rest arrives in parallel and fills in as it lands
  drawPlants().then(() => safe("biochar", renderBiochar, "bio"));
  j("data/cement.geojson").then((g) => safe("cement", () => addCement(g))).catch(() => {});
  j("data/national/manure.json").then((m) => { S.manure = arr(m); safe("manure", drawManure); }).catch(() => { S.manure = []; });
  j("data/scenarios/scenarios.json").then((x) => { S.sc = obj(x); safe("biochar", renderBiochar, "bio"); }).catch(() => {});
}
init().catch((e) => { if (window.console) console.error("national: init", e); setHint("Something went wrong while loading the page.", true); });
