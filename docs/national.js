/* SkyMeter: national record (docs/national.html).
   Reads data/v2/summary.json, data/v2/regions.json and data/v2/fields/<box>.json. Every figure on the page comes from
   those files: a missing value shows "–" or hides its own line, and nothing throws. Crop and water colours are read
   from the --c-crop-* and --c-wu-* tokens in style.css. */
"use strict";

const V2 = "data/v2/";
/* Crop codes in the field rows (docs/data/v2/fields/<box>.json, column 4) */
const CROP_KEY = { 1: "perennial_forage", 2: "winter_cereal", 3: "double_crop", 4: "summer_crop", 5: "tree_crop", 6: "autumn_crop",
  7: "spring_crop", 8: "winter_fodder", 9: "multi_cycle", 10: "fallow", 0: "insufficient_data" };
const SHORT = { perennial_forage: "Perennial forage", winter_cereal: "Winter cereal", double_crop: "Cereal, then summer crop",
  summer_crop: "Summer crop", tree_crop: "Tree crop", autumn_crop: "Autumn crop", spring_crop: "Spring crop", winter_fodder: "Winter fodder",
  multi_cycle: "Several cycles", fallow: "No crop", insufficient_data: "Too few looks" };
const PATTERN = { perennial_forage: "One long green stand, cut and regrown", winter_cereal: "One winter crop cycle",
  double_crop: "A winter cereal, then a summer crop", summer_crop: "One summer crop cycle", tree_crop: "Green all year: palms or orchards",
  autumn_crop: "One autumn crop cycle", spring_crop: "One spring crop cycle", winter_fodder: "One winter fodder cycle",
  multi_cycle: "Several short crop cycles", fallow: "No crop cycle this season", insufficient_data: "Too few clear Landsat looks to tell" };
const FALLBACK = { perennial_forage: "#168134", winter_cereal: "#d17d00", double_crop: "#a51303", summer_crop: "#2f6bba", tree_crop: "#532b17",
  autumn_crop: "#950375", spring_crop: "#839d54", winter_fodder: "#9680f5", multi_cycle: "#4122aa", fallow: "#868e96", insufficient_data: "#5f6b76" };
const WU_FALLBACK = ["#b7d3f6", "#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#0d366b"];
const WU_EDGES = [500, 900, 1300, 1700, 2100];   // mm a year: the key's six steps
const CONF = { 3: "High", 2: "Medium", 1: "Low", 0: "Not rated" };
const METHOD = {
  1: ["Thermal", "from this field's own Landsat heat samples"],
  2: ["Mixed", "partly from its own heat samples"],
  3: ["NDVI-calibrated", "no usable heat sample of its own: its greenness is calibrated on thermal fields in the same box"],
  4: ["Tree crop coefficient", "a tree crop coefficient times reference evapotranspiration"],
  0: ["None", "no estimate"],
};
const TABS = ["crops", "halt", "water", "residues", "checks", "method"];
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const R_EARTH = 6378137;
const NO_HOVER = window.matchMedia ? matchMedia("(hover: none)").matches : false;
const COARSE = window.matchMedia ? matchMedia("(pointer: coarse)").matches : false;
const REDUCE = window.matchMedia ? matchMedia("(prefers-reduced-motion: reduce)").matches : false;

const S = { sum: null, regions: [], crops: [], colour: "crop", show: null, current: null, loaded: 0, total: 0, failed: [],
  rects: {}, home: null, layer: null, tip: null, hadPopup: false, popupOpen: false, keyOpen: null, hintGone: false };
/* Field columns, one entry per field (all boxes): mercator x/y in 0..1, radius in metres, 1/cos(lat) */
const F = { n: 0, lon: [], lat: [], x: [], y: [], rm: [], ic: [], ha: [], crop: [], et: [], w: [], conf: [], meth: [], reg: [] };
let COL = Object.assign({}, FALLBACK), WU = WU_FALLBACK.slice(), WU_NONE = "#d3d8dd";
let REGION = "#ffd166", REGION_ON = "#fff", CASING = "rgba(29, 35, 39, .35)";   // box outlines: --c-region, --c-region-on, --c-casing
let map = null;

/* ---------- Helpers ---------- */
const $ = (id) => document.getElementById(id);
const ok = (v) => typeof v === "number" && isFinite(v);
const obj = (v) => (v && typeof v === "object" && !Array.isArray(v)) ? v : null;
const arr = (v) => Array.isArray(v) ? v : [];
const get = (o, path) => path.split(".").reduce((a, k) => (a == null ? undefined : a[k]), o);
const esc = (t) => String(t == null ? "" : t).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (v, d = 0) => ok(v) ? v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }) : "–";
const sig = (v, n = 3) => {   // n significant figures, with thousands separators
  if (!ok(v)) return "–";
  if (v === 0) return "0";
  const r = Number(v.toPrecision(n));
  return r.toLocaleString("en-US", { maximumFractionDigits: Math.max(0, n - 1 - Math.floor(Math.log10(Math.abs(r)))) });
};
const bn = (v) => fmt(v, 2);
const pct = (x, d = 0) => ok(x) ? fmt(100 * x, d) + "%" : "–";
const share = (x) => ok(x) && x > 0 && x < 0.01 ? pct(x, 1) : pct(x);   // a small share keeps one decimal
const nw = (h) => `<span class="nw">${h}</span>`;
const rng = (o, f) => o && ok(o.low) && ok(o.high) ? nw(`${f(o.low)}–${f(o.high)}`) : "–";
const list = (xs) => xs.length < 2 ? xs.join("") : xs.slice(0, -1).join(", ") + " and " + xs[xs.length - 1];
const ico = (id, cls) => `<svg class="ico${cls ? " " + cls : ""}" aria-hidden="true"><use href="img/icons.svg#i-${id}"/></svg>`;
const SUM = () => S.sum || {};
// Box regions come from geoBoundaries (regions.json admin); the summary's tables use MEWA and GASTAT spellings. One
// spelling on the page: the summary's.
const ADMIN_NAME = { "Al Jawf": "Al-Jouf", "Hayel": "Hail", "Al-Qassim": "Qassim", "Al Madinah": "Madinah", "Al Bahah": "Al-Baha", "'Asir": "Asir" };
const regionName = (r) => { const n = r && r.admin ? String(r.admin).replace(/\s+Region$/, "") : ""; return ADMIN_NAME[n] || n; };
const WORDS = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"];
const words = (n) => ok(n) && n >= 0 && n <= 10 && n === Math.round(n) ? WORDS[n] : fmt(n);   // small counts in prose are spelled out
// A crop type in running text, with its article ("an autumn crop")
const NOUN = { perennial_forage: "perennial forage", winter_cereal: "a winter cereal", double_crop: "a cereal then a summer crop", summer_crop: "a summer crop",
  tree_crop: "a tree crop", autumn_crop: "an autumn crop", spring_crop: "a spring crop", winter_fodder: "winter fodder", multi_cycle: "several crop cycles",
  fallow: "no crop", not_farmland: "land that is not farmed", insufficient_data: "too few looks" };
const noun = (k) => NOUN[k] || esc(String(k).replace(/_/g, " "));
function dateText(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ""));
  return m && MONTHS[Number(m[2]) - 1] ? `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]} ${m[1]}` : "";
}
function seasonLabel(s) {
  const m = /(\d{4})-\d{2}-\d{2}\D+(\d{4})-\d{2}-\d{2}/.exec(String(s || ""));
  return m ? `${m[1]}/${m[2].slice(2)}` : "";
}
function seasonSpan(s) {
  const m = /(\d{4}-\d{2}-\d{2})\D+(\d{4}-\d{2}-\d{2})/.exec(String(s || ""));
  return m && dateText(m[1]) && dateText(m[2]) ? `${dateText(m[1])} to ${dateText(m[2])}` : "";
}
function failHtml(msg) { return `<p class="alert loadfail" role="alert">${ico("alert")}<span>${esc(msg)}</span></p>`; }
const safe = (name, fn, box) => {   // one block failing never takes the rest of the page with it
  try { fn(); } catch (e) {
    if (window.console) console.error("national: " + name, e);
    const b = box && $(box);
    if (b) b.innerHTML = failHtml("This part could not be drawn from the data.");
  }
};
async function j(p) { const r = await fetch(p); if (!r.ok) throw new Error(`${p} (${r.status})`); return r.json(); }

/* Crops in data order (summary.crops), with the token colour for each */
const cropOf = (key) => S.crops.find((c) => c.key === key) || null;
const cropName = (key) => { const c = cropOf(key); return c && c.name ? c.name : SHORT[key] || "Field"; };
const csCls = (key) => key === "insufficient_data" ? " ring" : key === "fallow" ? " pale" : "";
const cs = (key) => `<span class="cs${csCls(key)}" style="--c:var(--c-crop-${key})" aria-hidden="true"></span>`;
function readColours() {
  let st = null;
  try { st = getComputedStyle(document.documentElement); } catch (e) { return; }
  const v = (n) => (st.getPropertyValue(n) || "").trim();
  Object.keys(FALLBACK).forEach((k) => { COL[k] = v("--c-crop-" + k) || FALLBACK[k]; });
  WU = WU_FALLBACK.map((c, i) => v("--c-wu-" + (i + 1)) || c);
  WU_NONE = v("--c-wu-none") || WU_NONE;
  REGION = v("--c-region") || REGION;
  REGION_ON = v("--c-region-on") || REGION_ON;
  CASING = v("--c-casing") || CASING;
}

/* ====================================================================================================
   Map
   ==================================================================================================== */
const floatingTools = () => { const t = $("tools"); return window.innerWidth > 860 && t && t.offsetParent ? t : null; };
function baseFit() {
  const tools = floatingTools(), h = !S.hintGone && $("hint");
  let t = Math.max(16, h && h.offsetParent ? h.offsetTop + h.offsetHeight + 12 : 16);
  let b = (tools ? tools.offsetHeight + 30 : 0) + 16;
  const y = map ? map.getSize().y : 0;
  if (y) { t = Math.max(16, Math.min(t, y - b - 100)); b = Math.max(16, Math.min(b, y - t - 100)); }
  return { paddingTopLeft: [16, t], paddingBottomRight: [16, b] };
}
// Padding for a fit: clear of the status pill, and of the floating tools card, either above it or beside it,
// whichever leaves the larger view
function fitOpts(bounds) {
  const below = baseFit(), tools = floatingTools();
  if (!tools || !bounds || !map) return below;
  const sz = map.getSize(), left = tools.offsetLeft + tools.offsetWidth + 16;
  if (sz.x - left - 16 < 240) return below;
  const beside = { paddingTopLeft: [left, below.paddingTopLeft[1]], paddingBottomRight: [16, 16] };
  const zoomOf = (o) => map.getBoundsZoom(bounds, false, L.point(o.paddingTopLeft).add(o.paddingBottomRight));
  const zb = zoomOf(below), zs = zoomOf(beside);
  return ok(zs) && (!ok(zb) || zs > zb) ? beside : below;
}
function fit(bounds, animate) {
  if (!map || !bounds) return;
  const o = fitOpts(bounds);
  if (REDUCE || animate === false) map.fitBounds(bounds, Object.assign({ animate: false }, o));
  else map.flyToBounds(bounds, Object.assign({ duration: 0.8 }, o));
}
/* Click to zoom: fly to a place, never zooming out; the place lands above the floating tools card */
function flyTo(ll, z, after) {
  if (!map || !ll) return;
  const zoom = Math.min(map.getMaxZoom() || 18, Math.max(map.getZoom(), z));
  const tools = floatingTools(), dy = tools ? Math.min(tools.offsetHeight / 2, map.getSize().y / 3) : 0;
  const c = dy ? map.unproject(map.project(L.latLng(ll), zoom).add([0, dy]), zoom) : L.latLng(ll);
  if (after) map.once("moveend", after);
  if (REDUCE) map.setView(c, zoom, { animate: false }); else map.flyTo(c, zoom, { duration: 0.8 });
}
// From the panel: on phones bring the map (above the panel) into view first
function toMap(after) {
  const m = $("map");
  if (window.innerWidth <= 860 && m) {
    const nav = document.querySelector("nav.site"), navH = nav ? nav.offsetHeight : 0, r = m.getBoundingClientRect();
    if (r.top < navH - 1 || r.bottom > window.innerHeight + 1) {
      window.scrollBy({ top: r.top - navH, behavior: REDUCE ? "auto" : "smooth" });
      if (after) setTimeout(after, REDUCE ? 0 : 450);
      return;
    }
  }
  if (after) after();
}
function setHint(text, isError) {
  let h = $("hint");
  if (!h && isError && text != null) {   // the pill was dismissed by a click: an error still needs a place to show
    const wrap = $("mapwrap");
    if (!wrap) return;
    h = document.createElement("p");
    h.id = "hint";
    h.className = "loading error";
    h.setAttribute("role", "alert");
    wrap.appendChild(h);
    S.hintGone = false;   // the pill is back: fits keep clear of it again
  }
  if (!h) return;
  if (text == null) { h.remove(); S.hintGone = true; return; }
  h.textContent = text;
  h.classList.toggle("is-busy", false);
  h.classList.toggle("error", !!isError);
}
function setBusy(text) { const h = $("hint"); if (h && !S.hintGone) { h.textContent = text; h.classList.add("is-busy"); } }

function makeMap() {
  if (typeof L === "undefined") return;
  map = L.map("map", { zoomSnap: 0.25, zoomAnimation: !REDUCE, fadeAnimation: !REDUCE, markerZoomAnimation: !REDUCE, inertia: !REDUCE,
    maxZoom: 18 }).setView([24.5, 44.5], 5);
  if (REDUCE) { const panBy = map.panBy; map.panBy = function (offset, opts) { return panBy.call(this, offset, Object.assign({}, opts, { animate: false })); }; }
  L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
    maxZoom: 18, maxNativeZoom: 17, className: "nat-base", attribution: "Imagery © Esri, Maxar, Earthstar Geographics" }).addTo(map);
  const pane = map.createPane("fieldsPane");
  pane.style.zIndex = 450;
  pane.style.pointerEvents = "none";
  defineLayer();
  S.layer = new FieldCanvas().addTo(map);
  // A click that closes an open popup only dismisses it (Leaflet closes the popup on preclick)
  map.on("preclick", () => { S.hadPopup = S.popupOpen; });
  map.on("popupopen", () => { S.popupOpen = true; hideTip(); });
  map.on("popupclose", () => { S.popupOpen = false; });
  map.on("click", onMapClick);
  if (!NO_HOVER) {
    map.on("mousemove", (e) => { S.mv = e; if (!S.raf) S.raf = requestAnimationFrame(onHover); });
    map.on("mouseout movestart zoomstart", hideTip);
  }
}

/* ---------- The field canvas: all fields drawn as circles sized by area, on one canvas, redrawn after each move ---------- */
let FieldCanvas = null;
function defineLayer() {
  FieldCanvas = L.Layer.extend({
    options: { pane: "fieldsPane", padding: 0.15 },
    onAdd() {
      this._c = L.DomUtil.create("canvas", "fields-canvas");
      L.DomUtil.addClass(this._c, "leaflet-zoom-" + (this._zoomAnimated ? "animated" : "hide"));
      this.getPane().appendChild(this._c);
      this._ctx = this._c.getContext("2d");
      this._reset();
    },
    onRemove() { L.DomUtil.remove(this._c); this._c = null; this._ctx = null; },
    getEvents() {
      const e = { moveend: this._reset, viewreset: this._reset, resize: this._reset };
      if (this._zoomAnimated) e.zoomanim = this._animateZoom;
      return e;
    },
    _animateZoom(e) {
      const m = this._map;
      if (!m || !this._nw) return;
      L.DomUtil.setTransform(this._c, m._latLngToNewLayerPoint(this._nw, e.zoom, e.center), m.getZoomScale(e.zoom));
    },
    _reset() {
      const m = this._map;
      if (!m || !this._c) return;
      const size = m.getSize(), pad = size.multiplyBy(this.options.padding).round();
      const tl = m.containerPointToLayerPoint(pad.multiplyBy(-1)).round();
      this._origin = tl;
      this._nw = m.layerPointToLatLng(tl);
      L.DomUtil.setPosition(this._c, tl);
      const w = size.x + 2 * pad.x, h = size.y + 2 * pad.y, dpr = Math.min(2, window.devicePixelRatio || 1);
      this._c.width = Math.max(1, Math.round(w * dpr));
      this._c.height = Math.max(1, Math.round(h * dpr));
      this._c.style.width = w + "px";
      this._c.style.height = h + "px";
      this._w = w; this._h = h; this._dpr = dpr;
      this.redraw();
    },
    redraw() { if (this._ctx && this._map) drawFields(this); },
  });
}
const minRadius = (z) => z < 6 ? 1.1 : z < 8 ? 1.4 : z < 10 ? 1.8 : 2.4;
function bucketOf(i) {
  if (S.colour === "water") {
    if (F.crop[i] === 10) return "wnone";
    const e = F.et[i];
    if (e == null) return "wna";
    let b = 0;
    while (b < WU_EDGES.length && e >= WU_EDGES[b]) b++;
    return "w" + b;
  }
  return "c" + F.crop[i];
}
// draw order, bottom to top: no crop and too few looks, then the larger classes, the small ones on top
const ORDER = { crop: ["c10", "c0", "c1", "c2", "c5", "c9", "c3", "c4", "c6", "c7", "c8"], water: ["wnone", "wna", "w0", "w1", "w2", "w3", "w4", "w5"] };
function styleOf(key) {
  if (key === "wnone") return { c: WU_NONE, a: 0.85 };
  if (key === "wna") return { c: COL.insufficient_data, a: 1, ring: true };
  if (key[0] === "w") return { c: WU[Number(key.slice(1))] || WU[0], a: 0.92 };
  const code = Number(key.slice(1)), k = CROP_KEY[code] || "insufficient_data";
  return { c: COL[k], a: code === 10 ? 0.6 : 0.92, ring: code === 0 };
}
function drawFields(layer) {
  const ctx = layer._ctx, m = layer._map, dpr = layer._dpr, w = layer._w, h = layer._h;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, layer._c.width, layer._c.height);
  if (!F.n) return;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const z = m.getZoom(), sc = 256 * Math.pow(2, z), po = m.getPixelOrigin();
  const ox = po.x + layer._origin.x, oy = po.y + layer._origin.y, k = sc / (2 * Math.PI * R_EARTH), rmin = minRadius(z);
  const B = {};
  for (let i = 0; i < F.n; i++) {
    if (S.show && !S.show.has(F.crop[i])) continue;
    const px = F.x[i] * sc - ox, py = F.y[i] * sc - oy, r = Math.max(rmin, F.rm[i] * k * F.ic[i]);
    if (px < -r || py < -r || px > w + r || py > h + r) continue;
    const key = bucketOf(i);
    (B[key] || (B[key] = [])).push(px, py, r);
  }
  const edge = z >= 10;
  ORDER[S.colour].forEach((key) => {
    const b = B[key];
    if (!b) return;
    const st = styleOf(key);
    ctx.globalAlpha = st.a;
    ctx.beginPath();
    for (let q = 0; q < b.length; q += 3) { ctx.moveTo(b[q] + b[q + 2], b[q + 1]); ctx.arc(b[q], b[q + 1], b[q + 2], 0, 2 * Math.PI); }
    if (st.ring) {
      ctx.fillStyle = "rgba(255,255,255,.9)"; ctx.fill();
      ctx.lineWidth = 1.6; ctx.strokeStyle = st.c; ctx.stroke();
    } else {
      ctx.fillStyle = st.c; ctx.fill();
      if (edge) { ctx.globalAlpha = 0.8; ctx.lineWidth = 0.8; ctx.strokeStyle = "#fff"; ctx.stroke(); }
    }
  });
  ctx.globalAlpha = 1;
}
let drawQueued = false;
function redraw() {
  if (drawQueued || !S.layer) return;
  drawQueued = true;
  requestAnimationFrame(() => { drawQueued = false; if (S.layer) S.layer.redraw(); });
}

/* ---------- Finding the field under the pointer (the shown fields only) ---------- */
function hitField(cp) {
  if (!map || !F.n || !cp) return -1;
  const z = map.getZoom(), sc = 256 * Math.pow(2, z), po = map.getPixelOrigin(), o = map.containerPointToLayerPoint([0, 0]);
  const ox = po.x + o.x, oy = po.y + o.y, k = sc / (2 * Math.PI * R_EARTH), rmin = minRadius(z), tol = COARSE ? 8 : 3;
  let best = -1, bs = Infinity;
  for (let i = 0; i < F.n; i++) {
    if (S.show && !S.show.has(F.crop[i])) continue;
    const r = Math.max(rmin, F.rm[i] * k * F.ic[i]) + tol;
    const dx = F.x[i] * sc - ox - cp.x;
    if (dx > r || dx < -r) continue;
    const dy = F.y[i] * sc - oy - cp.y;
    if (dy > r || dy < -r) continue;
    const s = Math.sqrt(dx * dx + dy * dy) / r;   // nearest to its own centre, relative to its size
    if (s <= 1 && s < bs) { bs = s; best = i; }
  }
  return best;
}
function regionAt(ll) {
  if (!ll) return null;
  const inside = S.regions.filter((r) => ll.lng >= r.bbox[0] && ll.lng <= r.bbox[2] && ll.lat >= r.bbox[1] && ll.lat <= r.bbox[3]);
  const area = (r) => (r.bbox[2] - r.bbox[0]) * (r.bbox[3] - r.bbox[1]);
  return inside.sort((a, b) => area(a) - area(b))[0] || null;
}
function hideTip() {
  if (map && S.tip && map.hasLayer(S.tip)) map.removeLayer(S.tip);
  const c = map && map.getContainer();
  if (c) c.classList.remove("over-item");
}
function showTip(ll, html) {
  if (!map) return;
  if (!S.tip) S.tip = L.tooltip({ direction: "top", offset: [0, -8], opacity: 1 });
  S.tip.setLatLng(ll).setContent(html);
  if (!map.hasLayer(S.tip)) map.addLayer(S.tip);
  map.getContainer().classList.add("over-item");
}
// At the country view a box is only a few pixels wide and packed with fields: there the box comes first, and its
// fields answer once it is open or the map is zoomed in
const BOX_FIRST_ZOOM = 8;
function boxFirst(ll) {
  if (!map || map.getZoom() >= BOX_FIRST_ZOOM) return null;
  const r = regionAt(ll);
  return r && r !== S.current ? r : null;
}
const boxTip = (r) => `<b>${esc(r.id)}</b>, ${esc(regionName(r))}<br><span class="tt-sub">Click to zoom to this box</span>`;
function onHover() {
  S.raf = 0;
  const e = S.mv;
  if (!e || !map || S.popupOpen) { hideTip(); return; }
  const rb = boxFirst(e.latlng);
  if (rb) { showTip(e.latlng, boxTip(rb)); return; }
  const i = hitField(e.containerPoint);
  if (i >= 0) {
    const key = CROP_KEY[F.crop[i]] || "insufficient_data";
    const water = S.colour === "water" ? (F.crop[i] === 10 ? ", water not counted" : F.et[i] == null ? ", no water estimate" : `, ${fmt(F.et[i])} mm a year`) : "";
    showTip([F.lat[i], F.lon[i]], `<b>${esc(SHORT[key])}</b>, ${fmt(F.ha[i], 1)} ha${water}<br><span class="tt-sub">Click for details</span>`);
    return;
  }
  const r = regionAt(e.latlng);
  if (r && r !== S.current) { showTip(e.latlng, boxTip(r)); return; }
  hideTip();
}
function onMapClick(e) {
  const closed = S.hadPopup;
  S.hadPopup = false;
  if (!S.hintGone) setHint(null);
  const rb = boxFirst(e.latlng);
  if (rb) { hideTip(); selectRegion(rb, true); return; }
  const i = hitField(e.containerPoint);
  if (i >= 0) { openField(i); return; }
  const r = regionAt(e.latlng);
  if (!r) return;
  if (closed && r === S.current) return;   // the click only closed a popup
  selectRegion(r, true);
}

/* ---------- Field popup ---------- */
function fieldHtml(i) {
  const key = CROP_KEY[F.crop[i]] || "insufficient_data", r = S.regions[F.reg[i]];
  const et = F.et[i], wv = F.w[i], m = METHOD[F.meth[i]] || METHOD[0], fallow = key === "fallow";
  const row = (a, b) => `<tr><th scope="row">${a}</th><td>${b}</td></tr>`;
  const use = fallow ? `Not counted<span class="sub">no crop this season</span>` : et == null ? "No estimate" : `${fmt(et)} mm a year<span class="sub">evapotranspiration, estimated</span>`;
  const vol = fallow || wv == null ? "–" : `${wv >= 1e6 ? `${sig(wv / 1e6)} million` : sig(wv)} m³ a year<span class="sub">including irrigation losses</span>`;
  return `<p class="pop-h">${cs(key)}<span>${esc(cropName(key))}</span></p>
    <p class="pop-sub">${esc(PATTERN[key] || "")}</p>
    <table class="pop">${row("Confidence", esc(CONF[F.conf[i]] || CONF[0]))}${row("Area", `${fmt(F.ha[i], 1)} ha`)}${row("Water use", use)}${row("Irrigation water", vol)}
      ${row("Method", `${esc(m[0])}<span class="sub">${esc(m[1])}</span>`)}${r ? row("Box", `${esc(r.id)}, ${esc(regionName(r))}`) : ""}</table>
    <p class="pop-note">Water is estimated from Landsat heat and NASA POWER weather, not metered.</p>`;
}
function openField(i) {
  if (!map || i < 0) return;
  hideTip();
  const ll = L.latLng(F.lat[i], F.lon[i]), r = S.regions[F.reg[i]];
  if (r && r !== S.current) selectRegion(r, false);
  const open = () => {
    if (!map) return;
    L.popup({ maxWidth: 300, minWidth: 230, autoPanPaddingTopLeft: [16, 16], autoPanPaddingBottomRight: [16, floatingTools() ? floatingTools().offsetHeight + 40 : 16] })
      .setLatLng(ll).setContent(fieldHtml(i)).openOn(map);
  };
  if (map.getZoom() >= 12.99) open(); else flyTo(ll, 13, open);
}

/* ====================================================================================================
   Farming boxes
   ==================================================================================================== */
const boundsOf = (r) => L.latLngBounds([[r.bbox[1], r.bbox[0]], [r.bbox[3], r.bbox[2]]]);
const radarAny = (r) => { const q = obj(r.radar_qc) || {}; return q.winter === true || q.summer === true; };
function drawRegions() {
  if (!map) return;
  const g = L.layerGroup(), ext = [];
  S.rects = {};
  S.regions.forEach((r) => {
    const b = boundsOf(r), any = radarAny(r);
    ext.push(b.getSouthWest(), b.getNorthEast());
    L.rectangle(b, { color: CASING, weight: 4, opacity: 1, fill: false, interactive: false }).addTo(g);   // the casing token carries its own opacity
    const base = { color: REGION, weight: 1.5, opacity: 1, fillColor: REGION, fillOpacity: 0.05, dashArray: any ? null : "5 4", interactive: false };
    S.rects[r.id] = { rect: L.rectangle(b, base).addTo(g), base };
  });
  g.addTo(map);
  S.home = ext.length ? L.latLngBounds(ext) : null;
}
function highlight(r, on) {
  const x = r && S.rects[r.id];
  if (!x) return;
  x.rect.setStyle(on ? { color: REGION_ON, weight: 3, fillOpacity: 0 } : x.base);
}
function selectRegion(r, zoom) {
  if (!r) { back(); return; }
  if (S.current && S.current !== r) highlight(S.current, false);
  S.current = r;
  highlight(r, true);
  const sel = $("region");
  if (sel && sel.value !== r.id) sel.value = r.id;
  safe("region panel", () => renderRegionPanel(r), "regionpanel");
  renderRegionBar();
  if (!S.hintGone) setHint(null);
  if (window.innerWidth > 860) { const a = $("panel"); if (a) a.scrollTop = 0; }
  if (zoom) fit(boundsOf(r));
}
function back() {
  if (S.current) highlight(S.current, false);
  S.current = null;
  const sel = $("region");
  if (sel) sel.value = "";
  renderRegionPanel(null);
  renderRegionBar();
  if (map) { map.closePopup(); fit(S.home); }
}
function fillRegionSelect() {
  const sel = $("region");
  if (!sel) return;
  const R = S.regions.slice().sort((a, b) => String(a.id).localeCompare(String(b.id)));
  sel.innerHTML = `<option value="">All boxes</option>` + R.map((r) => `<option value="${esc(r.id)}">${esc(r.id)} ${esc(regionName(r))}</option>`).join("");
  sel.value = "";
  sel.disabled = !map;
  sel.addEventListener("change", () => { const r = S.regions.find((x) => x.id === sel.value); if (r) selectRegion(r, true); else back(); });
}
function renderRegionBar() {
  const bar = $("regionbar"), st = $("regionstatus"), r = S.current;
  if (!bar || !st) return;
  bar.hidden = !r;
  if (!r) { st.textContent = ""; return; }
  st.innerHTML = `<b>${esc(r.id)}</b> ${esc(regionName(r))}: ${fmt(r.fields)} fields, ${sig(r.area_ha)} ha`;
}
/* Energy-balance QC per box (summary.water.qc.<box>): a box that never observed both anchors on one overpass carries the
   national default gap ratio (dT_src "national"), which is no check of that box; c_src says, per half of the season,
   whether its cold-anchor factor is its own or the national default */
const DT_DEFAULT = "national default (no own anchors)";
const ownGap = (q) => obj(q) && q.dT_src !== "national" && ok(q.dT_ratio);
const gapSub = (q) => obj(q) && q.dT_src === "national" ? `<span class="sub">Hot-to-cold anchor gap: ${DT_DEFAULT}</span>`
  : ownGap(q) ? `<span class="sub">Hot-to-cold anchor gap ${fmt(q.dT_ratio, 2)} times the gap SSEBop's physics expects (1 is a match)${q.dT_ratio < QC_BAND[0] || q.dT_ratio > QC_BAND[1] ? `; outside the accepted ${fmt(QC_BAND[0], 1)} to ${fmt(QC_BAND[1], 1)} band, so this box's water rests largely on fallback anchors` : ""}</span>` : "";
function coldSub(q) {
  const c = obj(q && q.c_src) || {}, nat = ["winter", "summer"].filter((h) => c[h] === "national");
  return nat.length ? `<span class="sub">Cold-anchor factor: national default in ${list(nat)}</span>` : "";
}
function renderRegionPanel(r) {
  const el = $("regionpanel");
  if (!el) return;
  if (!r) { el.hidden = true; el.innerHTML = ""; return; }
  const q = obj(get(SUM(), "water.qc." + r.id)), rq = obj(r.radar_qc) || {};
  const pass = (b) => b === true ? `<span class="qc-yes">${ico("check")}passed</span>` : b === false ? `<span class="qc-no">${ico("close")}not passed</span>` : "–";
  const items = Object.entries(obj(r.crop_ha) || {}).map(([code, ha]) => ({ key: CROP_KEY[Number(code)], ha }))
    .filter((x) => x.key && ok(x.ha) && x.ha > 0).sort((a, b) => b.ha - a.ha)
    .map((x) => ({ key: x.key, name: SHORT[x.key], ha: x.ha, sub: ok(r.area_ha) && r.area_ha > 0 ? share(x.ha / r.area_ha) : "" }));
  const water = ok(r.water_bn_m3_central) ? `${sig(r.water_bn_m3_central * 1000)} million m³ a year` : "–";
  // The box's largest fields as buttons: the keyboard route to a field's details (the map finds fields by pointer only)
  const ri = S.regions.indexOf(r), big = [];
  if (ri >= 0) for (let i = 0; i < F.n; i++) if (F.reg[i] === ri) big.push(i);
  big.sort((a, b) => F.ha[b] - F.ha[a]);
  const top = big.slice(0, 5);
  el.innerHTML = `<div class="rp-head"><div><p class="rp-k">Farming box ${esc(r.id)}</p><h2 class="rp-h" id="rp-h">${esc(regionName(r)) || esc(r.id)}</h2></div>
      <button type="button" class="rp-close" id="rp-close" aria-label="Close the box details and show all boxes">${ico("close")}</button></div>
    <dl class="ov-facts">
      <div><dt>Fields</dt><dd>${fmt(r.fields)}</dd></div>
      <div><dt>Mapped area</dt><dd>${sig(r.area_ha)} ha</dd></div>
      <div><dt>Irrigation water, estimated</dt><dd>${water}</dd></div>
      <div><dt>Median water use</dt><dd>${ok(r.median_et_mm) ? `${fmt(r.median_et_mm)} mm a year` : "–"}</dd></div>
      <div><dt>Area with its own heat samples (mainly or partly)</dt><dd>${pct(r.thermal_share)}</dd></div>
      <div><dt>NISAR radar check</dt><dd>${nw("Winter " + pass(rq.winter))}<span class="sub">${nw("Summer " + pass(rq.summer))}</span></dd></div>
      ${q ? `<div class="wide"><dt>Energy-balance check</dt><dd>${ok(q.accepted) && ok(q.overpasses) ? `${fmt(q.accepted)} of ${fmt(q.overpasses)} Landsat overpasses kept` : "–"}${gapSub(q)}${coldSub(q)}</dd></div>` : ""}
    </dl>
    ${items.length ? `<h3>Crop types in this box</h3>${cbars(items)}` : ""}
    ${top.length ? `<h3>Largest fields</h3><ul class="rp-fields">${top.map((i) => { const k = CROP_KEY[F.crop[i]] || "insufficient_data"; return `<li><button type="button" data-field="${i}">${cs(k)}<span>${esc(SHORT[k])}</span><span class="rp-ha">${fmt(F.ha[i], 1)} ha</span></button></li>`; }).join("")}</ul>` : ""}
    <p class="note">${radarAny(r) ? "Radar confirms crop canopy here in the seasons where it passed its quality check." : "The radar did not pass its quality check here, so the crop types rest on Landsat alone."}</p>`;
  el.hidden = false;
  const c = $("rp-close");
  if (c) c.addEventListener("click", back);
  el.querySelectorAll("button[data-field]").forEach((b) => b.addEventListener("click", () => { const i = Number(b.dataset.field); toMap(() => openField(i)); }));
}

/* ====================================================================================================
   Map key: the crop filter, or the water ramp
   ==================================================================================================== */
function renderLegend() {
  const el = $("legend");
  if (!el) return;
  const filt = S.show ? [...S.show].map((c) => SHORT[CROP_KEY[c]]).filter(Boolean) : [];
  const boxes = `<p class="ck-foot"><span class="bx"><i aria-hidden="true"></i>Farming box</span><span class="bx"><i class="dash" aria-hidden="true"></i>Box where the radar check passed in neither season</span></p>`;
  if (S.colour === "water") {
    const labels = WU.map((c, b) => b === 0 ? `under ${fmt(WU_EDGES[0])}` : b === WU_EDGES.length ? `${fmt(WU_EDGES[b - 1])}+` : `${fmt(WU_EDGES[b - 1])}–${fmt(WU_EDGES[b])}`);
    el.innerHTML = `<p class="ck-head"><span><b>Water use</b>, mm a year (estimate)</span>${S.show ? `<button type="button" class="ck-all" data-all="1">Show all crops</button>` : ""}</p>
      <ul class="wu-ramp">${WU.map((c, b) => `<li><i style="--c:${c}" aria-hidden="true"></i>${labels[b]}</li>`).join("")}</ul>
      <ul class="wu-extra"><li><span class="cs pale" style="--c:var(--c-wu-none)" aria-hidden="true"></span>No crop: not counted</li><li><span class="cs ring" style="--c:var(--c-crop-insufficient_data)" aria-hidden="true"></span>No estimate</li></ul>
      ${S.show ? `<p class="ck-foot">Showing ${esc(list(filt))} only.</p>` : ""}${boxes}`;
    return;
  }
  el.innerHTML = `<p class="ck-head"><span><b>Crop type</b>, share of mapped area</span>${S.show ? `<button type="button" class="ck-all" data-all="1">Show all</button>` : `<span>Select crops to show only those</span>`}</p>
    <ul class="ck-list" role="group" aria-label="Show only these crops">${S.crops.map((c) => {
      const on = !!(S.show && S.show.has(c.code));
      return `<li><button type="button" data-crop="${c.code}" aria-pressed="${on}"${S.show && !on ? ' class="dim"' : ""}>${cs(c.key)}<span class="ck-name">${esc(SHORT[c.key] || c.name)}</span><span class="ck-v">${share(c.share)}</span></button></li>`;
    }).join("")}</ul>${boxes}`;
}
function setKeyOpen(open) {
  S.keyOpen = open;
  const tools = $("tools"), btn = $("keybtn");
  if (tools) tools.classList.toggle("keys-off", !open);
  if (btn) { btn.setAttribute("aria-expanded", open ? "true" : "false"); btn.textContent = open ? "Hide key" : "Show key"; }
}
function setColour(c) {
  if (c !== "crop" && c !== "water") return;
  S.colour = c;
  document.querySelectorAll("[data-colour]").forEach((b) => {
    const on = b.dataset.colour === c;
    b.classList.toggle("on", on);
    b.setAttribute("aria-pressed", on ? "true" : "false");
  });
  renderLegend();
  redraw();
}
function setShow(codes) {
  S.show = codes && codes.size ? codes : null;
  renderLegend();
  redraw();
  if (map && S.popupOpen) map.closePopup();
}
function toggleCrop(code) {
  const s = new Set(S.show || []);
  if (s.has(code)) s.delete(code); else s.add(code);
  setShow(s);
  const b = document.querySelector(`#legend button[data-crop="${code}"]`);
  if (b) b.focus();
}

/* ====================================================================================================
   Panel: tabs and shared pieces
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
  const aside = $("panel"), tabs = document.querySelector(".tabs"), panel = $("tab-" + n);
  if (window.innerWidth > 860) { if (aside && !S.current) aside.scrollTop = 0; }
  else if (tabs && panel) {
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
  const fromHash = () => { const h = decodeURIComponent(location.hash.slice(1)); if (TABS.includes(h)) openTab(h, { hash: false, scroll: false }); };
  window.addEventListener("hashchange", fromHash);
  fromHash();
}
function cbars(items) {   // items: [{key, name, ha, sub, note}]; bars scale to the largest
  const max = Math.max(0, ...items.map((x) => x.ha).filter(ok));
  return `<ul class="cbars">${items.map((x) => `<li><div class="cb-head">${cs(x.key)}<span class="cb-name">${esc(x.name)}</span><span class="cb-num">${fmt(x.ha)} ha</span>${x.sub != null ? `<span class="cb-sub">${x.sub}</span>` : ""}</div>` +
    `<div class="cb-bar" aria-hidden="true"><i style="--c:var(--c-crop-${x.key});--w:${max > 0 && ok(x.ha) ? (100 * x.ha / max).toFixed(1) : 0}%"></i></div>${x.note ? `<p class="cb-note">${x.note}</p>` : ""}</li>`).join("")}</ul>`;
}
function meter(label, x, value, sub) {
  if (!ok(x)) return "";
  return `<div class="meter"><div class="meter-head"><span>${label}</span><b>${value}</b></div><div class="meter-bar" aria-hidden="true"><i style="--w:${(100 * Math.max(0, Math.min(1, x))).toFixed(1)}%"></i></div>${sub ? `<p class="meter-sub">${sub}</p>` : ""}</div>`;
}
function stack(parts, f) {   // parts: [{label, v, c}]; the key carries every value
  const p = parts.filter((x) => ok(x.v) && x.v > 0), tot = p.reduce((t, x) => t + x.v, 0);
  if (!p.length || !(tot > 0)) return "";
  return `<div class="stack" aria-hidden="true">${p.map((x) => `<i style="--c:${x.c};--w:${(100 * x.v / tot).toFixed(2)}%"></i>`).join("")}</div>` +
    `<ul class="stack-key">${p.map((x) => `<li><i style="--c:${x.c}" aria-hidden="true"></i><span>${x.label}</span><b>${f(x.v)}</b></li>`).join("")}</ul>`;
}
// A range bar: lanes {cls, a, b, m} (a range and its own central tick) or {pt} (one value as a ring), on one scale;
// the end labels are divided by div (default 1)
function rbar(lanes, d, div) {
  const dv = ok(div) && div ? div : 1;
  const L_ = lanes.filter((l) => ("pt" in l) ? ok(l.pt) : ok(l.a) && ok(l.b));
  const vals = [];
  L_.forEach((l) => { if ("pt" in l) vals.push(l.pt); else { vals.push(l.a, l.b); if (ok(l.m)) vals.push(l.m); } });
  if (!vals.length) return "";
  const lo = Math.min(...vals), hi = Math.max(...vals);
  if (!(hi > lo)) return "";
  const at = (x) => (100 * (x - lo) / (hi - lo)).toFixed(2) + "%";
  return `<div class="rb" aria-hidden="true">${L_.map((l) => ("pt" in l) ? `<div class="rb-lane rb-pt"><i style="--x:${at(l.pt)}"></i></div>`
    : `<div class="rb-lane ${l.cls}"><i style="--a:${at(Math.min(l.a, l.b))};--b:${at(Math.max(l.a, l.b))}"></i>${ok(l.m) ? `<b class="rb-tk" style="--x:${at(l.m)}"></b>` : ""}</div>`).join("")}</div>` +
    `<div class="rb-ends" aria-hidden="true"><span>${fmt(lo / dv, d)}</span><span>${fmt(hi / dv, d)}</span></div>`;
}
const triple = (o) => obj(o) && ok(o.central) ? `${bn(o.central)} <span class="sub">${rng(o, bn)}</span>` : "–";
const actBtn = (act, icon, label) => `<button type="button" data-act="${act}">${ico(icon)}<span>${label}</span></button>`;

/* ---------- Coverage and water context (shared by the tabs) ---------- */
// The processed boxes' share of the cropland and tree cover ESA WorldCover finds in all the farming boxes
const boxCover = (cov) => cov && ok(cov.crop_tree_share_of_worldcover)
  ? ` hold about ${pct(cov.crop_tree_share_of_worldcover)} of the cropland and tree cover that ESA WorldCover finds in all ${ok(cov.boxes_total) ? `${fmt(cov.boxes_total)} ` : ""}farming boxes` : "";
const OUTSIDE = "Fields in the other boxes, and scattered farmland outside the boxes, are in no total.";
// MEWA 2024 groundwater for the same regions as the shelf figure: the halt regions in the comparison table
function mewaShelf(s) {
  const G = arr(get(s, "validation.gastat_by_region")).filter((r) => obj(r) && r.halt_region === true && ok(r.mewa_agri_groundwater_bn_m3));
  return G.length ? G.reduce((t, r) => t + r.mewa_agri_groundwater_bn_m3, 0) : null;
}
const above = (x) => `${pct(Math.abs(x))} ${x >= 0 ? "above" : "below"}`;
const inside = (v, o) => ok(v) && o && ok(o.low) && ok(o.high) && v >= o.low && v <= o.high;
// The heat-based totals in context: the shelf against MEWA for the same regions, all water against MEWA for the Kingdom
// and against the v1 benchmark (each part only when its numbers are there)
function waterContext(s) {
  const w = obj(s.water) || {}, sh = obj(w.shelf_groundwater_bn_m3) || {}, g = obj(w.gross_bn_m3) || {}, bm = obj(w.benchmark_bn_m3) || {}, ms = mewaShelf(s);
  const a = ok(sh.central) && ok(ms) && ms > 0 ? `the central groundwater figure for the shelf is ${above(sh.central / ms - 1)} MEWA's 2024 figure for all farms in the same regions` : "";
  const b = ok(g.central) && ok(w.mewa_bn_m3) && w.mewa_bn_m3 > 0 ? `the central figure for all irrigation water is ${above(g.central / w.mewa_bn_m3 - 1)} MEWA's figure for all farms in the Kingdom` : "";
  const c = ok(g.central) && ok(bm.central) && bm.central > 0 ? `about ${fmt(g.central / bm.central, 1)} times the v1 benchmark` : "";
  const parts = [a, b && c ? `${b} and ${c}` : b || (c ? `the central figure for all irrigation water is ${c}` : "")].filter(Boolean);
  if (!parts.length) return "";
  const inS = inside(ms, sh), inG = inside(w.mewa_bn_m3, g);
  return `For the mapped fields alone, ${parts.join(", and ")}.` +
    (inS && inG ? " MEWA's figures lie inside SkyMeter's low-to-high ranges." : inS ? " MEWA's figure for the shelf regions lies inside SkyMeter's low-to-high range." : inG ? " MEWA's figure for the Kingdom lies inside SkyMeter's low-to-high range." : "") +
    " The heat-based method scales a fully watered field to 1.2 times the grass reference evapotranspiration, so it reads higher than benchmark depths.";
}

/* ---------- Crops ---------- */
function renderCrops() {
  const el = $("p-crops");
  if (!el) return;
  const s = SUM(), cov = obj(s.coverage) || {}, v = obj(s.validation) || {}, conf = obj(v.confidence_ha) || {};
  const items = S.crops.slice().sort((a, b) => (b.area_ha || 0) - (a.area_ha || 0)).map((c) => ({ key: c.key, name: c.name || SHORT[c.key], ha: c.area_ha, sub: share(c.share),
    note: `${fmt(c.fields)} fields${ok(c.median_et_mm) && c.key !== "fallow" ? `, median water use ${fmt(c.median_et_mm)} mm a year` : ""}` }));
  el.innerHTML = `<p class="lead">Every mapped field gets one crop type for the season${seasonSpan(s.season) ? ` (${esc(seasonSpan(s.season))})` : ""}, from its Landsat 8/9 greenness record: how many crop cycles it had, when they started and ended, and how long they stayed green.</p>
    <div class="ov-hero"><p class="ov-k">${ico("field", "sm")}Fields in the record</p><p class="ov-num">${fmt(cov.fields)}<span class="ov-unit">fields</span></p>
      <dl class="ov-facts">
        <div><dt>Mapped area</dt><dd>${sig(cov.area_ha)} ha</dd></div>
        <div><dt>Farming boxes processed</dt><dd>${ok(cov.boxes_processed) && ok(cov.boxes_total) ? `${fmt(cov.boxes_processed)} of ${fmt(cov.boxes_total)}` : "–"}</dd></div>
        <div><dt>Boxes where the radar passed its check</dt><dd>${fmt(cov.radar_qc_boxes)}<span class="sub">${ok(cov.radar_qc_area_ha) ? `${sig(cov.radar_qc_area_ha)} ha of fields` : ""}</span></dd></div>
        <div><dt>Winter-cereal cycles</dt><dd>${sig(s.winter_cereal_cycle_ha)} ha<span class="sub">including cereal before a summer crop</span></dd></div>
      </dl></div>
    <p class="note">${ok(cov.boxes_processed) && boxCover(cov) ? `The ${fmt(cov.boxes_processed)} processed boxes${boxCover(cov)}. ` : ""}${OUTSIDE}</p>
    <h3>Area by crop type</h3>
    ${items.length ? cbars(items) : `<p class="note">No crop table in this data export.</p>`}
    <p class="note">On the map, select crops in the key to show only those, or switch the colours to water use.</p>
    <h3>How confident each call is</h3>
    ${stack([{ label: "High", v: conf.high, c: "var(--rb-mid)" }, { label: "Medium", v: conf.medium, c: "var(--rb-thr)" }, { label: "Low", v: conf.low, c: "var(--rb-factor)" }], (x) => `${fmt(x)} ha`) || `<p class="note">–</p>`}
    <p class="note">Confidence says how clearly a field's greenness record fits its crop type. Low-confidence fields stay in the totals; the Checks tab tests the calls.</p>`;
}

/* ---------- Fodder halt ---------- */
function haltExcess(h) {   // regions where the mapped perennial forage alone is over a tenth above GASTAT's whole fodder area
  return arr(h.regions).filter((r) => ok(r.perennial_ha) && ok(r.gastat_fodder_ha) && r.gastat_fodder_ha > 0 && r.perennial_ha / r.gastat_fodder_ha > 1.1).map((r) => String(r.region));
}
function renderHalt() {
  const el = $("p-halt");
  if (!el) return;
  const s = SUM(), h = obj(s.halt);
  if (!h) { el.innerHTML = `<p class="note">No fodder-halt baseline in this data export.</p>`; return; }
  const R = arr(h.regions).filter(obj), st = obj(h.stand_ha) || {}, over = haltExcess(h), po = pfOver(blindOf(s));
  const gTot = R.reduce((t, r) => t + (ok(r.gastat_fodder_ha) ? r.gastat_fodder_ha : 0), 0);
  const names = R.map((r) => esc(r.region));
  const mh = minHa(blindOf(s));
  el.innerHTML = `<p class="lead">MEWA is halting the cultivation of perennial green fodder in ${R.length ? `${words(R.length)} sedimentary-shelf regions (${list(names)})` : "the sedimentary-shelf regions"}${dateText(h.effective) ? ` from ${esc(dateText(h.effective))}` : ""}. This is the ${esc(seasonLabel(s.season) || "season's")} baseline: the fields that grew perennial forage there and the water they used. It is a record to screen against, not an enforcement tool.</p>
    <div class="ov-hero"><p class="ov-k">${ico("field", "sm")}Perennial forage in the halt regions</p><p class="ov-num">${sig(h.perennial_ha)}<span class="ov-unit">ha</span></p>
      <dl class="ov-facts"><div><dt>Fields</dt><dd>${fmt(h.fields)}</dd></div><div><dt>Irrigation water, estimated</dt><dd>${bn(h.water_bn_m3_central)} bn m³ a year</dd></div></dl></div>
    ${po && po.over >= 0.005 ? `<p class="note">The blind visual check, a national sample${ok(mh) ? ` of fields of ${fmt(mh)} ha or more` : ""}, suggests ${overText(po)}. ${cap1(haltIf(h, po))} (see the Checks tab).</p>` : ""}
    <div class="act">${actBtn("forage", "map", "Show all perennial forage on the map (every region)")}</div>
    <p class="note">The map shows every perennial-forage field; the baseline above counts only stands growing at season end in the halt regions.</p>
    <h3>By region</h3>
    <table class="wide"><tr><th scope="col">Region</th><th class="num" scope="col">Perennial forage at season end, ha</th><th class="num" scope="col">Fields</th><th class="num" scope="col">Water of this forage, bn m³ a year</th><th class="num" scope="col">GASTAT 2024 fodder, ha</th></tr>
      ${R.map((r) => `<tr><td>${esc(r.region)}</td><td class="num${over.includes(String(r.region)) ? " over" : ""}">${fmt(r.perennial_ha)}</td><td class="num">${fmt(r.fields)}</td><td class="num">${bn(r.water_bn_m3_central)}</td><td class="num">${fmt(r.gastat_fodder_ha)}</td></tr>`).join("")}
      <tr class="total"><th scope="row">Total</th><td class="num">${fmt(h.perennial_ha)}</td><td class="num">${fmt(h.fields)}</td><td class="num">${bn(h.water_bn_m3_central)}</td><td class="num">${gTot > 0 ? fmt(gTot) : "–"}</td></tr></table>
    <p class="note">GASTAT's figure is context, not a check: it counts all fodder, perennial and seasonal.${over.length ? ` Even so, the mapped perennial forage alone is more than a tenth above GASTAT's whole fodder area in ${list(over.map(esc))} (shown in bold). SkyMeter reports this as found; it is not scaled down to match.` : ""}</p>
    ${ok(st.established) && ok(st.new) ? `<h3>Stand age</h3>
    <p class="note">The baseline counts stands growing at the end of the season: ${sig(st.established)} ha already established when the season began and ${sig(st.new)} ha that first greened during it, either a new perennial stand or a long summer fodder crop (one season cannot tell them apart; the next season's record will).${ok(st.ended) ? ` Not counted: ${sig(st.ended)} ha of stands that ended during the season${ok(st.within) ? ` and ${sig(st.within)} ha that started and ended within it` : ""}.` : ""}</p>` : ""}
    ${h.source ? `<p class="note">Source: ${h.url ? `<a href="${esc(h.url)}" rel="noopener">${esc(h.source)}</a>` : esc(h.source)}.</p>` : ""}`;
}

/* ---------- Water ---------- */
function renderWater() {
  const el = $("p-water");
  if (!el) return;
  const s = SUM(), w = obj(s.water);
  if (!w) { el.innerHTML = `<p class="note">No water figures in this data export.</p>`; return; }
  const sh = obj(w.shelf_groundwater_bn_m3) || {}, sd = obj(w.shield_undetermined_bn_m3), nc = obj(w.noncrop_et_bn_m3), g = obj(w.gross_bn_m3) || {},
    net = obj(w.net_bn_m3), bm = obj(w.benchmark_bn_m3) || {}, ms = obj(w.methods_area_share) || {}, en = obj(s.energy) || {};
  const crops = S.crops.filter((c) => c.key !== "fallow" && (ok(c.water_bn_m3) || ok(c.median_et_mm))).sort((a, b) => (b.water_bn_m3 || 0) - (a.water_bn_m3 || 0));
  const mewaS = mewaShelf(s), ncs = noCropSeen(blindOf(s));
  el.innerHTML = `<p class="lead">Water use is estimated field by field from Landsat surface heat and NASA POWER weather. The result is an estimate, not a meter reading. Its low and high values vary the two largest scaling choices, the reference-evapotranspiration scaling and the irrigation efficiency. Errors in the heat anchors and in the crop map are not in the range.</p>
    <div class="kpi"><div class="kpi-label">${ico("water", "sm")}<span>Groundwater pumped on the sedimentary shelf</span></div>
      <div class="kpi-value">${bn(sh.central)}<span class="kpi-unit">billion m³ a year</span></div>
      ${rbar([{ cls: "rb-thr", a: sh.low, b: sh.high, m: sh.central }, { pt: mewaS }], 2)}
      <dl class="kpi-range"><div class="r-thr"><dt>Heat-based estimate, low to high</dt><dd>${rng(sh, bn)}</dd></div>
        ${ok(mewaS) ? `<div class="r-pt"><dt>MEWA 2024, same regions, all farms</dt><dd>${bn(mewaS)}</dd></div>` : ""}</dl></div>
    <dl class="ov-facts">
      ${sd ? `<div class="wide"><dt>Arabian Shield irrigation: source not determined</dt><dd>${triple(sd)}<span class="sub">bn m³ a year on ${sig(w.shield_ha)} ha of fields in the six western and south-western regions (mostly the Arabian Shield and the Red Sea coastal plain), where water can come from floods, rain or shallow wells. SkyMeter does not determine which, so it is kept out of the groundwater figure.</span></dd></div>` : ""}
      <div><dt>All irrigation water, shelf and Shield</dt><dd>${triple(g)}<span class="sub">bn m³ a year, including losses</span></dd></div>
      ${net ? `<div><dt>Net consumptive use</dt><dd>${triple(net)}<span class="sub">bn m³ a year: evapotranspiration minus effective rain</span></dd></div>` : ""}
      ${nc ? `<div class="wide"><dt>Not counted: evapotranspiration of fields mapped as no crop</dt><dd>${triple(nc)}<span class="sub">bn m³ a year from fields mapped as having no crop this season${ncs && ncs.crop >= 0.5 ? "; the blind check suggests most of them did carry one, so much of this is probably missed irrigation" : ""}</span></dd></div>` : ""}
    </dl>
    <h3>Cross-checks</h3>
    ${rbar([{ cls: "rb-thr", a: g.low, b: g.high, m: g.central }, { cls: "rb-factor", a: bm.low, b: bm.high, m: bm.central }, { pt: w.mewa_bn_m3 }], 2)}
    <dl class="kpi-range">
      <div class="r-thr"><dt>Heat-based, all irrigation water</dt><dd>${bn(g.central)} (${rng(g, bn)})</dd></div>
      <div class="r-factor"><dt>Benchmark, v1 method: mapped area times a benchmark depth per crop</dt><dd>${bn(bm.central)} (${rng(bm, bn)})</dd></div>
      ${ok(w.mewa_bn_m3) ? `<div class="r-pt"><dt>MEWA 2024, all farms in the Kingdom</dt><dd>${bn(w.mewa_bn_m3)}</dd></div>` : ""}
    </dl>
    <p class="note">Billion m³ a year. MEWA's figures cover every farm, mapped or not; the benchmark is the method of SkyMeter's first version. ${waterContext(s)}${ok(w.radar_qc_boxes_gross_bn_m3) ? ` In the boxes where the radar passed its check, the heat-based figure is ${bn(w.radar_qc_boxes_gross_bn_m3)}.` : ""}</p>
    <h3>How each field's water was estimated</h3>
    ${stack([{ label: "Thermal: own heat samples", v: ms.thermal, c: "var(--c-m-thermal)" }, { label: "Mixed", v: ms.mixed, c: "var(--c-m-mixed)" },
      { label: "NDVI-calibrated", v: ms.ndvi_calibrated, c: "var(--c-m-ndvi)" }, { label: "Tree crop coefficient", v: ms.kc_tree, c: "var(--c-m-tree)" },
      { label: "No estimate", v: ms.insufficient, c: "var(--c-m-none)" }], (x) => pct(x, 1)) || `<p class="note">–</p>`}
    <p class="note">Shares of mapped area.${ok(w.eto_adj_mm_median) ? ` Reference evapotranspiration from NASA POWER, aridity-adjusted: median ${fmt(w.eto_adj_mm_median)} mm a year across the boxes.` : ""}</p>
    <div class="act">${actBtn("water", "water", "Colour the map by water use")}</div>
    ${crops.length ? `<h3>Water by crop type</h3><table><tr><th scope="col">Crop type</th><th class="num" scope="col">Median water use (evapotranspiration), mm a year</th><th class="num" scope="col">Irrigation water including losses, bn m³ a year</th></tr>
      ${crops.map((c) => `<tr><td>${cs(c.key)} ${esc(c.name || SHORT[c.key])}</td><td class="num">${fmt(c.median_et_mm)}</td><td class="num">${bn(c.water_bn_m3)}</td></tr>`).join("")}</table>` : ""}
    ${obj(en.twh) ? `<h3>Pumping electricity</h3><p class="note">Modelled from the water and the depth to groundwater, not metered: ${bn(en.twh.central)} TWh a year (${rng(en.twh, bn)})${obj(en.jjas_mw) && ok(en.jjas_mw.central) ? `, an average load of ${fmt(en.jjas_mw.central)} MW from June to September (${rng(en.jjas_mw, fmt)})` : ""}. The Arabian Shield gets none.</p>` : ""}`;
}

/* ---------- Residues ---------- */
function renderResidues() {
  const el = $("p-residues");
  if (!el) return;
  const r = obj(SUM().residues);
  if (!r) { el.innerHTML = `<p class="note">No residue figures in this data export.</p>`; return; }
  const st = obj(r.straw_t_dry) || {}, fn = obj(r.fronds_t_dry_national) || {}, fm = obj(r.fronds_t_dry_mapped), rm = obj(r.removal_t_co2_per_t_dry);
  const kt = (x) => fmt(x / 1e3);
  const sc = arr(r.scenarios).filter(obj), shares = [...new Set(sc.map((x) => x.collected_share).filter(ok))].sort((a, b) => a - b);
  const cell = (share, lv) => { const x = sc.find((y) => y.collected_share === share && y.level === lv); return x && ok(x.total_t_co2) ? kt(x.total_t_co2) : "–"; };
  el.innerHTML = `<p class="flag">${ico("info")}<span><b>Technical potential only.</b> No biochar plants exist or are planned. These figures show what the residues could store as biochar if a share of them were collected.</span></p>
    <div class="kpi"><div class="kpi-label">${ico("residue", "sm")}<span>Cereal straw, from winter-cereal cycles</span></div>
      <div class="kpi-value">${ok(st.central) ? kt(st.central) : "–"}<span class="kpi-unit">thousand tonnes dry a year</span></div>
      ${rbar([{ cls: "rb-factor", a: st.low, b: st.high, m: st.central }], 0, 1e3)}
      <dl class="kpi-range"><div class="r-factor"><dt>Low to high</dt><dd>${rng(st, kt)}</dd></div><div class="r-none"><dt>Winter-cereal area counted for straw</dt><dd>${sig(r.winter_cereal_cycle_ha)} ha</dd></div></dl>
      <p class="note">Fields that also held perennial forage count only for their cereal part${ok(r.winter_cereal_cycle_ha) && ok(SUM().winter_cereal_cycle_ha) && r.winter_cereal_cycle_ha < SUM().winter_cereal_cycle_ha ? `, so this is below the ${sig(SUM().winter_cereal_cycle_ha)} ha of winter-cereal cycles on the Crops tab` : ""}.</p></div>
    <div class="kpi"><div class="kpi-label">${ico("leaf", "sm")}<span>Date-palm fronds, from GASTAT's palm count</span></div>
      <div class="kpi-value">${ok(fn.central) ? kt(fn.central) : "–"}<span class="kpi-unit">thousand tonnes dry a year</span></div>
      ${rbar([{ cls: "rb-factor", a: fn.low, b: fn.high, m: fn.central }], 0, 1e3)}
      <dl class="kpi-range"><div class="r-factor"><dt>Low to high</dt><dd>${rng(fn, kt)}</dd></div><div class="r-none"><dt>GASTAT 2024 date palms, whole Kingdom</dt><dd>${ok(r.gastat_date_palms) && r.gastat_date_palms >= 1e6 ? `${sig(r.gastat_date_palms / 1e6)} million` : fmt(r.gastat_date_palms)}</dd></div>
        ${fm ? `<div class="r-none"><dt>On the ${sig(r.tree_crop_ha_mapped)} ha of mapped tree-crop fields</dt><dd>${ok(fm.central) ? `${kt(fm.central)} thousand t` : "–"}</dd></div>` : ""}</dl></div>
    ${shares.length ? `<h3>Carbon removal by collected share</h3>
      <table><tr><th scope="col">Share collected</th><th class="num" scope="col">Low</th><th class="num" scope="col">Central</th><th class="num" scope="col">High</th></tr>
        ${shares.map((x) => `<tr><td>${pct(x)}</td><td class="num">${cell(x, "low")}</td><td class="num">${cell(x, "central")}</td><td class="num">${cell(x, "high")}</td></tr>`).join("")}</table>
      <p class="note">Thousand tonnes of CO₂ a year: straw from the mapped winter-cereal cycles plus fronds from GASTAT's palm count. Haulage, plant energy and costs are not netted out.</p>` : ""}
    ${rm ? `<details class="more"><summary>Removal per dry tonne of residue</summary><table><tr><th scope="col">Estimate</th><th class="num" scope="col">Straw, t CO₂</th><th class="num" scope="col">Fronds, t CO₂</th></tr>
      ${["low", "central", "high"].map((lv) => obj(rm[lv]) ? `<tr><td>${lv[0].toUpperCase() + lv.slice(1)}</td><td class="num">${fmt(rm[lv].straw, 2)}</td><td class="num">${fmt(rm[lv].fronds, 2)}</td></tr>` : "").join("")}</table>
      <p>Char yield times its organic carbon times the Puro.earth 2025 persistence model.</p></details>` : ""}`;
}

/* ---------- Blind visual check (summary.validation.blind_check): shared by the Checks, Fodder halt and Method tabs ---------- */
const GROUP = { perennial: "Perennial forage", seasonal: "Seasonal crops", tree: "Tree crops", no_crop: "No crop" };
const GROUP_ORDER = ["perennial", "seasonal", "tree", "no_crop"];
// The no-crop group's name says whether it also holds land that is not farmed (coarse_legend.groups.no_crop)
const groupNames = (gr) => Object.assign({}, GROUP, arr(gr && gr.no_crop).includes("not_farmland") ? { no_crop: "No crop or not farmland" } : {});
const cap1 = (t) => { const x = String(t || ""); return x.charAt(0).toUpperCase() + x.slice(1); };
const blindOf = (s) => { const v = obj(s && s.validation); return v ? obj(v.blind_check) : null; };
const ciRange = (x, ci) => ok(x) && ok(ci) && ci > 0 ? `${pct(Math.max(0, x - ci))} to ${pct(Math.min(1, x + ci))}` : "";
const FEW = 5;   // a crop type with fewer sampled fields than this gets no confirmed share: one or two fields say nothing
const ciText = (x, ci) => { const r = ciRange(x, ci); return r ? `95% interval ${r}` : ""; };
const minHa = (b) => { const m = /fields\s*>=\s*(\d+(?:\.\d+)?)\s*ha/i.exec(String((b && b.design) || "")); return m ? Number(m[1]) : null; };
// The error-adjusted perennial-forage area against the mapped area: the share of the mapped area by which the map may
// overstate it, with the 95% interval carried through (lo at or below 0 means the interval reaches no overstatement)
function pfOver(b) {
  const e = obj(b && b.error_adjusted_area), p = obj(e && e.perennial_forage);
  if (!p || !ok(p.ha) || !ok(p.mapped_ha) || !(p.mapped_ha > 0)) return null;
  const ci = ok(p.ci95_ha) ? p.ci95_ha : null;
  return { adj: p.ha, ci, mapped: p.mapped_ha, over: 1 - p.ha / p.mapped_ha,
    lo: ci != null ? 1 - (p.ha + ci) / p.mapped_ha : null, hi: ci != null ? 1 - (p.ha - ci) / p.mapped_ha : null };
}
// "about one in six hectares mapped as perennial forage (16%, 95% interval 0% to 32%) may be another crop"
function overText(o, bold, start) {
  const m = `${start ? "About" : "about"} one in ${words(Math.round(1 / o.over))} hectares mapped as perennial forage`;
  const ci = ok(o.lo) && ok(o.hi) && o.hi > 0 ? `, 95% interval ${pct(Math.max(0, o.lo))} to ${pct(o.hi)}` : "";
  return `${bold ? `<b>${m}</b>` : m} (${pct(o.over)}${ci}) may be another crop`;
}
// The fodder-halt baseline if the sample's error rate holds in the halt regions (a conditional, not a correction)
const haltIf = (h, o) => h && ok(h.perennial_ha) && o && ok(o.over)
  ? `if the same error rate holds in the halt regions, the baseline would be about ${sig(h.perennial_ha * (1 - o.over))} ha rather than ${sig(h.perennial_ha)} ha` : "";
// What the interpreters saw on fields mapped as no crop (error_matrix_area_share row "fallow"): the share of that area
// that looked like a crop, and the commonest crop
function noCropSeen(b) {
  const row = obj(get(b, "error_matrix_area_share.fallow"));
  if (!row) return null;
  let tot = 0, crop = 0, top = null;
  Object.entries(row).forEach(([k, x]) => {
    if (!ok(x)) return;
    tot += x;
    if (k === "fallow" || k === "not_farmland") return;
    crop += x;
    if (!top || x > row[top]) top = k;
  });
  return tot > 0 && top ? { crop: crop / tot, top } : null;
}
// The second interpretation: consistency, not correctness
const agreeText = (ia) => ia && ok(ia.agreement) && ok(ia.n)
  ? `A second, separate interpretation of ${fmt(ia.n)} of the fields agreed on ${pct(ia.agreement)} of them${ok(ia.kappa) ? ` (kappa ${fmt(ia.kappa, 2)})` : ""}; both followed the same written guide, so this shows the labels are consistent, not that they are correct.` : "";
// The commonest thing the interpreters saw on fields mapped as perennial forage, as a share of that mapped area
// (error_matrix_area_share rows are the mapped class, columns what the interpreters saw)
function pfMix(b) {
  const em = obj(b && b.error_matrix_area_share), row = obj(em && em.perennial_forage);
  if (!row) return null;
  const xs = Object.entries(row).filter(([, x]) => ok(x)), tot = xs.reduce((t, [, x]) => t + x, 0);
  const top = xs.filter(([k]) => k !== "perennial_forage").sort((a, c) => c[1] - a[1])[0];
  return top && tot > 0 ? { key: top[0], share: top[1] / tot } : null;
}
// The design in plain words: only what the recorded design states, with the counts from the data. The interpreters were
// AI vision models working from a written guide: a methods disclosure, stated wherever the check is described.
function blindDesign(b) {
  const d = String(b.design || ""), ua = obj(b.users_accuracy) || {}, n = ok(b.labelled) ? b.labelled : b.cards;
  if (!ok(n)) return "";
  const ns = Object.values(ua).map((x) => obj(x) ? x.n : null).filter(ok).sort((a, c) => a - c);
  const per = ns.length ? ns[Math.floor(ns.length / 2)] : null, mh = minHa(b), ls = /ndvi|landsat/i.test(d), s2 = /sentinel/i.test(d);
  return `Interpreters (AI vision models, separate from the classifier, working blind from a written guide and never shown the map's labels) named the crop type of ${fmt(n)} fields drawn at random${ok(per) ? `, about ${fmt(per)} from each mapped crop type` : " from each mapped crop type"}` +
    `${ok(mh) ? ` (fields of ${fmt(mh)} ha or more)` : ""}${/exclud/i.test(d) ? ", none of them among the fields used to tune the crop rules" : ""}.` +
    `${ls && s2 ? " For each field they looked at its Landsat greenness through the season and Sentinel-2 true-colour images." : ""}` +
    `${ls ? ` They saw the same Landsat record the map is built from, so errors in that record are not caught and the accuracy is an upper bound${s2 ? "; the Sentinel-2 images are the independent part." : "."}` : ""}`;
}

/* ---------- Checks ---------- */
function blindHtml(b) {
  if (!obj(b)) return `<p class="note">A blind visual check of a stratified sample of fields is in progress; its result will be added here when it is complete. It is visual interpretation of satellite images, not field visits.</p>`;
  const UA = obj(b.users_accuracy) || {}, PA = obj(b.producers_accuracy) || {}, ia = obj(b.interpreter_agreement), mh = minHa(b);
  const cl = obj(b.coarse_legend), cu = obj(cl && cl.users_accuracy) || {}, gr = obj(cl && cl.groups) || {}, GN = groupNames(gr);
  const gk = [...GROUP_ORDER.filter((k) => k in gr || ok(cu[k])), ...[...new Set([...Object.keys(gr), ...Object.keys(cu)])].filter((k) => !GROUP_ORDER.includes(k))];
  const gName = (k) => GN[k] || cap1(String(k).replace(/_/g, " "));
  const gRows = gk.filter((k) => ok(cu[k]));
  const name = (k) => SHORT[k] ? `${cs(k)} ${esc(SHORT[k])}` : esc(cap1(String(k).replace(/_/g, " ")));
  const head = `<tr><th scope="col">Mapped as</th><th class="num" scope="col">Confirmed<span class="sub">user's accuracy</span></th><th class="num" scope="col">Found<span class="sub">producer's accuracy</span></th><th class="num" scope="col">Fields checked</th></tr>`;
  const row = (k) => {   // too few sampled fields: no confirmed share and no found share either
    const u = obj(UA[k]) || {}, r = ciRange(u.value, u.ci95), few = ok(u.n) && u.n < FEW;
    return `<tr><td>${name(k)}</td><td class="num">${few ? `–<span class="sub">too few fields</span>` : `${pct(u.value)}${r ? `<span class="sub">${r}</span>` : ""}`}</td><td class="num">${few ? "–" : pct(PA[k])}</td><td class="num">${fmt(u.n)}</td></tr>`;
  };
  const three = ["perennial_forage", "winter_cereal", "tree_crop"].filter((k) => (obj(UA[k]) && ok(UA[k].value)) || ok(PA[k]));
  const every = Object.keys(UA).filter((k) => obj(UA[k]) && ok(UA[k].value)).sort((a, c) => UA[c].value - UA[a].value);
  const po = pfOver(b), mix = pfMix(b), design = blindDesign(b), agree = agreeText(ia), hi = haltIf(obj(SUM().halt), po).replace(/the baseline/, "the fodder-halt baseline");
  // the mix-up as a count of the sampled fields: an area share from two or three fields would look more precise than it is
  const pfN = ok(get(UA, "perennial_forage.n")) ? UA.perennial_forage.n : null, mixN = mix && ok(pfN) ? Math.round(mix.share * pfN) : null;
  return `${design ? `<p class="note">${esc(design)}</p>` : ""}
    ${meter("Mapped area where the interpreters saw the same crop type", b.overall_accuracy, pct(b.overall_accuracy),
      `${[ciText(b.overall_accuracy, b.overall_ci95), "weighted by mapped area"].filter(Boolean).join(", ")}.${ok(b.labelled) ? ` ${fmt(b.labelled)} fields labelled${ok(b.unsure) && b.unsure > 0 ? `, ${fmt(b.unsure)} marked unsure` : ""}.` : ""}`)}
    ${cl ? meter("Mapped area in the same broad group", cl.overall_accuracy, pct(cl.overall_accuracy), gk.length ? `With ${words(gk.length)} broad groups: ${list(gk.map((k) => esc(gName(k).toLowerCase())))}.` : "") : ""}
    ${gRows.length ? `<table><tr><th scope="col">Broad group</th><th class="num" scope="col">Mapped fields confirmed</th></tr>${gRows.map((k) => `<tr><td>${esc(gName(k))}</td><td class="num">${pct(cu[k])}</td></tr>`).join("")}</table>` : ""}
    ${three.length ? `<table>${head}${three.map(row).join("")}</table>
    <p class="note">Confirmed: of the sampled fields the map gave this crop type, the share the interpreters also gave it (95% interval underneath). Found: of the area the interpreters gave this crop type, the share the map also gave it, weighted by mapped area.</p>` : ""}
    ${po ? `<p class="note">Correcting the mapped area for the errors in the sample puts perennial forage at about <b>${sig(po.adj)} ha</b>${ok(po.ci) ? ` (95% interval ${sig(Math.max(0, po.adj - po.ci))} to ${sig(po.adj + po.ci)} ha)` : ""}, against ${sig(po.mapped)} ha mapped${ok(mh) ? ` in fields of ${fmt(mh)} ha or more` : ""}. ` +
      `${po.over >= 0.005 ? `${overText(po, true, true)}${hi ? `; ${hi}` : ""}.` : po.over <= -0.005 ? `The map may understate perennial forage by about ${pct(-po.over)}.` : "The mapped and corrected areas agree."}` +
      `${mix && ok(mixN) && mixN >= 1 ? ` The most common mix-up: ${words(mixN)} of the ${words(pfN)} sampled perennial-forage fields looked like ${noun(mix.key)} to the interpreters${mix.key === "winter_fodder" ? " (seasonal fodder, which the halt still allows)" : ""}.` : ""}</p>` : ""}
    ${agree ? `<p class="note">${esc(agree)}</p>` : ""}
    ${every.length ? `<details class="more"><summary>Every mapped crop type</summary><table>${head}${every.map(row).join("")}</table><p>A small sample gives a wide interval, and a crop type with very few fields gives no usable figure.</p></details>` : ""}
    <p class="note">This is visual interpretation of satellite images, not field visits.</p>`;
}
function gastatTable(rows) {
  const R = arr(rows).filter(obj);
  if (!R.length) return "";
  const cell = (m, o, f) => ok(m) && ok(o) && o > 0 ? `${fmt(m / o, 2)}×<span class="sub">${f(m)} / ${f(o)}</span>` : `–<span class="sub">${f(m)} / ${f(o)}</span>`;
  return `<table class="wide"><tr><th scope="col">Region</th><th class="num" scope="col">Winter cereal vs GASTAT wheat</th><th class="num" scope="col">Perennial forage (all stands) vs GASTAT fodder</th><th class="num" scope="col">Water, all crops, vs MEWA groundwater</th></tr>
    ${R.map((r) => `<tr><td>${esc(r.region)}${r.halt_region === true ? ` <span class="tag">halt</span>` : ""}</td><td class="num">${cell(r.mapped_winter_cereal_cycle_ha, r.gastat_wheat_ha, sig)}</td><td class="num">${cell(r.mapped_perennial_forage_ha, r.gastat_fodder_ha, sig)}</td><td class="num">${cell(r.water_bn_m3_central, r.mewa_agri_groundwater_bn_m3, bn)}</td></tr>`).join("")}</table>
    <p class="note">Ratio of mapped to official (mapped / official underneath; ha, and bn m³ a year for water). Above 1 means more mapped than reported. The definitions differ: winter-cereal cycles include barley, GASTAT's wheat does not; GASTAT's fodder includes seasonal fodder; MEWA's water covers every farm in the region, mapped or not, and the mapped water includes the Arabian Shield. Mapped perennial forage here includes stands that ended during the season, and the water is that of all crops; the Fodder halt tab counts only stands growing at season end, and their water.</p>`;
}
const QC_BAND = [0.6, 1.5];   // accepted observed-to-expected gap ratio on an overpass that sees both anchors (et_fields.py)
function ebQc(qc, regions) {
  const Q = Object.entries(obj(qc) || {}).filter(([, x]) => obj(x));
  if (!Q.length) return "";
  const acc = Q.reduce((t, [, x]) => t + (ok(x.accepted) ? x.accepted : 0), 0), all = Q.reduce((t, [, x]) => t + (ok(x.overpasses) ? x.overpasses : 0), 0);
  // boxes on the national default ratio (dT_src "national") are no check of themselves: out of the median and the outliers
  const ratios = Q.filter(([, x]) => ownGap(x)).map(([, x]) => x.dT_ratio).sort((a, b) => a - b);
  const dflt = Q.filter(([, x]) => x.dT_src === "national").length;
  const med = ratios.length ? (ratios.length % 2 ? ratios[(ratios.length - 1) / 2] : (ratios[ratios.length / 2 - 1] + ratios[ratios.length / 2]) / 2) : null;
  const far = Q.filter(([, x]) => ownGap(x) && Math.abs(Math.log(x.dT_ratio)) > Math.log(1.25)).sort((a, b) => Math.abs(Math.log(b[1].dT_ratio)) - Math.abs(Math.log(a[1].dT_ratio)));
  const gapCell = (x) => x.dT_src === "national" ? `<span class="sub">${DT_DEFAULT}</span>` : fmt(x.dT_ratio, 2);
  // boxes whose own median ratio is outside the acceptance band: most of their both-anchor overpasses were rejected
  const outBand = Q.filter(([, x]) => ownGap(x) && (x.dT_ratio < QC_BAND[0] || x.dT_ratio > QC_BAND[1])).map(([id]) => esc(id));
  // the default-ratio boxes' share of the mapped area and of the water (regions.json), and how many also take their
  // cold anchor from the national ratio in both halves of the season
  const D = Q.filter(([, x]) => x.dT_src === "national"), by = {};
  arr(regions).forEach((r) => { if (obj(r) && ok(r.area_ha) && ok(r.water_bn_m3_central)) by[r.id] = r; });
  const R = Object.values(by), A = R.reduce((t, r) => t + r.area_ha, 0), W = R.reduce((t, r) => t + r.water_bn_m3_central, 0);
  const ds = D.length && A > 0 && W > 0 && D.every(([id]) => by[id]) ? { area: D.reduce((t, [id]) => t + by[id].area_ha, 0) / A, water: D.reduce((t, [id]) => t + by[id].water_bn_m3_central, 0) / W } : null;
  const both = D.filter(([, x]) => { const c = obj(x.c_src) || {}; return c.winter === "national" && c.summer === "national"; }).length;
  return `<p class="note">${all > 0 ? `Each Landsat overpass of a box is kept only if at least 30% of the box is clear, no more than 5 mm of rain fell in the previous 5 days, the cold anchor sits inside the box's usual 5th to 95th percentile range (a screen for haze), and the hot-to-cold anchor gap is at least 6 K and, where both anchors are seen, ${fmt(QC_BAND[0], 1)} to ${fmt(QC_BAND[1], 1)} times the gap SSEBop's energy-balance physics expects: ${fmt(acc)} of ${fmt(all)} box overpasses (${pct(acc / all)}) passed.` : ""}` +
    `${ok(med) ? ` Across the ${fmt(ratios.length)} boxes with anchors of their own, the median ratio of observed to expected gap is ${fmt(med, 2)} (1 is a match)${far.length ? `; furthest from it: ${list(far.map(([id, x]) => `${esc(id)} (${fmt(x.dT_ratio, 2)})`))}.` : "."}` : ""}` +
    `${outBand.length ? ` ${list(outBand)}${outBand.length === 1 ? "'s own ratio is" : "'s own ratios are"} outside the accepted band, so ${outBand.length === 1 ? "its water rests" : "their water rests"} largely on fallback anchors.` : ""}` +
    `${dflt ? ` The ${fmt(dflt)} ${dflt === 1 ? "box that never observed both anchors on one overpass uses" : "boxes that never observed both anchors on one overpass use"} the national default ratio, which is not a check of ${dflt === 1 ? "that box" : "those boxes"}.` +
      `${ds ? ` ${dflt === 1 ? "It holds" : "They hold"} ${pct(ds.area, 1)} of the mapped area and ${pct(ds.water, 1)} of the water${both ? `; in ${both === dflt ? (dflt === 1 ? "it" : "all of them") : `${fmt(both)} of them`} the cold anchor itself is a national ratio times NASA POWER air temperature, so their water is less certain.` : "."}` : ""}` : ""}</p>
    <details class="more"><summary>Every box</summary><table><tr><th scope="col">Box</th><th class="num" scope="col">Overpasses kept</th><th class="num" scope="col">Gap ratio</th></tr>
      ${Q.map(([id, x]) => `<tr><td>${esc(id)}</td><td class="num">${fmt(x.accepted)} of ${fmt(x.overpasses)}</td><td class="num">${gapCell(x)}</td></tr>`).join("")}</table></details>`;
}
function renderChecks() {
  const el = $("p-checks");
  if (!el) return;
  const s = SUM(), v = obj(s.validation);
  if (!v) { el.innerHTML = `<p class="note">No checks in this data export.</p>`; return; }
  const ra = Object.entries(obj(v.radar_agreement_by_crop) || {}).filter(([, x]) => ok(x)).sort((a, b) => b[1] - a[1]);
  const t = obj(v.tier_ha) || {};
  el.innerHTML = `<p class="lead">None of these is a field visit. They test whether the crop calls hold up when the data are split or resampled, and whether independent satellites agree.</p>
    <h3>Stability</h3>
    ${meter("Landsat 8 alone and Landsat 9 alone give the same crop type", v.split_half_same_area_share, pct(v.split_half_same_area_share), ok(v.split_half_kappa) ? `Share of area; kappa ${fmt(v.split_half_kappa, 2)}. Each satellite's half of the record is classified on its own.` : "")}
    ${meter("Area whose crop type holds in at least 18 of 20 reruns", v.area_share_stability_ge_0_9, pct(v.area_share_stability_ge_0_9), ok(v.bootstrap_stability_median) ? `Each rerun drops a random 40% of the clear looks; the median field keeps its type in ${pct(v.bootstrap_stability_median)} of reruns.` : "")}
    ${stack([{ label: "Reliable", v: t.reliable, c: "var(--rb-mid)" }, { label: "Provisional", v: t.provisional, c: "var(--rb-thr)" }, { label: "Edge-mixed", v: t.edge_mixed, c: "var(--rb-factor)" }], (x) => `${fmt(x)} ha`)}
    <h3>Independent satellites</h3>
    ${meter("Sentinel-2 agrees on whether a field was bare in spring", v.spring_check_agreement, pct(v.spring_check_agreement), "Share of fields: Sentinel-2's own spring flag against the Landsat record.")}
    ${meter("NISAR radar agrees with the crop type", v.radar_agreement_area_share, pct(v.radar_agreement_area_share), "Share of tested area, in boxes and seasons where the radar passed its quality check.")}
    ${ra.length ? `<ul class="cbars">${ra.map(([k, x]) => `<li><div class="cb-head">${cs(k)}<span class="cb-name">${esc(SHORT[k] || k)}</span><span class="cb-num">${pct(x)}</span></div><div class="cb-bar" aria-hidden="true"><i style="--c:var(--c-crop-${esc(k)});--w:${(100 * x).toFixed(1)}%"></i></div></li>`).join("")}</ul><p class="note">Radar agreement by crop type, share of fields tested.</p>` : ""}
    <h3>Blind visual check</h3>
    ${blindHtml(v.blind_check)}
    <h3>Mapped against official 2024 statistics</h3>
    ${gastatTable(v.gastat_by_region)}
    <h3>Energy-balance check</h3>
    ${ebQc(get(s, "water.qc"), S.regions)}`;
}

/* ---------- Method ---------- */
function renderMethod() {
  const el = $("p-method");
  if (!el) return;
  const s = SUM(), cov = obj(s.coverage) || {}, inp = obj(s.inputs) || {};
  const b = blindOf(s), fa = obj(obj(b && b.users_accuracy) && b.users_accuracy.fallow), po = pfOver(b), seen = noCropSeen(b), nc = obj(get(s, "water.noncrop_et_bn_m3"));
  const ncEt = nc && ok(nc.central) ? ` (their evapotranspiration, about ${bn(nc.central)} bn m³ a year, is not counted)` : "";
  const hi = haltIf(obj(s.halt), po).replace(/the baseline/, "the fodder-halt baseline");
  el.innerHTML = `<ol class="steps">
      <li><b>Fields.</b> Field outlines come from ESA Sentinel-2 imagery. The country is processed in farming boxes${ok(cov.boxes_processed) && ok(cov.boxes_total) ? `; ${fmt(cov.boxes_processed)} of ${fmt(cov.boxes_total)} are in this record${boxCover(cov) ? `, and they${boxCover(cov)}` : ""}` : ""}. ${OUTSIDE}</li>
      <li><b>Crop type.</b> Each field's Landsat 8 and 9 greenness (NDVI) over the season is split into crop cycles: when each greens up and ends, and how long it stays green. The pattern gives the crop type: a long stand cut and regrown is perennial forage, one winter cycle is a winter cereal, green all year is a tree crop. Each call gets a confidence.</li>
      <li><b>Radar evidence.</b> NISAR L-band radar (NASA and ISRO) sees crop canopy through cloud and dust. Where it passed its quality check for a season, its canopy call is compared with what the crop type implies for that season. It is a separate sensor, though its green/bare threshold is set against Landsat looks. Radar is not used to estimate water.</li>
      <li><b>Water from heat.</b> Landsat surface temperature, corrected for emissivity and for hot desert blending into field edges, places each field between a cold anchor (fully green field interiors) and a hot anchor (bare fields) on every clear overpass. That fraction, carried through the season, multiplies 1.2 times the reference evapotranspiration (SSEBop's scaling for a grass reference; 1.1 in the low estimate), computed with FAO-56 from NASA POWER daily weather and adjusted for desert air (FAO-56 Annex 6). Fields without their own heat samples get the fraction from their greenness, calibrated on thermal fields in the same box; tree crops without them use a crop coefficient.</li>
      <li><b>Net and gross.</b> Net consumptive use subtracts effective rain; gross abstraction adds irrigation losses. Water on the sedimentary shelf is counted as groundwater; in the six western and south-western regions (mostly the Arabian Shield and the Red Sea coastal plain) its source is not determined. Evapotranspiration of fields mapped as having no crop is not counted. Low and high values vary the reference-evapotranspiration scaling and the irrigation efficiency; errors in the heat anchors and in the crop map are not in the range.</li>
      <li><b>Cross-checks.</b> The v1 method (mapped area times a benchmark depth per crop) is kept beside the heat-based figure, with MEWA's 2024 figures for context.</li>
      <li><b>Residues.</b> Straw from the area of winter-cereal cycles; fronds from GASTAT's date-palm count; both with low and high residue factors. Biochar carbon removal is a technical potential at a collected share; no plants exist or are planned.</li>
      <li><b>Checks.</b> Landsat 8 against Landsat 9, reruns on random subsets of the looks, Sentinel-2's spring flag, the NISAR radar, GASTAT and MEWA statistics, and a blind visual check of a sample by AI vision models working from a written guide, where available (see the Checks tab).</li>
    </ol>
    <h3>Limits</h3>
    <ul class="plain">
      <li><b>One optical series.</b> The crop calls rest on Landsat alone; clouds and gaps leave some fields with too few clear looks.</li>
      <li><b>One season.</b> Stand age and rotations need more seasons.</li>
      <li><b>No field visits.</b> The checks are agreement between methods and satellites; the blind check is visual interpretation of satellite images by AI vision models working from a written guide, not ground truth.</li>
      ${fa && ok(fa.value) ? `<li><b>The no-crop class is weak.</b> In the blind check only ${pct(fa.value)}${ciRange(fa.value, fa.ci95) ? ` (95% interval ${ciRange(fa.value, fa.ci95)})` : ""} of fields mapped as having no crop this season were judged to have none${seen ? `; about ${pct(seen.crop)} of that area looked like a crop to the interpreters, most often ${noun(seen.top)}, so some irrigation on them is missed${ncEt}.` : `, so some irrigation on them may be missed${ncEt}.`}</li>` : ""}
      ${po && po.over >= 0.005 ? `<li><b>Perennial forage may be overstated.</b> The blind check, a national sample, suggests ${overText(po)}${hi ? `; ${hi}` : ""}.</li>` : ""}
      <li><b>Coverage.</b> ${OUTSIDE}</li>
      <li><b>Water is an estimate.</b> Scaling reference evapotranspiration for desert air is the largest single uncertainty.</li>
      <li><b>Keyboard.</b> With a keyboard, choose a box from the Box list; its largest fields are listed in the box details, and other fields need a pointer.</li>
    </ul>
    <h3>Data and licences</h3>
    <p class="note">Landsat 8/9 Collection 2 (USGS/NASA, via Microsoft Planetary Computer); NASA POWER daily weather; NASA-ISRO NISAR (ASF DAAC); ESA Sentinel-2 and WorldCover; Copernicus DEM; GASTAT 2024 agricultural statistics; MEWA 2024 water figures; OpenStreetMap contributors (ODbL); geoBoundaries; Natural Earth. Map imagery © Esri, Maxar, Earthstar Geographics.</p>
    ${Object.keys(inp).length ? `<details class="more"><summary>Input fingerprints for this export${s.generated ? ` (${esc(dateText(s.generated) || s.generated)})` : ""}</summary><ul class="mono-list">${Object.entries(inp).map(([k, x]) => `<li>${esc(k)}: ${esc(x == null ? "–" : x)}</li>`).join("")}</ul></details>` : ""}
    <p class="note">Code and data: <a href="https://github.com/khalidmelo/circle-to-char" rel="noopener">github.com/khalidmelo/circle-to-char</a></p>`;
}

/* ====================================================================================================
   Start
   ==================================================================================================== */
function wire() {
  document.querySelectorAll("[data-colour]").forEach((b) => b.addEventListener("click", () => setColour(b.dataset.colour)));
  const lg = $("legend");
  if (lg) lg.addEventListener("click", (e) => {
    const b = e.target.closest && e.target.closest("button");
    if (!b) return;
    if (b.dataset.all) { setShow(null); const f = document.querySelector("#legend button[data-crop]") || $("keybtn"); if (f) f.focus(); return; }
    const c = Number(b.dataset.crop);
    if (b.dataset.crop != null && ok(c)) toggleCrop(c);
  });
  const kb = $("keybtn");
  if (kb) kb.addEventListener("click", () => setKeyOpen(!S.keyOpen));
  const bb = $("backbtn");
  if (bb) bb.addEventListener("click", back);
  const dl = $("detailslink");
  if (dl) dl.addEventListener("click", (e) => { const p = $("regionpanel"); if (p && !p.hidden) { e.preventDefault(); p.scrollIntoView({ behavior: REDUCE ? "auto" : "smooth", block: "start" }); p.focus({ preventScroll: true }); } });
  const aside = $("panel");
  if (aside) aside.addEventListener("click", (e) => {
    const b = e.target.closest && e.target.closest("button[data-act]");
    if (!b) return;
    if (b.dataset.act === "forage") { setColour("crop"); setShow(new Set([1])); }
    if (b.dataset.act === "water") setColour("water");
    toMap(() => { if (map && S.home && !S.current) fit(S.home); });
  });
}
async function loadFields() {
  S.total = S.regions.length;
  S.loaded = 0;
  setBusy(`Loading fields: 0 of ${S.total} boxes`);
  await Promise.all(S.regions.map((r, ri) => j(`${V2}fields/${encodeURIComponent(r.id)}.json`)
    .then((rows) => { safe("fields " + r.id, () => addRows(ri, arr(rows))); })
    .catch(() => { S.failed.push(r.id); })
    .then(() => { S.loaded++; if (!S.hintGone) setBusy(`Loading fields: ${S.loaded} of ${S.total} boxes`); redraw(); })));
  if (S.failed.length) setHint(`Fields for ${S.failed.length} ${S.failed.length === 1 ? "box" : "boxes"} could not load (${S.failed.sort().join(", ")}). Reload to try again.`, true);
  else if (!S.hintGone) setHint(NO_HOVER ? "Tap a box, then a field" : "Click a box, then a field");
  if (S.current) safe("region panel", () => renderRegionPanel(S.current), "regionpanel");   // a box opened while loading now lists its fields
}
function addRows(ri, rows) {
  rows.forEach((row) => {
    if (!Array.isArray(row) || row.length < 4) return;
    const lon = row[0], lat = row[1];
    if (!ok(lon) || !ok(lat) || Math.abs(lat) > 85) return;
    const ha = ok(row[2]) && row[2] > 0 ? row[2] : 0, sn = Math.sin(lat * Math.PI / 180);
    F.lon.push(lon); F.lat.push(lat);
    F.x.push((lon + 180) / 360);
    F.y.push(0.5 - Math.log((1 + sn) / (1 - sn)) / (4 * Math.PI));
    F.rm.push(Math.sqrt(ha * 1e4 / Math.PI));
    F.ic.push(1 / Math.cos(lat * Math.PI / 180));
    F.ha.push(ha);
    F.crop.push(ok(row[3]) && CROP_KEY[row[3]] ? row[3] : 0);
    F.et.push(ok(row[4]) ? row[4] : null);
    F.w.push(ok(row[5]) ? row[5] : null);
    F.conf.push(ok(row[6]) ? row[6] : 0);
    F.meth.push(ok(row[7]) ? row[7] : 0);
    F.reg.push(ri);
    F.n++;
  });
}
function renderAll() {
  safe("crops", renderCrops, "p-crops");
  safe("halt", renderHalt, "p-halt");
  safe("water", renderWater, "p-water");
  safe("residues", renderResidues, "p-residues");
  safe("checks", renderChecks, "p-checks");
  safe("method", renderMethod, "p-method");
}
async function init() {
  readColours();
  initTabs();
  wire();
  safe("map", makeMap);
  setKeyOpen(!(window.innerWidth > 860 && window.innerHeight <= 720));
  let sum = null, regs = null;
  try { [sum, regs] = await Promise.all([j(V2 + "summary.json"), j(V2 + "regions.json")]); } catch (e) {
    setHint(`Could not load the national record (${e.message}).`, true);
    ["p-crops", "p-halt", "p-water", "p-residues", "p-checks", "p-method"].forEach((id) => { const x = $(id); if (x) x.innerHTML = failHtml("Could not load the national record. Reload the page to try again."); });
    return;
  }
  S.sum = obj(sum) || {};
  S.crops = arr(S.sum.crops).filter((c) => obj(c) && ok(c.code) && typeof c.key === "string" && CROP_KEY[c.code] === c.key);
  S.regions = arr(regs).filter((r) => obj(r) && typeof r.id === "string" && Array.isArray(r.bbox) && r.bbox.length === 4 && r.bbox.every(ok));
  safe("title", () => { const e = $("h-season"), l = seasonLabel(S.sum.season); if (e && l) e.textContent = l; });
  renderAll();
  safe("legend", renderLegend, "legend");
  if (!map) { setHint("The map library did not load; the figures in the panel do not need it.", true); return; }
  safe("regions", drawRegions);
  safe("select", fillRegionSelect);
  map.invalidateSize();
  if (S.home) fit(S.home, false);
  await loadFields();
}
init().catch((e) => { if (window.console) console.error("national: init", e); setHint("Something went wrong while loading the page.", true); });
