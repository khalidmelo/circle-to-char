/* SkyMeter: Qassim deep dive. Reads precomputed JSON from data/ (and data/national/ for the comparison note).
   Every figure on the page comes from those files; a missing key hides or degrades its element instead of throwing. */
"use strict";

// Data colours: the same values as the --c-* tokens in style.css (one meaning per colour on every page).
const COLORS = { winter_only: "#eda100", wheat_rotation: "#b23a00", summer_only: "#3b7dd8", year_round: "#2e9e5b", palm_grove: "#4a2c0f", idle: "#9aa0a6" };
const MARK = { soil: "#0f6e6a", cement: "#5b2c83" };          // dashed square = hypothetical biochar plant by char outlet; solid ring = real cement plant
const FEED_COL = { straw: COLORS.winter_only, fronds: COLORS.palm_grove };  // a feed takes the colour of the fields it comes from
const CLASS_NAME = { winter_only: "Winter only (wheat)", wheat_rotation: "Wheat, then summer crop", summer_only: "Summer only", year_round: "Year-round (fodder)",
  palm_grove: "Palm groves", idle: "Not detected by radar" };
const CLASS_HELP = {
  winter_only: "Radar sees a crop in winter only; treated as wheat.",
  wheat_rotation: "Farmed in both seasons and brown in late spring (national spring check): wheat, then a summer crop.",
  summer_only: "Radar sees a crop in summer only.",
  year_round: "Farmed in both seasons and green in late spring, or with no spring check: perennial fodder, mostly alfalfa.",
  palm_grove: "Tree cover of 30% or more and farmed in both seasons.",
  idle: "Below the radar threshold in both seasons, though Sentinel-2 saw it green at some point: most such fields are radar misses, not idle land.",
};
const FARMED = ["winter_only", "wheat_rotation", "summer_only", "year_round", "palm_grove"];
const CLASSES = [...FARMED, "idle"];
const WINTER_ON = new Set(["winter_only", "wheat_rotation", "year_round", "palm_grove"]);   // radar farmed in winter
const SUMMER_ON = new Set(["summer_only", "wheat_rotation", "year_round", "palm_grove"]);   // radar farmed in summer
const WHEAT = new Set(["winter_only", "wheat_rotation"]);
const TWO_SEASON = new Set(["wheat_rotation", "year_round", "palm_grove"]);
const LEVEL_NAME = { low: "Low", central: "Central", high: "High" };
// National field codes that count as farmed (scripts/export_national.py CODES): winter only, summer only, year-round,
// palm grove, wheat rotation, one season observed and farmed.
const NATIONAL_FARMED = new Set([1, 2, 3, 4, 6, 7]);
// A 26.6 ha winter-only pivot whose radar and Sentinel-2 agree; replaced by the largest such field if the id changes.
const EXAMPLE_FIELD = 3175;
// Share of the 16,103 field-sized desert patches whose seasonal peak beats the threshold, recomputed from the GCOV
// rasters for these thresholds by the data audit (tx-4, qd-5). Not in any JSON: validation.desert_exceedance is read
// first if the pipeline exports it; this fallback is shown only while the published thresholds match.
const DESERT_EXCEED = { thr: { winter: 2.64, summer: 1.96 }, share: { winter: 0.1515, summer: 0.2046 } };
// Feeds of the deep-dive siting, and each char's soil-use status (summary.soil_use, Puro.earth 2025 Table 3.3 limits)
const FEEDS = [["straw", "Wheat straw", "straw char"], ["fronds", "Palm fronds", "frond char"]];
const SOIL_STATUS = { pass: "passes (measured)", unmeasured: "not yet measured", uncertain: "uncertain", excluded: "excluded" };
const soilStatus = (s) => SOIL_STATUS[s] || String(s || "–");
// Colour scale of each overlay group, as scripts/export_web.py renders it (the legend strings do not hold the ends).
const RAMPS = {
  "NISAR HV backscatter": { stops: ["#000000", "#ffffff"], lo: "−28 dB (bare)", hi: "−12 dB (crop canopy)" },
  "NISAR 12-day coherence": { stops: ["#000004", "#51127c", "#b73779", "#fc8961", "#fcfdbf"], lo: "0 (surface changed)", hi: "1 (unchanged)" },
  "NISAR soil moisture": { stops: ["#f7fbff", "#c6dbef", "#6baed6", "#2171b5", "#08306b"], lo: "0", hi: "0.4 m³/m³",
    note: "Read it for broad wet and dry patches, not single fields; diagonal stripes on some dates are not field patterns." },
  "Sentinel-2 greenness (ESA)": { stops: ["#ffffe5", "#d9f0a3", "#78c679", "#238443", "#004529"], lo: "NDVI 0 (bare)", hi: "0.8 (green)" },
};
// Field-chart colours, read from the style.css tokens when the first chart is drawn: HV (the signal the rule uses) in
// the accent, HH de-emphasised in the label grey with open points, single-series charts in secondary ink.
const CH = { hv: "#1d56a8", hh: "#5a6773", ink: "#3d4b58", muted: "#5a6773", grid: "#e3e7eb", axis: "#cdd4db", title: "#0e1a26", panel: "#ffffff" };
function chartTokens() {
  const cs = getComputedStyle(document.body), v = (n) => (cs.getPropertyValue(n) || "").trim();
  [["hv", "--accent"], ["hh", "--muted"], ["ink", "--ink-2"], ["muted", "--muted"], ["grid", "--line"], ["axis", "--line-2"], ["title", "--ink"], ["panel", "--panel"]]
    .forEach(([k, n]) => { const c = v(n); if (c) CH[k] = c; });
}
const ICO = (id, cls = "") => `<svg class="ico${cls ? " " + cls : ""}" aria-hidden="true"><use href="img/icons.svg#i-${id}"/></svg>`;
const DAY = 864e5;
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MONTH = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

const state = { level: "central", size: 10, group: null, overlays: [], current: null, layer: null, pending: null, ovSeq: 0, firstImage: false,
  fieldsLayer: null, plantLayer: null, plantSites: new Map(), cementLayer: null, cementHalo: null, byId: {}, selLyr: null, fieldShown: null,
  summary: null, fields: null, ts: null, tsPromise: null, charts: [], national: null, idleGreen: undefined,
  autoView: false, userMoved: false, fitSize: null, rzFrame: 0, rzTimer: 0, keyTouched: false };

/* ---------- helpers ---------- */
const $ = (id) => document.getElementById(id);
const num = (v) => (v == null || v === "" || isNaN(v)) ? null : Number(v);
const fmt = (v, d = 0) => {
  const x = num(v);
  if (x == null) return "–";
  const y = Number(x.toFixed(d)) === 0 ? 0 : x;   // no "-0.00" (qassim-15)
  return y.toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d }).replace(/^-/, "−");
};
const pct = (x, d = 0) => num(x) == null ? "–" : fmt(100 * x, d) + "%";
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const get = (o, ...path) => path.reduce((a, k) => (a == null ? undefined : a[k]), o);
const obj = (o) => (o && typeof o === "object" && !Array.isArray(o) ? o : null);
const sum = (a) => a.reduce((t, v) => t + (num(v) || 0), 0);
const list = (a) => a.length < 2 ? a.join("") : `${a.slice(0, -1).join(", ")} and ${a[a.length - 1]}`;
const pick = (o, keys) => { for (const k of keys) if (o && o[k] && typeof o[k] === "object") return o[k]; return null; };
const cname = (c) => CLASS_NAME[c] || String(c || "unknown").replaceAll("_", " ");
const isDate = (d) => /^\d{4}-\d{2}-\d{2}$/.test(String(d));
const tOf = (d) => Date.parse(d + "T00:00:00Z");
const seasonOf = (d) => (d === "winter" || d === "summer") ? d : ((m) => (m >= 4 && m <= 10 ? "summer" : "winter"))(+String(d).slice(5, 7));
const dayLabel = (d) => { const t = new Date(tOf(d)); return isNaN(t) ? String(d) : `${t.getUTCDate()} ${MON[t.getUTCMonth()]} ${t.getUTCFullYear()}`; };
const dayLong = (d) => { const t = new Date(tOf(d)); return isNaN(t) ? String(d) : `${t.getUTCDate()} ${MONTH[t.getUTCMonth()]}`; };
const mq = (q) => !!(window.matchMedia && window.matchMedia(q).matches);
const narrow = () => mq("(max-width: 860px)");
const coarse = mq("(pointer: coarse)"), canHover = mq("(hover: hover)"), reduceMotion = mq("(prefers-reduced-motion: reduce)");
const idle = (fn) => (window.requestIdleCallback ? window.requestIdleCallback(() => fn(), { timeout: 3000 }) : setTimeout(fn, 600));
// Data strings shown as prose (qassim-9): drop code references such as "(model/params.json)" clause by clause, name
// factors and flags by their labels, and write the arithmetic with proper signs.
const CODE_WORD = { s2_winter_active: "the winter Sentinel-2 flag", s2_summer_active: "the summer Sentinel-2 flag",
  s2_winter_check: "the winter Sentinel-2 check", s2_summer_check: "the summer Sentinel-2 check",
  elec_kwh: "the pumping electricity", water_m3: "the pumped water",
  straw_factor_seasons: "the region's season-fill straw factor", straw_factor_s2_only: "the region's Sentinel-2-only straw factor" };
const isCode = (c) => /\b(?:model|scripts|data|out)\/|\.(?:py|json|csv|tif)\b|\b\w*_\w*\.\w|\b\w+\.\w*_/.test(c) || /^\s*[a-z0-9]+(?:_[a-z0-9]+)+\s*$/.test(c);
const labelOf = (k) => CODE_WORD[k] || (PARAM_LABEL[k] ? PARAM_LABEL[k].replace(/\s*\(.*\)$/, "").replace(/^./, (c) => c.toLowerCase()) : k);
const plain = (s) => String(s == null ? "" : s)
  // a code reference inside a clause goes first, so the clause around it survives the filter below
  // ("…Qassim lift, lift_m.Qassim of data/national/official_2024.json, at every level…" keeps "at every level")
  .replace(/,\s*[\w.]+ of (?:data|model|out)\/[\w./-]+/g, "")
  .replace(/\bdata\/national\/fields_national\.csv\b/g, "the national field table")
  // a parenthesis keeps its clauses without code; one with nothing left goes
  .replace(/\s*\(([^()]*)\)/g, (m, inner) => { const keep = inner.split(/;\s*/).filter((c) => !isCode(c)); return keep.length ? m.replace(inner, keep.join("; ")) : ""; })
  .replace(/\bThe rule of (?:model|scripts)\/[\w./]+ where it applies, /g, "The national rule where it applies, ")
  .replace(/\bmodel\/national_supply\.s2_tier\b/g, "the national radar + Sentinel-2 rule")
  .replace(/\b(?:model|scripts)\/[\w./]+(?:'s)?/g, "the pipeline")
  .replace(/\b[a-z0-9]+(?:_[a-z0-9]+)+\b/g, labelOf)
  .replace(/\b([a-z][a-z -]*[a-z]) \(\1, /gi, "$1 (")          // "static depth to water (static depth to water, Buraidah …" becomes "static depth to water (Buraidah …"
  .replace(/ x /g, " × ").replace(/\brho g\b/g, "ρg").replace(/ - /g, " − ")   // " / " stays: sources use it between low, central and high values
  .replace(/(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)/g, (m, a, b, i, str) => /[\d-]/.test(str[i - 1] || "") || /[\d-]/.test(str[i + m.length] || "") ? m : `${a}–${b}`)
  .replace(/(\d{1,2} [A-Z][a-z]{2})-(\d{1,2} [A-Z][a-z]{2})\b/g, "$1–$2").replace(/(\d) C\b/g, "$1 °C")
  .replace(/(^|[\s({])-(\d)/g, "$1−$2").replace(/\bCO2\b/g, "CO₂").replace(/\bm3\b/g, "m³")
  .replace(/ {2,}/g, " ").replace(/ ([,.;:])/g, "$1").trim();
function safe(fn, el) {
  try { return fn(); } catch (e) {
    console.error(e);
    const box = el && $(el);
    if (box) box.innerHTML = `<p class="alert" role="alert">${ICO("alert")}<span>This part could not be shown (${esc(e.message)}).</span></p>`;
  }
}

/* ---------- map ---------- */
// trackResize off: onResize() below resizes the map itself, so a window resize does not count as the reader moving it.
const map = L.map("map", { zoomControl: true, zoomSnap: 0.25, trackResize: false, renderer: L.canvas({ tolerance: coarse ? 10 : 3 }) }).setView([26.33, 43.52], 10);
L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
  maxZoom: 17, attribution: "Imagery © Esri, Maxar, Earthstar Geographics",
}).addTo(map);
map.createPane("imagery").style.zIndex = 350;   // satellite overlays: above the basemap, below field outlines and plants

async function getJSON(p) { const r = await fetch(p); if (!r.ok) throw new Error(p); return r.json(); }

async function init() {
  const [ov, sm, fl, ce] = await Promise.allSettled([getJSON("data/overlays.json"), getJSON("data/summary.json"),
    getJSON("data/fields.geojson"), getJSON("data/cement.geojson")]);
  if (sm.status !== "fulfilled") throw sm.reason;
  if (fl.status !== "fulfilled") throw fl.reason;
  state.summary = sm.value && typeof sm.value === "object" ? sm.value : {};
  state.fields = fl.value;
  if (!state.fields || !Array.isArray(state.fields.features)) throw new Error("data/fields.geojson holds no fields");
  state.overlays = ov.status === "fulfilled" && Array.isArray(ov.value) ? ov.value.filter((o) => o && o.group && o.file && o.bounds) : [];
  if (ce.status === "fulfilled") safe(() => addCement(ce.value));

  wire();
  drawFields();
  raiseMarkers();   // the cement rings went onto the shared canvas first: keep them above the field outlines
  safe(buildKeys);
  safe(setupGroups, "legendtext");   // fills the colour ramp and legend, so the map-tools card has its final height before the fit
  safe(renderStamp);
  autoView(() => map.invalidateSize({ pan: false }));
  foldKey();
  $("mapkey")?.querySelector("summary")?.addEventListener("click", () => { state.keyTouched = true; });
  autoView(fitFields);
  map.on("movestart zoomstart", () => { if (!state.autoView) state.userMoved = true; });
  window.addEventListener("resize", onResize);
  safe(renderOverview, "lead"); safe(renderValidation, "validation"); safe(renderPlants, "plantlist");
  safe(renderSteps, "steps"); safe(renderDiffers, "differs"); safe(renderHead, "headinfo"); safe(renderParams, "params");
  $("loading")?.remove();

  const h = location.hash.slice(1);
  if ($("tab-" + h)) openTab(h, { hash: false, scroll: false });
  if (h === "field") showExample(true);
  idle(loadNational);
  setTimeout(loadTs, 5000);   // the per-field radar record (largest file, Field tab only): fetched after the first view
}

function wire() {
  $("group").onchange = (e) => { const keep = state.current ? oTime(state.current) : null; state.group = e.target.value; setupDates(keep); };
  $("date").oninput = showOverlay;
  $("opacity").oninput = () => { if (state.layer) state.layer.setOpacity(opacity()); };
  $("showfields").onchange = (e) => {
    if (!state.fieldsLayer) return;
    if (e.target.checked) { state.fieldsLayer.addTo(map); raiseMarkers(); } else map.removeLayer(state.fieldsLayer);
  };
  $("showplants").onchange = (e) => [state.cementHalo, state.cementLayer, state.plantLayer].forEach((l) => {
    if (l) e.target.checked ? l.addTo(map) : map.removeLayer(l);
  });
  document.addEventListener("click", onDocClick);
  $("examplefield").onclick = () => showExample(true);
  // Phones: the layer select, legend and map key fold under one "Map layers and key" button (desktop shows them all).
  $("mtmore").onclick = (e) => {
    const open = e.currentTarget.getAttribute("aria-expanded") !== "true";
    e.currentTarget.setAttribute("aria-expanded", open);
    $("maptools").classList.toggle("is-open", open);
  };
}
// The tabs work before the data arrives, so the Method tab stays readable if the results fail to load.
function wireTabs() {
  document.querySelectorAll(".tabs [data-tab]").forEach((b) => b.addEventListener("click", () => openTab(b.dataset.tab)));
  document.querySelector(".tabs")?.addEventListener("keydown", onTabKey);
  window.addEventListener("hashchange", () => {
    const n = location.hash.slice(1);
    if (!$("tab-" + n)) return;
    openTab(n, { hash: false });
    if (n === "field" && !state.fieldShown && state.fieldsLayer) showExample(true);
  });
}

function onDocClick(e) {
  const lv = e.target.closest(".level button[data-level]");
  if (lv) { setLevel(lv.dataset.level); return; }
  const sz = e.target.closest(".sizes button[data-size]");
  if (sz) { setSize(+sz.dataset.size); return; }
  const pc = e.target.closest("#plantlist .plant[data-plant]");   // a plant card (or its Show on map button): fly to its site
  if (pc && !e.target.closest("a, summary, details")) { goPlant(pc.dataset.plant); return; }
  const a = e.target.closest('a[href^="#"]');
  const name = a && a.getAttribute("href").slice(1);
  if (!a || !$("tab-" + name)) return;
  e.preventDefault();
  const target = a.dataset.target ? $(a.dataset.target) : null;   // a section further down the tab
  openTab(name, { scroll: !a.classList.contains("poplink") && !target });
  if (target) {
    const d = target.tagName === "DETAILS" ? target : target.querySelector("details");
    if (d) d.open = true;
    target.scrollIntoView({ block: "start" });   // a jump: the tab has just changed, so there is nothing to follow on the way
  }
  if (a.classList.contains("poplink")) {   // a link in a map popup: the reader asked to go to the panel (a plant: its card)
    map.closePopup();
    const card = a.dataset.plant ? highlightPlant(a.dataset.plant, false) : null;
    (card || document.querySelector("aside"))?.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
  }
}

/* ---------- tabs (S5: the URL hash follows the tab) ---------- */
function openTab(name, opts = {}) {
  if (!$("tab-" + name)) return;
  document.querySelectorAll(".tabs [data-tab]").forEach((b) => {
    const on = b.dataset.tab === name;
    b.classList.toggle("on", on); b.setAttribute("aria-selected", on); b.tabIndex = on ? 0 : -1;
    if (on) keepInStrip(b);
  });
  document.querySelectorAll(".tab").forEach((x) => { const on = x.id === "tab-" + name; x.classList.toggle("on", on); x.hidden = !on; });
  if (opts.hash !== false && location.hash.slice(1) !== name) { try { history.replaceState(null, "", "#" + name); } catch (e) { /* sandboxed */ } }
  const aside = document.querySelector("aside");
  if (aside) {
    if (!narrow()) aside.scrollTop = 0;   // a tab never opens mid-content
    else if (opts.scroll !== false && aside.getBoundingClientRect().top < 0) aside.scrollIntoView({ block: "start" });
  }
  if (name === "field") loadTs();
}
function keepInStrip(b) {
  const strip = b.parentElement;
  if (!strip || strip.scrollWidth <= strip.clientWidth) return;
  const l = b.offsetLeft, r = l + b.offsetWidth;
  if (l < strip.scrollLeft) strip.scrollLeft = l - 8;
  else if (r > strip.scrollLeft + strip.clientWidth) strip.scrollLeft = r - strip.clientWidth + 8;
}
function onTabKey(e) {
  const tabs = [...document.querySelectorAll(".tabs [role=tab]")], i = tabs.indexOf(document.activeElement);
  if (i < 0) return;
  const j = { ArrowRight: (i + 1) % tabs.length, ArrowLeft: (i - 1 + tabs.length) % tabs.length, Home: 0, End: tabs.length - 1 }[e.key];
  if (j == null) return;
  e.preventDefault(); tabs[j].focus(); openTab(tabs[j].dataset.tab);
}

/* ---------- estimate and plant size (S1: every copy of the switch follows the value) ---------- */
function setLevel(lv) {
  if (!LEVEL_NAME[lv]) return;
  state.level = lv;
  document.querySelectorAll(".level button[data-level]").forEach((x) => {
    const on = x.dataset.level === lv; x.classList.toggle("on", on); x.setAttribute("aria-pressed", on);
  });
  safe(renderOverview, "kpis"); safe(renderPlants, "plantlist"); safe(renderFieldInfo, "fieldinfo");
}
function setSize(n) {
  if (!n) return;
  state.size = n;
  document.querySelectorAll(".sizes button[data-size]").forEach((x) => {
    const on = +x.dataset.size === n; x.classList.toggle("on", on); x.setAttribute("aria-pressed", on);
  });
  safe(renderPlants, "plantlist");
}

/* ---------- satellite overlays ---------- */
const overlaysFor = (g) => state.overlays.filter((o) => o.group === g);
const opacity = () => (num($("opacity").value) ?? 85) / 100;
function seasonMid(season) {   // mean date of the overlays in a season, to keep the nearest date when the layer changes
  const t = state.overlays.filter((o) => isDate(o.date) && seasonOf(o.date) === season).map((o) => tOf(o.date));
  return t.length ? sum(t) / t.length : 0;
}
const oTime = (o) => isDate(o.date) ? tOf(o.date) : seasonMid(o.date);

function setupGroups() {
  const groups = [...new Set(state.overlays.map((o) => o.group))];
  const tools = document.querySelectorAll("#group, #date, #opacity");
  if (!groups.length) {
    tools.forEach((x) => { x.disabled = true; });
    $("legendtext").textContent = "No satellite layers could be loaded; the field map still works.";
    return;
  }
  $("group").innerHTML = groups.map((g) => `<option>${esc(g)}</option>`).join("");
  state.group = groups[0];
  setupDates(null);
}
function setupDates(keepT) {
  const list = overlaysFor(state.group), r = $("date");
  if ($("groupname")) $("groupname").textContent = state.group || "";   // the layer's name in the title, for phones (the select is folded)
  r.max = Math.max(0, list.length - 1);
  r.disabled = list.length < 2;
  let i = list.length - 1;
  if (keepT != null) {
    let best = Infinity;
    list.forEach((o, j) => { const d = Math.abs(oTime(o) - keepT); if (d < best) { best = d; i = j; } });
  }
  r.value = Math.max(0, i);
  safe(() => renderRuns(list));
  showOverlay();
}
// Under the date slider: one label per season run of images, placed under its first to last tick, with a tick per image.
// The slider steps image by image, so the runs are spaced by image count, not by calendar time.
function renderRuns(list) {
  const box = $("dateruns");
  if (!box) return;
  const n = list.length;
  if (n < 2) { box.innerHTML = ""; return; }
  const runs = [];
  list.forEach((o, i) => { const s = seasonOf(o.date); if (!runs.length || runs[runs.length - 1].s !== s) runs.push({ s, a: i, b: i }); else runs[runs.length - 1].b = i; });
  const f = (i) => (i / (n - 1)).toFixed(4), at = (i) => `calc(9px + (100% - 18px) * ${f(i)})`;   // 9 px: half the thumb
  const span = (r) => `width:calc((100% - 18px) * ${((r.b - r.a) / (n - 1)).toFixed(4)})`;
  const name = (r) => {
    const d = list.slice(r.a, r.b + 1).map((o) => o.date).filter(isDate);
    if (!d.length) return r.s.charAt(0).toUpperCase() + r.s.slice(1);
    const m0 = MON[+d[0].slice(5, 7) - 1], m1 = MON[+d[d.length - 1].slice(5, 7) - 1], y0 = d[0].slice(0, 4), y1 = d[d.length - 1].slice(0, 4);
    return m0 === m1 && y0 === y1 ? `${m0} ${y0}` : y0 === y1 ? `${m0}–${m1} ${y0}` : `${m0} ${y0} to ${m1} ${y1}`;
  };
  box.innerHTML = list.map((o, i) => `<i class="dl-tick" style="left:${at(i)}"></i>`).join("") +
    runs.map((r, k) => {   // the last run is set from its end, so its label ends under the last tick
      const end = runs.length > 1 && k === runs.length - 1;
      return `<span class="dl-run${end ? " end" : ""}" style="${end ? `right:calc(9px + (100% - 18px) * ${(1 - r.b / (n - 1)).toFixed(4)})` : `left:${at(r.a)}`};${span(r)}">${esc(name(r))}</span>`;
    }).join("");
}
function showOverlay() {
  const list = overlaysFor(state.group), i = +$("date").value, o = list[i];
  if (!o) return;
  state.current = o;
  const season = seasonOf(o.date);
  $("datelabel").innerHTML = isDate(o.date) ? `<span class="dl-date">${esc(dayLabel(o.date))}</span><span class="tag">${esc(season)}</span>` :
    `<span class="dl-date">${esc(season.charAt(0).toUpperCase() + season.slice(1))} season</span>`;
  $("date").setAttribute("aria-valuetext", `${isDate(o.date) ? dayLabel(o.date) + ", " + season : season + " season"}, image ${i + 1} of ${list.length}`);
  updateLegend(o);
  // Keep the current image until the next one has loaded, so the map never flashes bare (qassim-14).
  const tok = ++state.ovSeq;
  if (state.pending) { map.removeLayer(state.pending); state.pending = null; }
  const next = L.imageOverlay("data/overlays/" + o.file, o.bounds, { opacity: 0, pane: "imagery" });
  state.pending = next;
  next.once("load", () => {
    if (tok !== state.ovSeq) return;
    state.pending = null;
    next.setOpacity(opacity());
    if (state.layer) map.removeLayer(state.layer);
    state.layer = next;
    if (!state.firstImage) { state.firstImage = true; idle(loadTs); }
  });
  next.once("error", () => {
    if (tok !== state.ovSeq) return;
    state.pending = null;
    map.removeLayer(next);
    $("legendtext").textContent = `This image could not be loaded (${o.file}).`;
  });
  next.addTo(map);
}
function updateLegend(o) {
  const r = RAMPS[o.group];
  $("ramp").hidden = $("rampends").hidden = !r;
  if (r) {
    $("ramp").style.setProperty("--ramp", r.stops.join(","));
    $("ramplo").textContent = r.lo; $("ramphi").textContent = r.hi;
  }
  const raw = r ? legendExtra(String(o.legend || "")) : String(o.legend || "");   // the ramp's ends already give the range
  const text = raw.replace(/\bHV gamma0\b/, "HV backscatter (gamma0)").replace(/m3\/m3/g, "m³/m³").replace(/(^|[\s(])-(\d)/g, "$1−$2");
  $("legendtext").textContent = [text, r && r.note].filter(Boolean).map((s, i, a) => i < a.length - 1 && !/[.!?]$/.test(s) ? s + "." : s).join(" ");
}
// A layer's legend string without the value range the colour ramp shows, and without the quantity's name before it:
// "Coherence 0 (surface changed) to 1 (unchanged). Note: sand itself…" keeps "Sand itself…"; "… 0 to 0.4 m3/m3 (200 m)"
// keeps "On a 200 m grid". A string with no range ("Maximum NDVI, winter season") is kept whole.
function legendExtra(s) {
  const v = "[−-]?\\d+(?:\\.\\d+)?(?:\\s*(?:dB|m³\\/m³|m3\\/m3))?(?:\\s*\\((?!\\d)[^)]*\\))?";
  const RNG = new RegExp(`,?\\s*${v}\\s+to\\s+${v}`);
  if (!RNG.test(s)) return s;
  return s.replace(RNG, "").replace(/^[^.(]*/, "").replace(/^\.\s*/, "").trim()
    .replace(/^\((\d+(?:\.\d+)?) ?m\)\.?$/, "On a $1 m grid").replace(/^Note:\s*/i, "").replace(/^./, (c) => c.toUpperCase())
    .replace(/([^.!?])$/, "$1.");   // what is left reads as a sentence
}

/* ---------- fields ---------- */
function fieldClass(p) {
  if (!p) return "idle";
  const w = p.winter_active ?? p.s2_winter_active, s = p.summer_active ?? p.s2_summer_active;
  return p.class || (w && s ? "year_round" : w ? "winter_only" : s ? "summer_only" : "idle");
}
const fieldStyle = (p) => { const c = COLORS[fieldClass(p)] || COLORS.idle; return { color: c, weight: 1.2, opacity: 0.95, fillColor: c, fillOpacity: 0.08 }; };

function drawFields() {
  state.byId = {};
  state.fieldsLayer = L.geoJSON(state.fields, {
    style: (f) => fieldStyle(f.properties),
    onEachFeature: (f, lyr) => {
      const p = f.properties || {};
      state.byId[p.id] = lyr;
      if (canHover) lyr.bindTooltip(() => `<b>Field ${esc(p.id)}</b><br>${esc(cname(fieldClass(p)))}, ${fmt(p.area_ha, 1)} ha<br><span class="tt-hint">Click to zoom in and see its radar record</span>`, { sticky: true });
      lyr.on("click", (e) => {
        showField(p, true, lyr);
        const moved = zoomTo(lyr.getBounds(), 15, true);
        if (narrow()) afterMove(moved, () => fieldPopup(p, e.latlng));
      });
    },
  }).addTo(map);
}
// Padding that keeps a fit clear of the floating map tools (desktop): the fields go above the panel or beside it,
// whichever draws them larger. On phones the tools sit under the map, so the padding is even.
function fitOpts(b, pad = 12, maxZoom = Infinity) {
  const P = (x, y) => L.point(x, y), even = { paddingTopLeft: P(pad, pad), paddingBottomRight: P(pad, pad) };
  const t = $("maptools");
  if (narrow() || !t || !t.offsetHeight || !b || !b.isValid()) return even;
  const m = map.getContainer().getBoundingClientRect(), r = t.getBoundingClientRect();
  const above = { paddingTopLeft: P(pad, pad), paddingBottomRight: P(pad, Math.max(pad, Math.round(m.bottom - r.top) + pad)) };
  const beside = { paddingTopLeft: P(Math.max(pad, Math.round(r.right - m.left) + pad), pad), paddingBottomRight: P(pad, pad) };
  const z = (o) => Math.min(maxZoom, map.getBoundsZoom(b, false, o.paddingTopLeft.add(o.paddingBottomRight)));
  const room = (o) => { const p = o.paddingTopLeft.add(o.paddingBottomRight), s = map.getSize(); return (s.x - p.x) * (s.y - p.y); };
  const zb = z(beside), za = z(above);   // the same zoom either way (a small field at maxZoom): the side with more room
  return zb > za || (zb === za && room(beside) > room(above)) ? beside : above;
}
function fitFields() {
  const b = state.fieldsLayer && state.fieldsLayer.getBounds();
  if (b && b.isValid()) map.fitBounds(b, { ...fitOpts(b), animate: false });
  state.fitSize = map.getSize();
}
// Map moves made by the page (fit, resize) are not the reader's: they do not stop the refit after a resize.
function autoView(fn) { state.autoView = true; try { fn(); } finally { state.autoView = false; } }
// The map key is folded on a small desktop map, so the floating card leaves room for the fields; its "Map key" row
// stays visible. Once the reader opens or closes it, it stays. On phones it is always open, inside the "Map layers and
// key" fold (its own summary is hidden there).
function foldKey() {
  const k = $("mapkey");
  if (!k) return;
  if (narrow()) { k.open = true; return; }
  if (state.keyTouched) return;
  const ms = map.getSize();
  k.open = !(ms.x < 760 || ms.y < 620);
}
function onResize() {   // as Leaflet's own trackResize, then a debounced refit to the fields unless the reader has moved the map
  cancelAnimationFrame(state.rzFrame);
  state.rzFrame = requestAnimationFrame(() => autoView(() => map.invalidateSize({ debounceMoveend: true })));
  clearTimeout(state.rzTimer);
  state.rzTimer = setTimeout(() => {
    autoView(() => map.invalidateSize({ pan: false }));
    foldKey();
    const s = map.getSize(), f = state.fitSize;
    if (state.userMoved || !s.x || !s.y || (f && f.x === s.x && f.y === s.y)) return;
    autoView(fitFields);
  }, 250);
}
function select(lyr) {
  if (state.selLyr && state.selLyr !== lyr && state.fieldsLayer) state.fieldsLayer.resetStyle(state.selLyr);
  state.selLyr = lyr || null;
  if (lyr) { lyr.setStyle({ weight: 4, fillOpacity: 0.35 }); lyr.bringToFront(); raiseMarkers(); }
}
function raiseMarkers() {   // cement rings stay above field outlines (plant markers are in the marker pane, always on top)
  if (state.cementHalo && map.hasLayer(state.cementHalo)) state.cementHalo.bringToFront();
  if (state.cementLayer && map.hasLayer(state.cementLayer)) state.cementLayer.bringToFront();
}
function fieldPopup(p, latlng) {   // phones: a small popup, and the reader chooses to scroll to the panel
  if (!latlng) return;
  L.popup({ maxWidth: 240, autoPanPadding: [16, 16], autoPanPaddingTopLeft: [64, 16] }).setLatLng(latlng)
    .setContent(`<b>Field ${esc(p.id)}</b><br>${esc(cname(fieldClass(p)))}, ${fmt(p.area_ha, 1)} ha<br><a href="#field" class="poplink">See its radar record${ICO("chevron", "sm down")}</a>`)
    .openOn(map);
}

// Click-to-zoom: fly to a field, plant or list item, clear of the floating map tools; a jump when motion is reduced.
// keepZoom (a click on the map itself): never zoom out, and do not move at all when the target is already in view.
// Returns true when the map will fire moveend later (an animated move), so a popup can wait for it.
function zoomTo(b, maxZ, keepZoom = false) {
  if (!b || !b.isValid()) return false;
  const o = fitOpts(b, 24, maxZ), tl = o.paddingTopLeft, br = o.paddingBottomRight;
  const z = Math.min(maxZ, map.getBoundsZoom(b, false, tl.add(br)));
  if (keepZoom && map.getZoom() >= z - 0.01) {
    const px = map.latLngToContainerPoint(b.getCenter()), s = map.getSize();
    if (px.x >= tl.x && px.y >= tl.y && px.x <= s.x - br.x && px.y <= s.y - br.y) return false;
    map.panInside(b.getCenter(), { paddingTopLeft: tl, paddingBottomRight: br, animate: !reduceMotion });
    return !reduceMotion;
  }
  if (reduceMotion) { map.fitBounds(b, { ...o, maxZoom: maxZ, animate: false }); return false; }
  map.flyToBounds(b, { ...o, maxZoom: maxZ, duration: 0.8 });
  return true;
}
const afterMove = (moved, fn) => { if (moved) map.once("moveend", fn); else fn(); };
// Phones: the panel sits under the map, so bring the map into view (below the sticky bar) before it moves.
function showMapThen(fn) {
  const w = $("mapwrap");
  if (!narrow() || !w) { fn(); return; }
  const nav = document.querySelector("nav.site"), top = w.getBoundingClientRect().top - (nav ? nav.offsetHeight : 0);
  if (Math.abs(top) < 4) { fn(); return; }
  window.scrollTo({ top: window.scrollY + top, behavior: reduceMotion ? "auto" : "smooth" });
  setTimeout(fn, reduceMotion ? 0 : 450);
}

/* ---------- cement plants and map keys ---------- */
function addCement(gj) {
  if (!gj || !Array.isArray(gj.features)) return;
  const pts = gj.features.filter((f) => f && f.geometry && Array.isArray(f.geometry.coordinates));
  const label = (q) => {
    const name = [q.owner_name, q.city].filter(Boolean).join(", ");
    return `<b>Existing cement plant</b> (a real facility)${name ? "<br>" + esc(name) : ""}${num(q.cap) ? `, ${fmt(q.cap, 1)} Mt/y` : ""}`;
  };
  const ll = (f) => [f.geometry.coordinates[1], f.geometry.coordinates[0]];
  state.cementHalo = L.featureGroup(pts.map((f) => L.circleMarker(ll(f), { radius: 7, color: "#fff", weight: 5, opacity: 0.85, fill: false, interactive: false }))).addTo(map);
  state.cementLayer = L.featureGroup(pts.map((f) => L.circleMarker(ll(f), { radius: 7, color: MARK.cement, weight: 2.5, opacity: 1, fill: false })
    .bindTooltip(label(f.properties || {}))
    .on("click", (e) => zoomTo(e.target.getLatLng().toBounds(2000), 14, true)))).addTo(map);
}
function buildKeys() {
  const area = get(state.summary, "supply", "area_ha_by_class") || {};
  const seen = new Set(state.fields.features.map((f) => fieldClass(f.properties)));
  const shown = CLASSES.filter((c) => seen.has(c) || num(area[c]) > 0).concat([...seen].filter((c) => !CLASSES.includes(c)));
  $("fieldkey").innerHTML = shown.map((c) => `<li><i class="outline" style="--c:${COLORS[c] || COLORS.idle}" aria-hidden="true"></i>${esc(cname(c))}</li>`).join("");
  const outlets = new Set();
  Object.values(get(state.summary, "siting") || {}).forEach((a) => Array.isArray(a) && a.forEach((p) => p && outlets.add(p.best_outlet === "cement" ? "cement" : "soil")));
  if (!outlets.size) outlets.add("soil");
  const both = outlets.has("soil") && outlets.has("cement");   // name the outlet only when the map shows both
  $("plantkey").innerHTML = ["soil", "cement"].filter((o) => outlets.has(o)).map((o) =>
    `<li><i class="hypo" style="--c:${MARK[o]}" aria-hidden="true"></i>Hypothetical biochar plant site${both ? `, char ${o === "soil" ? "to the fields" : "to cement"}` : " (numbered)"}</li>`).join("") +
    (state.cementLayer ? `<li><i class="ring" style="--c:${MARK.cement}" aria-hidden="true"></i>Existing cement plant (real facility)</li>` : "");
}

/* ---------- Overview ---------- */
function idleGreenHa() {   // 'not detected' area that Sentinel-2 sees green over the radar's own dates
  if (state.idleGreen !== undefined) return state.idleGreen;
  let all = 0, green = 0, known = false;
  state.fields.features.forEach((f) => {
    const p = f.properties || {};
    if (fieldClass(p) !== "idle") return;
    all += num(p.area_ha) || 0;
    if (p.s2_winter_check != null || p.s2_summer_check != null) known = true;
    if (p.s2_winter_check || p.s2_summer_check) green += num(p.area_ha) || 0;
  });
  state.idleGreen = known ? { all, green } : null;
  return state.idleGreen;
}
function regionSentence() {
  const ids = (get(state, "national", "boxes") || []).map((r) => r.id);
  const where = ids.length ? `national region${ids.length > 1 ? "s" : ""} ${list(ids)}` : "the national run's Qassim regions";
  return `This 20 m close-up lies inside ${esc(where)}, which map the same area on a 40 m grid, so the two are not added together (<a href="#sources" data-target="differs-h">how they differ</a>).`;
}
function farmedOfSupply(S) {
  const area = S && S.area_ha_by_class && typeof S.area_ha_by_class === "object" ? S.area_ha_by_class : {};
  const vals = FARMED.map((k) => num(area[k])).filter((v) => v != null);
  return num(S && S.farmed_ha) ?? (vals.length ? sum(vals) : null);
}
function renderLead() {
  const S = get(state.summary, "supply");
  if (!S) { $("lead").textContent = "The results summary has no supply figures."; return; }
  const nf = S.fields_by_class || {}, act = S.active_ha || {};
  let farmedFields = sum(FARMED.map((k) => nf[k]));
  if (!farmedFields) farmedFields = state.fields.features.filter((f) => FARMED.includes(fieldClass(f.properties))).length;
  const nFields = num(S.fields) ?? state.fields.features.length;
  // The two seasons as small figures between hairlines under the headline (each shown only when the JSON holds it).
  const seasons = [["winter", "Farmed in winter"], ["summer", "Farmed in summer"]].filter(([k]) => num(act[k]) != null)
    .map(([k, label]) => `<div><dt>${label}</dt><dd>${fmt(act[k])}<span class="u">ha</span></dd></div>`).join("");
  // qassim-3, qd-9, tx-10: the farmed area sits on the farmed fields, not on every mapped field.
  $("lead").innerHTML = `<p class="hl"><span class="hl-num">${fmt(farmedOfSupply(S))}</span><span class="hl-unit">ha farmed in 2025/26, found by radar</span></p>` +
    (seasons ? `<dl class="hl-seasons">${seasons}</dl>` : "") +
    `<p class="hl-text">Farmed on ${fmt(farmedFields)} of the ${fmt(nFields)} fields that Sentinel-2 maps in the core Qassim pivot cluster${num(S.field_ha) != null ? `, which cover ${fmt(S.field_ha)} ha` : ""}. ${regionSentence()}</p>`;
}
// The header's data stamp: the radar's dates, from the HV overlays (the static text stays when there are none).
function renderStamp() {
  const D = hvDates(), el = $("stamptext");
  if (!el || !D.all.length) return;
  const mo = (d) => `${MON[+d.slice(5, 7) - 1]} ${d.slice(0, 4)}`;
  el.textContent = `NISAR L-band radar, 20 m grid, ${D.all.length} dates from ${mo(D.all[0])} to ${mo(D.all[D.all.length - 1])}`;
}
// A KPI card's range bar, on a scale from the lowest to the highest value shown, with a tick at the chosen estimate.
// Lanes: the factor range (light band) and the threshold range (dark band). "Both at once" (the widest corners) normally
// sets the scale, so it is drawn as the bar's two ends with their values under them, not as a lane of its own; if a value
// falls outside it, it gets its whisker lane and keeps its row instead (bothRow). No bar when the estimate is missing,
// no range has values, or every value is equal.
function rangeBar(mid, lanes, both, div, d) {
  const ok = lanes.filter((l) => num(l.lo) != null && num(l.hi) != null);
  const hasBoth = both && num(both.lo) != null && num(both.hi) != null;
  if (num(mid) == null || (!ok.length && !hasBoth)) return { html: "", bothRow: hasBoth };
  const vals = [mid, ...ok.flatMap((l) => [l.lo, l.hi]), ...(hasBoth ? [both.lo, both.hi] : [])].map(Number);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  if (!(hi > lo)) return { html: "", bothRow: hasBoth };
  const ends = hasBoth && Math.min(both.lo, both.hi) === lo && Math.max(both.lo, both.hi) === hi;
  const pos = (v) => `${(100 * (v - lo) / (hi - lo)).toFixed(2)}%`;
  const drawn = ends || !hasBoth ? ok : [...ok, { ...both, cls: "rb-both" }];
  const html = `<div class="kpi-bar"><div class="rb${ends ? " framed" : ""}" aria-hidden="true">${drawn.map((l) => `<div class="rb-lane ${l.cls}"><i style="--a:${pos(Math.min(l.lo, l.hi))};--b:${pos(Math.max(l.lo, l.hi))}"></i></div>`).join("")}` +
    `<b class="rb-mid" style="--x:${pos(mid)}"></b></div>` +
    (ends ? `<div class="rb-ends"><span><span class="sr-only">${esc(both.name)}: </span>${fmt(lo / div, d)}</span><span><span class="sr-only">to </span>${fmt(hi / div, d)}</span></div>` : "") + `</div>`;
  return { html, bothRow: hasBoth && !ends, ends };
}
function renderOverview() {
  const S = get(state.summary, "supply");
  renderLead();
  if (!S) { $("kpis").innerHTML = ""; return; }
  const L_ = state.level, area = S.area_ha_by_class && typeof S.area_ha_by_class === "object" ? S.area_ha_by_class : {};
  const farmed = farmedOfSupply(S);

  const mw = S.summer_pumping_avg_mw;
  // [label, keys, divisor, unit, decimals, sub line]. Labels carry no icon: the six are told apart by their words.
  const tiles = [
    ["Water pumped", ["water_m3"], 1e6, "million m³ / year", 0],
    ["Pumping electricity", ["elec_kwh"], 1e6, "GWh / year", 0, mw && num(mw[L_]) != null ? `About ${fmt(mw[L_])} MW average June–September` : ""],
    ["Pumping CO₂ (grid)", ["co2_t_electric", "co2_t_grid"], 1e3, "kt CO₂e / year", 0],
    ["Pumping CO₂ (diesel)", ["co2_t_diesel"], 1e3, "kt CO₂e / year", 0],
    ["Collectable wheat straw", ["residue_t_dry", "straw_t_dry"], 1e3, "kt dry / year", 1],
    ["Palm fronds", ["fronds_t_dry"], 1e3, "kt dry / year", 1, "From radar + WorldCover"],
  ];
  // Each card: the chosen estimate, then its ranges on one bar. Factor range: every factor at its low or high bound.
  // Threshold: both radar thresholds moved each way, at the chosen estimate. Both at once: the widest corners, drawn as
  // the bar's ends. The key above the cards names each mark once; each card's rows give the values.
  const CR = obj(S.classification_range) || {}, sh = shifts(CR), corners = obj(CR.corners) || {};
  const thrName = sh.up === sh.dn ? `Threshold ±${sh.upTxt}` : `Threshold −${sh.dnTxt} / +${sh.upTxt}`;
  const span = (a, b, div, d) => { const lo = Math.min(a, b), hi = Math.max(a, b); return fmt(lo / div, d) === fmt(hi / div, d) ? fmt(lo / div, d) : `${fmt(lo / div, d)}–${fmt(hi / div, d)}`; };   // a range that collapses shows its one value
  const used = new Set();
  $("kpis").innerHTML = tiles.map(([label, keys, div, unit, d, extra]) => {
    const o = pick(S, keys);
    if (!o || num(o[L_]) == null) return "";
    const tp = pick(CR.plus_1db, keys), tm = pick(CR.minus_1db, keys), co = pick(corners, keys);
    const lanes = [
      { cls: "rb-factor", lo: num(o.low), hi: num(o.high), name: "Factor range" },
      { cls: "rb-thr", lo: num(get(tp, L_)), hi: num(get(tm, L_)), name: thrName },
    ];
    const both = { cls: "rb-both", lo: num(get(co, "low")), hi: num(get(co, "high")), name: "Both at once" };
    const bar = rangeBar(num(o[L_]), lanes, both, div, d);
    const shown = lanes.filter((l) => l.lo != null && l.hi != null).concat(bar.bothRow ? [both] : []);
    shown.forEach((l) => used.add(l.cls));
    if (bar.html) used.add("rb-mid");
    if (bar.ends) used.add("rb-ends");
    const rows = shown.map((l) => `<div class="r-${l.cls.slice(3)}"><dt><span class="sr-only">${l.name}</span></dt><dd>${span(l.lo, l.hi, div, d)}</dd></div>`).join("");
    // five rows on the cards' shared grid (label, value, sub line, bar, values), so bars line up across a row
    return `<div class="kpi"><div class="kpi-label">${label}</div><div class="kpi-value">${fmt(o[L_] / div, d)}<span class="kpi-unit">${unit}</span></div>` +
      `<p class="kpi-sub">${extra || ""}</p>${bar.html || `<div class="kpi-bar"></div>`}<dl class="kpi-range">${rows}</dl></div>`;
  }).join("");
  // The key, once above the cards: only the marks the cards draw.
  const keyItems = [
    ["rb-factor", "rk", "Factor range", "every factor at its low or high bound"],
    ["rb-thr", "rk thr", thrName, "both radar thresholds moved, at the chosen estimate"],
    ["rb-ends", "rk both", "Both at once", "the bar's two ends, with their values under them"],
    ["rb-both", "rk both", "Both at once", "the two moved together"],
    ["rb-mid", "rk mid", `${LEVEL_NAME[L_]} estimate`, "the tick"],
  ].filter(([k]) => used.has(k));
  $("kpikey").hidden = !keyItems.length;
  $("kpikey").innerHTML = keyItems.map(([, cls, name, what]) => `<li><i class="${cls}" aria-hidden="true"></i><span><b>${esc(name)}</b>, ${what}</span></li>`).join("");
  safe(() => renderSens(S, L_), "sens");

  const max = Math.max(1, ...Object.values(area).map((v) => num(v) || 0));
  const row = (c) => `<div class="bar-row"><div class="bar-head"><span class="swatch" style="background:${COLORS[c] || COLORS.idle}"></span><span>${esc(cname(c))}</span><span class="num">${fmt(area[c])} ha</span></div>
    <div class="bar-fill" style="--c:${COLORS[c] || COLORS.idle};width:${(100 * (num(area[c]) || 0) / max).toFixed(1)}%"></div></div>`;
  const farmedRows = FARMED.filter((c) => area[c] != null), otherRows = Object.keys(area).filter((c) => !FARMED.includes(c));
  $("classbars").innerHTML = `<div class="bar-group">Farmed (in the total): ${fmt(farmed)} ha</div>${farmedRows.map(row).join("")}` +
    (otherRows.length ? `<div class="bar-group sep">Not in the total</div>${otherRows.map(row).join("")}` : "") +
    (area.idle != null ? `<p class="note">“Not detected by radar”: green in Sentinel-2 at some point in 2025/26 but below the radar threshold in both seasons; most are fields the radar missed, not idle land.</p>` : "");
  safe(() => renderCaveats(S), "caveats");
}

// The classification range's threshold shifts (classification_range.shift_db), 1 dB each way when the key is missing.
function shifts(CR) {
  const sh = (CR && CR.shift_db) || {}, up = Math.abs(num(sh.plus_1db) ?? 1), dn = Math.abs(num(sh.minus_1db) ?? 1);
  const dB = (v) => `${fmt(v, Number.isInteger(v) ? 0 : 1)} dB`, sgn = (v) => (v > 0 ? "+" : "") + fmt(v, Number.isInteger(v) ? 0 : 1);
  return { up, dn, upTxt: dB(up), dnTxt: dB(dn), both: up === dn ? dB(up) : `${dB(dn)} down or ${dB(up)} up`, corners: `${sgn(-dn)}, 0 or ${sgn(up)} dB` };
}
function renderSens(S, L_) {
  // How firm the totals are: radar thresholds moved each way, and the radar + Sentinel-2 tier, at the chosen estimate.
  const CR = S.classification_range || {}, SF = S.s2_filled || {}, wasOpen = !!$("sens").querySelector("details[open]"), sh = shifts(CR);
  // With no Sentinel-2-only fields the combined tier equals the seasons tier, whose scope string reads better here.
  const tier = num(get(SF, "s2_only_fields", "fields")) === 0 && SF.radar_plus_s2_seasons ? SF.radar_plus_s2_seasons : (SF.combined || SF.radar_plus_s2_seasons);
  const rows = [];
  if (CR.plus_1db) rows.push([`Radar, threshold ${sh.upTxt} stricter`, CR.plus_1db, ""]);
  rows.push(["Radar: the totals above", S, "base"]);
  if (CR.minus_1db) rows.push([`Radar, threshold ${sh.dnTxt} looser`, CR.minus_1db, ""]);
  if (tier) rows.push(["Radar + Sentinel-2", tier, "tier"]);
  if (rows.length < 2) { $("sens").innerHTML = ""; return; }
  const cell = (o, keys, div, d) => { const t = pick(o, keys); return `<td class="num">${t && num(t[L_]) != null ? fmt(t[L_] / div, d) : "–"}</td>`; };
  const farmedOf = (o) => num(o.farmed_ha) ?? sum(FARMED.map((k) => get(o, "area_ha_by_class", k)));
  let html = `<h3>How firm are these totals?</h3>
    <p class="note sens-cap">${LEVEL_NAME[L_]} estimate. Water in million m³ a year, electricity in GWh a year, straw in kt dry a year.</p>
    <table class="sens"><tr><th></th><th class="num">Farmed ha</th><th class="num">Water</th><th class="num">Electricity</th><th class="num">Straw</th></tr>
    ${rows.map(([label, o, cls]) => `<tr${cls ? ` class="${cls}"` : ""}><td>${label}</td><td class="num">${fmt(farmedOf(o))}</td>${cell(o, ["water_m3"], 1e6, 0)}${cell(o, ["elec_kwh"], 1e6, 0)}${cell(o, ["straw_t_dry", "residue_t_dry"], 1e3, 1)}</tr>`).join("")}</table>`;
  const notes = [];
  if (CR.plus_1db || CR.minus_1db) {
    const z = CR.zero_shift_check || {};
    notes.push(`The threshold rows move both radar thresholds by ${sh.both} at the same factors: looser counts more fields as farmed, stricter fewer.${num(z.share_identical) === 1 ? ` Moving them by 0 dB reproduces all ${fmt(z.fields)} published field calls.` : ""}`);
  }
  const co = CR.corners || {}, cr = (k, div, d, unit) => co[k] && num(co[k].low) != null ? `${unit} ${fmt(co[k].low / div, d)}–${fmt(co[k].high / div, d)}` : null;
  const corners = [cr("water_m3", 1e6, 0, "water"), cr("elec_kwh", 1e6, 0, "electricity"), cr("straw_t_dry", 1e3, 1, "straw")].filter(Boolean);
  if (corners.length) notes.push(`Widest corners, with every factor at its low or high bound and the threshold at ${sh.corners}: ${list(corners)} (same units). Corners are not probability intervals.`);
  if (tier) {
    const add = num(tier.s2_filled_ha), n = num(tier.s2_filled_fields), caps = SF.caps && typeof SF.caps === "object" ? SF.caps : {};
    // qassim-5: say next to the tier that its straw is capped at GASTAT's wheat area, and whether the cap binds here.
    const yr = (String(caps.rule || "").match(/GASTAT (\d{4})/) || [])[1];
    const capped = Array.isArray(caps.regions_capped) ? caps.regions_capped.map((r) => typeof r === "string" ? r : r && (r.region || r.name)).filter(Boolean) : null;
    const eff = get(caps, "effect", tier === SF.radar_plus_s2_seasons ? "radar_plus_s2_seasons" : "combined") || {};
    const credited = num(eff.s2_wheat_ha_credited) != null && num(eff.s2_wheat_ha) > 0 && eff.s2_wheat_ha_credited < eff.s2_wheat_ha ?
      `: straw is counted on ${fmt(eff.s2_wheat_ha_credited)} of the ${fmt(eff.s2_wheat_ha)} ha of wheat-pattern fields the tier adds, as in the row above` : "";
    const capTxt = caps.rule ? ` Its straw is capped at GASTAT${yr ? " " + yr : ""} wheat area per region${capped ? (capped.length ? `; the cap binds in ${esc(list(capped))}${credited}` : "; the cap does not bind here") : ""}.` : "";
    notes.push(`Radar + Sentinel-2 is a separate tier, never the headline: ${add != null ? `it adds ${fmt(add)} ha on ${fmt(n)} fields that the radar did not detect but Sentinel-2 sees green in winter only, counted as winter-farmed. ` : ""}That area is measured by Sentinel-2, not by the radar.${capTxt}`);
  }
  const fr = rows.map(([, o]) => get(o, "fronds_t_dry", L_)).filter((v) => num(v) != null);
  if (fr.length === rows.length && fr.every((v) => Math.abs(v - fr[0]) < 0.5)) {
    // qassim-3 (review): the reason is that no grove sits near the threshold, not that groves ignore the radar.
    const why = [CR.plus_1db || CR.minus_1db ? `moving the thresholds by ${sh.both} changes no palm grove` : "", tier ? "the Sentinel-2 tier adds none" : ""].filter(Boolean);
    if (why.length) notes.push(`Palm fronds are the same in every row: ${why.join(", and ")}.`);
  }
  // qassim-4 (review): the tier's scope names fills (a) to (c), which only its rule defines, so it sits under that rule.
  const rules = [[CR.rule, "Threshold rows"], [CR.corners_rule, "Corners"], [SF.rule, "Radar + Sentinel-2", tier && tier.scope]].filter(([r]) => r);
  html += notes.map((t) => `<p class="note">${t}</p>`).join("") +
    (rules.length ? `<details class="more"><summary>The rules behind these rows</summary>${rules.map(([r, h, scope]) =>
      `<p><b>${h}.</b> ${esc(plain(r))}</p>${scope ? `<p><b>Scope of the Radar + Sentinel-2 row:</b> ${esc(plain(scope).replace(/\.$/, ""))}.</p>` : ""}`).join("")}</details>` : "");
  $("sens").innerHTML = html;
  if (wasOpen) $("sens").querySelector("details")?.setAttribute("open", "");   // an estimate change keeps the rules open
}

function renderCaveats(S) {
  const V = get(state.summary, "validation") || {}, nf = S.national_flags || {}, H = S.pumping_head || {};
  const rec = (s) => { const h = get(V, s, "ha"); return h && num(h.both_active) != null && num(get(V, s, "s2_active_ha")) ? h.both_active / V[s].s2_active_ha : null; };
  const ig = idleGreenHa(), rw = rec("winter"), rs = rec("summer");
  const water = [];
  if (rw != null && rs != null) water.push(`Radar finds ${pct(rw)} of the area Sentinel-2 sees green over the radar's dates in winter and ${pct(rs)} in summer`);
  if (ig && ig.all) water.push(`${fmt(ig.green)} of the ${fmt(ig.all)} ha “not detected” were green then`);
  const noSpring = get(nf, "two_season_no_spring_check", "ha");
  const da = depthAge(H, state.level);
  const items = [
    `<b>Water</b> is likely an underestimate: fields the radar did not detect get none.${water.length ? ` ${water.join(", and ")}.` : ""} Radar false alarms push the other way.`,
    `<b>Energy</b> is a lower bound: it assumes a well-run pump lifting from the depth to water ${da.measured}${H.rule ? ", plus drawdown and pivot pressure" : ""}, and water levels have fallen since.${da.sens ? `<span class="caveat-sub"><span class="tag">Sensitivity, in no total</span> ${da.sens}</span>` : ""}`,
    `<b>Straw</b> is a lower bound too: it counts winter-only fields (assumed wheat) and wheat rotations, which the national spring check finds brown in late spring; radar's winter scenes end on ${lastWinterDate() || "31 December"}, when young wheat is still thin${num(noSpring) ? `, and ${fmt(noSpring)} ha farmed in both seasons have no spring check, so they stay year-round` : ""}.`,
    `<b>Palm fronds</b> come from palm groves: tree cover of 30% or more and farmed in both seasons.`,
  ];
  $("caveats").innerHTML = `<ul class="note caveats">${items.map((t) => `<li>${t}</li>`).join("")}</ul>`;
}
// Where and when the depth to water was measured, and what the water-level decline since then would add to the
// pumping electricity at the chosen estimate (pumping_head.depth_age_sensitivity; notes.depth_age or the older
// notes._age as text when the numbers are missing). A sensitivity: it is in no total.
function depthAge(H, L_) {
  const D = H.depth_age_sensitivity && typeof H.depth_age_sensitivity === "object" ? H.depth_age_sensitivity : {};
  const m = String(H.detail || "").match(/static depth to water, ([A-Z][\w'-]*(?: [A-Z][\w'-]*)*),? (\d{4})/);
  const y0 = num(D.depth_year) ?? (m ? +m[2] : null);
  const measured = y0 != null ? `measured ${m ? `at ${esc(m[1])} ` : ""}in ${y0}` : "measured years ago";
  const two = (a) => Array.isArray(a) && a.length === 2 && a.every((v) => num(v) != null) ? a.map(Number) : null;
  const n1 = (v) => fmt(v, Number.isInteger(v) ? 0 : 1);
  const g = two(get(D, "extra_elec_gwh", L_)), s = two(get(D, "extra_share_of_elec_kwh", L_)), r = two(D.decline_m_per_yr), h = two(D.extra_head_m);
  const notes = H.notes && typeof H.notes === "object" ? H.notes : {};
  let sens = "";
  if (g && r && y0 != null) {
    const y1 = num(D.season_year);
    sens = `If the water table has fallen ${n1(r[0])}–${n1(r[1])} m a year since ${y0} (a decline measured elsewhere, used as an analogue: <a href="#sources" data-target="headinfo">Method tab</a>)` +
      `${h ? `, the water would be ${n1(h[0])}–${n1(h[1])} m deeper${y1 != null ? ` by ${y1}` : ""}, which` : ", that"} would add ${fmt(g[0])}–${fmt(g[1])} GWh a year` +
      `${s ? ` (+${pct(s[0])} to +${pct(s[1])})` : ""} to the ${LEVEL_NAME[L_].toLowerCase()} pumping electricity above.`;
  } else {
    const t = [notes.depth_age, notes._age].find((x) => typeof x === "string" && x);
    if (t) sens = esc(plain(t).replace(/\.?$/, "."));
  }
  return { measured, sens };
}
function lastWinterDate() {
  const w = overlaysFor("NISAR HV backscatter").filter((o) => isDate(o.date) && seasonOf(o.date) === "winter").map((o) => o.date).sort();
  return w.length ? dayLong(w[w.length - 1]) : null;
}

/* ---------- Radar check ---------- */
function ruleText(V) {
  const t = V.hv_threshold_db || {};
  const thr = num(t.winter) != null && num(t.summer) != null ? `, here ${fmt(t.winter, 2)} dB (winter) and ${fmt(t.summer, 2)} dB (summer)` : "";
  const de = V.desert_exceedance && num(V.desert_exceedance.winter) != null && num(V.desert_exceedance.summer) != null ? V.desert_exceedance :
    (t.winter === DESERT_EXCEED.thr.winter && t.summer === DESERT_EXCEED.thr.summer ? DESERT_EXCEED.share : null);
  const rate = de ? `about ${pct(de.winter)} (winter) and ${pct(de.summer)} (summer) of bare-desert patches` : "a share of bare-desert patches";
  return `its seasonal peak HV backscatter, measured above the bare-desert median of the same date, beats a desert-patch tail threshold: median + 3 × (median − 16th percentile) of field-sized desert patches' seasonal peaks${thr}. Desert peaks have a long bright tail, so ${rate} still beat it: not the near-zero false-alarm rate a “3σ” rule would suggest. The rule uses no Sentinel-2 input; Sentinel-2 (same date windows) is only the check.`;
}
function winterMisses() {   // fields Sentinel-2 sees green over the radar's winter dates that the radar calls not farmed in winter
  let all = 0, brown = 0, green = 0;
  state.fields.features.forEach((f) => {
    const p = f.properties || {};
    if (!p.s2_winter_check || WINTER_ON.has(fieldClass(p))) return;
    const a = num(p.area_ha) || 0;
    all += a;
    if (p.spring_brown === true) brown += a; else if (p.spring_brown === false) green += a;
  });
  return all ? { all, brown, green } : null;
}
function renderValidation() {
  const V = get(state.summary, "validation");
  if (!V || typeof V !== "object") { $("validation").innerHTML = "<p class='note'>Validation runs once radar data is processed.</p>"; return; }
  const seasons = ["winter", "summer"].filter((s) => V[s]);
  const rows = seasons.map((s) => { const v = V[s]; return `<tr><td>${s}</td><td class="num">${pct(v.area_agreement)}</td><td class="num">${fmt(v.kappa, 2)}</td>
      <td class="num">${fmt(v.radar_active_ha)}</td><td class="num">${fmt(v.s2_active_ha)}</td></tr>`; }).join("");
  const hit = seasons.map((s) => {
    const h = V[s].ha || {}, ra = num(V[s].radar_active_ha), sa = num(V[s].s2_active_ha);
    if (num(h.both_active) == null || !ra || !sa) return "";
    return `${s}: radar finds ${pct(h.both_active / sa)} of the area Sentinel-2 sees green, and Sentinel-2 confirms ${pct(h.both_active / ra)} of what radar calls farmed (${fmt(h.radar_only)} ha farmed by radar only, ${fmt(h.s2_only)} ha green in Sentinel-2 only)`;
  }).filter(Boolean);
  const wit = seasons.filter((s) => V[s].by_witness).map((s) => Object.entries(V[s].by_witness).map(([k, w]) =>
    `<tr><td>${s}</td><td>${esc(k)}</td><td class="num">${pct(w.area_agreement)}</td><td class="num">${fmt(w.kappa, 2)}</td><td class="num">${fmt(w.radar_active_ha)}</td></tr>`).join("")).join("");
  const S = get(state.summary, "supply") || {}, CR = S.classification_range || {};
  const move = CR.plus_1db && CR.minus_1db ? ` Moving both thresholds by ${shifts(CR).both} gives ${fmt(CR.plus_1db.farmed_ha)} ha farmed (stricter) to ${fmt(CR.minus_1db.farmed_ha)} ha (looser), against ${fmt(farmedOfSupply(S))} ha (<a href="#overview">Overview</a>).` : "";
  const sm = (s) => get(V, s, "by_witness", "soil moisture"), bs = (s) => get(V, s, "by_witness", "backscatter or soil moisture");
  const smTxt = sm("winter") && sm("summer") ? `Soil moisture (200 m) helps in summer only (kappa ${fmt(sm("summer").kappa, 2)} in summer, ${fmt(sm("winter").kappa, 2)} in winter): it catches irrigation but also wet ground around fields, so adding it raises the farmed area${bs("winter") && bs("summer") ? ` (to ${fmt(bs("winter").radar_active_ha)} ha in winter and ${fmt(bs("summer").radar_active_ha)} ha in summer, against Sentinel-2's ${fmt(get(V, "winter", "s2_active_ha"))} and ${fmt(get(V, "summer", "s2_active_ha"))} ha)` : ""} but lowers kappa.` :
    "Soil moisture (200 m) catches irrigation but also wet ground around fields: adding it raises the farmed area but lowers kappa.";
  const wm = winterMisses(), last = lastWinterDate() || "31 December";
  const wmTxt = wm && wm.brown + wm.green > 0 ? ` Of the ${fmt(wm.all)} ha Sentinel-2 sees green in winter that the radar misses, ${pct(wm.brown / (wm.brown + wm.green))} turn brown in late spring like wheat and ${pct(wm.green / (wm.brown + wm.green))} stay green like perennial fodder, which also has a low winter canopy (national spring check, on the ${fmt(wm.brown + wm.green)} ha with a matching national field).` : "";
  $("validation").innerHTML = `<table><tr><th>Season</th><th class="num">Area agreement</th><th class="num">Kappa</th>
    <th class="num">Radar farmed ha</th><th class="num">Sentinel-2 farmed ha</th></tr>${rows}</table>
    ${hit.length ? `<p class="note">${hit.map((t) => t.charAt(0).toUpperCase() + t.slice(1)).join(". ")}.</p>` : ""}
    <p class="note"><b>Rule:</b> a field is farmed in a season when ${ruleText(V)}${move}</p>
    ${wit ? `<h3>Three radar witnesses tested</h3>
    <table><tr><th>Season</th><th>Witness</th><th class="num">Agreement</th><th class="num">Kappa</th><th class="num">Farmed ha</th></tr>${wit}</table>` : ""}
    <p class="note">HV backscatter (crop canopy) is the reliable witness here. Twelve-day coherence does not separate fields from desert: sand itself loses coherence (desert median about 0.5). ${smTxt} Winter agreement is lower because NISAR's winter scenes end on ${last}, when young wheat is still thin at L-band.${wmTxt}</p>
    <p class="note">Sentinel-2 also outlines the fields, so these are consistency checks, not an independent ground truth.</p>`;
}

/* ---------- Biochar plants ---------- */
function feedMix(straw, fronds) {
  const tot = straw + fronds;
  if (!(tot > 0)) return "";
  const parts = [["straw", straw, "wheat straw"], ["fronds", fronds, "palm fronds"]].filter(([, v]) => v > 0);
  return `<div class="feedmix">Feed: ${parts.map(([, v, n]) => `<b>${fmt(v)} t</b> ${n}`).join(" + ")} (dry)
    <div class="feedbar" role="img" aria-label="${parts.map(([, v, n]) => `${pct(v / tot)} ${n}`).join(", ")}">${parts.map(([k, v]) => `<i style="--c:${FEED_COL[k]};flex-grow:${v}"></i>`).join("")}</div></div>`;
}
function renderPlants() {
  const siting = get(state.summary, "siting") || {}, P = get(state.summary, "params") || {}, L_ = state.level, size = state.size;
  const tag = `${L_}_${size}kt`, plants = Array.isArray(siting[tag]) ? siting[tag].filter((p) => p && typeof p === "object") : null;
  if (state.plantLayer) map.removeLayer(state.plantLayer);
  state.plantLayer = L.layerGroup();
  state.plantSites = new Map();
  const lvl = LEVEL_NAME[L_].toLowerCase(), minLoad = num(get(P, "min_load_fraction", L_));
  if (!plants) {
    $("plantlist").innerHTML = `<p class="callout">${ICO("info")}<span>No siting result for hypothetical ${size} kt/y plants at the ${lvl} estimate.</span></p>`;
  } else if (!plants.length) {
    $("plantlist").innerHTML = `<p class="callout">${ICO("info")}<span>No site can be filled to ${minLoad != null ? pct(minLoad) : "80%"} of a <b>${size} kt/y</b> plant with the straw and palm fronds radar finds here (${lvl} estimate). The local limit is supply, not distance: pooling a wider region or other residues would be needed.</span></p>`;
  } else {
    const tot = sum(plants.map((p) => p.feed_t_dry)), st = sum(plants.map((p) => p.feed_straw)), fr = sum(plants.map((p) => p.feed_fronds));
    const net = sum(plants.map((p) => p.net_removal_tco2 ?? (p.best_outlet === "cement" ? p.cement_net_tco2 : p.soil_net_tco2)));
    const ret = P.cement_retention || {}, temp = get(P, "soil_temp_c", L_);
    const pfS = get(P, "straw_char_persistence", L_), pfF = get(P, "fronds_char_persistence", L_);
    const pf = [num(pfS) != null ? `straw char ${pct(pfS)}` : "", num(pfF) != null ? `frond char ${pct(pfF)}` : ""].filter(Boolean);
    const pens = plants.map((p) => 100 * (num(p.penalty) || 0)), pmin = Math.min(...pens), pmax = Math.max(...pens);
    const rc = num(get(P, "road_circuity", L_));
    const outletName = (o) => o === "cement" ? "cement" : "soil";
    // Soil use of each char (summary.soil_use): a feed whose char is not measured as passing is flagged on each card.
    const SU = obj(get(state.summary, "soil_use")) || obj(get(state.summary, "params", "_soil_use")) || {};
    const notPass = FEEDS.filter(([f]) => obj(SU[f]) && SU[f].status && SU[f].status !== "pass");
    const card = (p) => {
      const cem = num(p.cement_net_tco2) != null ? `, <b>${fmt(p.cement_net_tco2)} t/y</b> in cement at the nearest existing cement plant (${fmt(p.cement_km)} km)` : "";
      const rem = num(p.soil_removal_tco2);
      const flags = notPass.map(([f, , ch]) => { const r = num(p[`soil_removal_${f}_tco2`]); return rem > 0 && r > 0 ? `${pct(r / rem)} of the removal comes from ${ch}, ${soilStatus(SU[f].status)} against Puro's soil limits` : ""; }).filter(Boolean);
      // The number badge matches the plant's pin on the map: a dashed square in the colour of its char outlet.
      return `<article class="plant" data-plant="${esc(p.plant)}" aria-label="Hypothetical biochar plant site ${esc(p.plant)}">
        <div class="plant-head"><span class="pnum" style="--c:${MARK[p.best_outlet === "cement" ? "cement" : "soil"]}" aria-hidden="true">${esc(p.plant)}</span>
          <div class="plant-id"><b class="plant-name">Hypothetical plant ${esc(p.plant)}</b><span class="plant-where">${fmt(p.lat, 3)}°N, ${fmt(p.lon, 3)}°E, ${p.kind === "cement" ? "beside an existing cement plant" : "model grid site"}</span></div>
          ${num(p.lat) != null && num(p.lon) != null ? `<button type="button" class="showmap">${ICO("target", "sm")}<span>Show on map</span></button>` : ""}</div>
        <dl class="pfacts"><div><dt>Fields</dt><dd>${fmt(p.fields)}</dd></div><div><dt>Mean haul</dt><dd>${fmt(p.mean_feed_haul_km, 1)} km</dd></div>
          <div><dt>Load</dt><dd>${pct(p.load_factor)}</dd></div><div><dt>Char</dt><dd>${fmt(p.char_t)} t/y</dd></div></dl>
        ${feedMix(num(p.feed_straw) || 0, num(p.feed_fronds) || 0)}
        <p class="pline">Net CO₂ removed after transport: <b>${fmt(p.soil_net_tco2)} t/y</b> spread back on the fields${cem}.</p>
        <p class="pline">Best outlet: <b>${outletName(p.best_outlet)}</b>; transport uses ${fmt(100 * (num(p.penalty) || 0), 1)}% of its removal.</p>
        ${flags.length ? `<div class="soilflag">${flags.map((t) => t.charAt(0).toUpperCase() + t.slice(1)).join(". ")} (<a href="#plants" data-target="soiluse-h">soil use</a>).</div>` : ""}</article>`;
    };
    const mixKey = st > 0 && fr > 0 ? `<ul class="key feedkey"><li><i style="--c:${FEED_COL.straw}" aria-hidden="true"></i>wheat straw</li><li><i style="--c:${FEED_COL.fronds}" aria-hidden="true"></i>palm fronds</li></ul>` : "";
    $("plantlist").innerHTML = `<dl class="plant-sum">
        <div><dt>Hypothetical plant${plants.length > 1 ? "s" : ""} of ${size} kt/y</dt><dd>${plants.length}</dd></div>
        <div><dt>kt dry feed a year</dt><dd>${fmt(tot / 1e3, 1)}</dd></div>
        <div><dt>t CO₂ removed a year, net of transport</dt><dd>${fmt(net)}</dd></div></dl>
      ${st || fr ? `<p class="note plant-feed">Feed: ${fmt(st / 1e3, 1)} kt wheat straw and ${fmt(fr / 1e3, 1)} kt palm fronds, dry, at the ${lvl} estimate.</p>` : ""}
      <p class="callout">${ICO("info")}<span>This is a technical potential, not a credit volume: stored char carbon × the Puro.earth 2025 soil persistence model, minus truck emissions only; production and embodied emissions and leakage are not subtracted.</span></p>
      ${mixKey}${plants.map(card).join("")}
      <p class="note">Char in cement earns the same credit as char spread back on the fields: the Puro.earth 2025 methodology credits both with its soil persistence model (${pf.length ? `${list(pf)} of the char's organic carbon kept over 200 years` : "the char's organic carbon kept over 200 years"}${num(temp) != null ? ` in ${fmt(temp)} °C soil` : ""}), so the shorter char haul picks the outlet. Cement may hold more in service${num(ret.low) != null ? ` (${pct(ret.low)}–${pct(ret.high)} retained)` : ""}; that is reported, not credited. In this cluster haulage costs ${pmin.toFixed(1) === pmax.toFixed(1) ? `${fmt(pmax, 1)}%` : `${fmt(pmin, 1)}–${fmt(pmax, 1)}%`} of the removal: the limit is residue supply, not distance.${rc != null && rc !== 1 ? ` At the ${lvl} estimate every distance is the straight line × ${fmt(rc, 1)} (road circuity, an unsourced sensitivity), so the same site shows longer hauls than at the other estimates.` : ""}</p>${soilUse(SU, plants, size, lvl)}`;
    // One marker per site: some sizes put two plants on the same grid point.
    const sites = new Map();
    plants.forEach((p) => {
      if (num(p.lat) == null || num(p.lon) == null) return;
      const k = `${(+p.lat).toFixed(5)},${(+p.lon).toFixed(5)}`;
      if (!sites.has(k)) sites.set(k, []);
      sites.get(k).push(p);
    });
    sites.forEach((ps) => {
      const outlet = ps.every((p) => p.best_outlet === "cement") ? "cement" : "soil", ids = ps.map((p) => p.plant);
      const icon = L.divIcon({ className: "plant-pin", html: `<span style="--c:${MARK[outlet]}">${ids.map(esc).join(", ")}</span>`, iconSize: [0, 0] });
      const m = L.marker([+ps[0].lat, +ps[0].lon], { icon, keyboard: true, riseOnHover: true });
      // Touch screens get the popup only: Leaflet also opens a tooltip on tap, and the two would overlap (as drawFields).
      if (canHover) m.bindTooltip(ps.map((p) => `<b>Hypothetical biochar plant ${esc(p.plant)}</b>: ${size} kt/y, ${plantFacts(p)}`).join("<br>") +
        `<br><span class="tt-hint">A modelled site: no such plant exists</span>`, { direction: "top", offset: [0, -12] });
      m.on("click", () => focusPlant(ps, m));
      m.on("add", () => m.getElement()?.setAttribute("aria-label", `Hypothetical biochar plant site ${ids.join(" and ")}`));
      m.addTo(state.plantLayer);
      ids.forEach((id) => state.plantSites.set(String(id), { ps, m }));
    });
  }
  if ($("showplants").checked) state.plantLayer.addTo(map);
}
const plantFacts = (p) => `char ${p.best_outlet === "cement" ? "to cement" : "back to the fields"}, transport ${fmt(100 * (num(p.penalty) || 0), 1)}% of removal`;
const plantBox = (m) => m.getLatLng().toBounds(2500);
function plantPopup(ps, marker, link) {
  marker.closeTooltip();
  L.popup({ maxWidth: 240, autoPanPadding: [16, 16], autoPanPaddingTopLeft: [64, 16], offset: [0, -8] }).setLatLng(marker.getLatLng())
    .setContent(`${ps.map((p) => `<b>Hypothetical biochar plant ${esc(p.plant)}</b>, ${state.size} kt/y<br>${plantFacts(p).replace(/^./, (c) => c.toUpperCase())}`).join("<br>")}` +
      `<br><span class="tt-hint">A modelled site: no such plant exists.</span>` +
      (link ? `<br><a href="#plants" class="poplink" data-plant="${esc(ps[0].plant)}">See it in the list${ICO("chevron", "sm down")}</a>` : "")).openOn(map);
}
function focusPlant(ps, marker) {
  const n = ps[0].plant, moved = zoomTo(plantBox(marker), 13, true);
  if (narrow()) {   // never scroll away from the map: offer the panel instead, with the tooltip's facts
    marker.closeTooltip();
    afterMove(moved, () => plantPopup(ps, marker, true));
    return;
  }
  openTab("plants");
  highlightPlant(n);
}
// A plant card in the list: fly the map to its site and open its facts there (phones: the map comes into view first).
function goPlant(n) {
  const site = state.plantSites.get(String(n));
  if (!site) return;
  highlightPlant(n, false);
  const box = $("showplants");
  if (box && !box.checked) { box.checked = true; box.onchange({ target: box }); }
  showMapThen(() => afterMove(zoomTo(plantBox(site.m), 13), () => plantPopup(site.ps, site.m, false)));
}
// Can the char go on the fields? Each feed's soil-use status against Puro.earth 2025 Table 3.3 (summary.soil_use), the
// share of this layout's credited removal that rests on a char not measured as passing, and the evidence.
function soilUse(SU, plants, size, lvl) {
  const rows = FEEDS.filter(([f]) => obj(SU[f]));
  if (!rows.length) return "";
  const tot = sum(plants.map((p) => p.soil_removal_tco2));
  const flagged = rows.filter(([f]) => SU[f].status && SU[f].status !== "pass").map(([f, , ch]) => {
    const r = sum(plants.map((p) => p[`soil_removal_${f}_tco2`]));
    const share = tot > 0 && r > 0 ? `: ${pct(r / tot)} of the removal above (${size} kt/y, ${lvl} estimate) comes from ${ch}` : "";
    return `${ch.charAt(0).toUpperCase() + ch.slice(1)} is ${soilStatus(SU[f].status)} against these limits; the siting applies no contaminant screen, so it is credited all the same, on the fields or in cement${share}.${SU[f].status === "unmeasured" ? ` It needs a lab analysis before it goes on farmland.` : ""}`;
  });
  return `<h3 id="soiluse-h">Can the char go on the fields?</h3>
    <table class="soiluse"><tr><th>Char from</th><th>Soil use (Puro Table 3.3)</th><th>Outlet</th></tr>${rows.map(([f, label]) =>
      `<tr><td>${label}</td><td>${esc(soilStatus(SU[f].status))}</td><td>${esc(SU[f].outlet || "–")}</td></tr>`).join("")}</table>
    ${flagged.length ? `<p class="note">${flagged.join(" ")}</p>` : ""}
    ${rows.some(([f]) => SU[f].note) ? `<details class="more"><summary>Evidence for each char</summary>${rows.map(([f, label]) => SU[f].note ? `<p><b>${label}:</b> ${esc(plain(SU[f].note).replace(/\.?$/, "."))}</p>` : "").join("")}</details>` : ""}`;
}
function highlightPlant(n, scroll = true) {
  let hit = null;
  document.querySelectorAll("#plantlist .plant[data-plant]").forEach((el) => { const on = el.dataset.plant === String(n); el.classList.toggle("sel", on); if (on) hit = el; });
  if (hit && scroll) hit.scrollIntoView({ block: "nearest", behavior: reduceMotion ? "auto" : "smooth" });
  return hit;
}

/* ---------- One field ---------- */
function showField(p, focus = true, lyr = state.byId[p && p.id]) {
  if (!p) return;
  state.fieldShown = p;
  if (focus) openTab("field");
  select(lyr);
  $("fieldbody").hidden = false;
  safe(renderFieldInfo, "fieldinfo");
  safe(renderFieldCharts, "chartnote");
  if (!state.ts) loadTs();
}
function renderFieldInfo() {
  const p = state.fieldShown;
  if (!p) return;
  const L_ = state.level, lv = LEVEL_NAME[L_].toLowerCase(), c = fieldClass(p);
  const val = (k) => num(p[`${k}_${L_}`]) ?? (L_ === "central" ? num(p[k]) : null);
  const green = (b) => b == null ? "unknown" : b ? "green" : "not green";
  $("fieldhint").classList.add("is-field");
  $("fieldhint").innerHTML = `<span class="field-title">Field ${esc(p.id)}</span>${state.ts ? "" : `<span class="field-status">Radar record loading…</span>`}`;
  const rw = WINTER_ON.has(c), rs = SUMMER_ON.has(c), dis = [];
  if (p.s2_winter_check != null && !!p.s2_winter_check !== rw) dis.push(`winter (radar: ${rw ? "farmed" : "not farmed"})`);
  if (p.s2_summer_check != null && !!p.s2_summer_check !== rs) dis.push(`summer (radar: ${rs ? "farmed" : "not farmed"})`);
  const tierOn = !!get(state.summary, "supply", "s2_filled");
  const filled = tierOn && c === "idle" && p.s2_winter_active === true && p.s2_summer_active === false;
  const none = c === "idle" && !(val("water_m3") > 0);   // not farmed by radar: no water, so no pumping
  const rows = [
    ["Class", `<span class="swatch outline" style="--c:${COLORS[c] || COLORS.idle}"></span>${esc(cname(c))}<div class="sub">${esc(CLASS_HELP[c] || "")}</div>`],
    ["Area", `${fmt(p.area_ha, 1)} ha${p.is_pivot ? ", centre pivot" : ""}`],
    [`Water pumped (${lv})`, none ? "none: not farmed by radar" : `${fmt(val("water_m3") / 1e3)} thousand m³/y`],
    [`Pumping electricity (${lv})`, none ? "none" : `${fmt(val("elec_kwh") / 1e3)} MWh/y`],
  ];
  if (WHEAT.has(c) || val("residue_t_dry") > 0) rows.push([`Collectable straw (${lv})`, `${fmt(val("residue_t_dry"), 1)} t dry/y`]);
  if (c === "palm_grove" || val("fronds_t_dry") > 0) rows.push([`Palm fronds (${lv})`, `${fmt(val("fronds_t_dry"), 1)} t dry/y`]);
  if (p.s2_winter_check != null || p.s2_summer_check != null) rows.push(["Sentinel-2 over the radar's dates",
    `winter ${green(p.s2_winter_check)}, summer ${green(p.s2_summer_check)}<div class="sub">${dis.length ? `Differs from the radar in ${dis.join(" and ")}.` : "Agrees with the radar in both seasons."} This is what the Radar check scores.</div>`]);
  if (p.s2_winter_active != null || p.s2_summer_active != null) rows.push(["Sentinel-2 over the whole season",
    `winter ${green(p.s2_winter_active)}, summer ${green(p.s2_summer_active)}${filled ? `<div class="sub">Counted as winter-farmed in the radar + Sentinel-2 tier.</div>` : ""}`]);
  if (TWO_SEASON.has(c)) {
    const none = "none: no national field covers half of this field";
    // Palm groves are set by tree cover, so the spring check does not decide their class (review issue qassim-2).
    rows.push(["National spring check", c === "palm_grove"
      ? `${p.spring_brown === true ? "brown in late spring" : p.spring_brown === false ? "green in late spring" : none}<div class="sub">Not used for palm groves: tree cover of 30% or more makes the field a palm grove.</div>`
      : p.spring_brown === true ? "brown in late spring (wheat, then a summer crop)" : p.spring_brown === false ? "green in late spring (perennial)" : none]);
  }
  if (num(p.plant_10kt) != null) rows.push(["Feeds", `Hypothetical biochar plant ${esc(p.plant_10kt)} in the central 10 kt/y layout (a modelled site)`]);
  $("fieldinfo").innerHTML = `<table class="fieldtable">${rows.map(([h, d]) => `<tr><th scope="row">${h}</th><td>${d}</td></tr>`).join("")}</table>`;
}
const pts = (a) => (Array.isArray(a) ? a : []).map((q) => Array.isArray(q) ? { x: tOf(q[0]), y: num(q[1]) } : null).filter((q) => q && !isNaN(q.x) && q.y != null);
function monthTicks(x0, x1) {
  const out = [], d = new Date(x0);
  let y = d.getUTCFullYear(), m = d.getUTCMonth() + 1;
  if (m % 2 === 0) m += 1;   // odd months: Jan, Mar, May, Jul, Sep, Nov
  for (let t = Date.UTC(y, m - 1, 1); t <= x1; m += 2, t = Date.UTC(y, m - 1, 1)) if (t >= x0) out.push(t);
  return out;
}
function makeChart(canvas, spec, x0, x1) {
  return new Chart(canvas, {
    type: "line",
    // Solid 2 px lines with a small dot per radar date in the series colour (no ring at rest, so the line never looks
    // dashed); an open dot marks the de-emphasised series (HH). The panel-coloured ring appears only on hover.
    data: { datasets: spec.sets.map(([label, data, color, open]) => ({ label, data, borderColor: color, backgroundColor: open ? CH.panel : color, borderWidth: open ? 1.5 : 2,
      pointRadius: open ? 2.5 : 2.25, pointBorderColor: color, pointBorderWidth: open ? 1.25 : 0, pointHitRadius: 10,
      pointHoverRadius: 5, pointHoverBorderColor: CH.panel, pointHoverBorderWidth: 2, pointHoverBackgroundColor: color,
      tension: 0, spanGaps: 40 * DAY, borderJoinStyle: "round", borderCapStyle: "round" })) },
    options: {
      maintainAspectRatio: false, animation: reduceMotion ? false : { duration: 250 },
      interaction: { mode: "nearest", axis: "x", intersect: false },
      layout: { padding: { top: 4, right: 4 } },
      scales: {
        x: { type: "linear", min: x0, max: x1, grid: { display: false }, border: { color: CH.axis },
          afterBuildTicks: (ax) => { ax.ticks = monthTicks(x0, x1).map((value) => ({ value })); },
          ticks: { autoSkip: false, maxRotation: 0, color: CH.muted, font: { size: 11 }, padding: 4,
            callback: (v, i) => { const d = new Date(v); return i === 0 || d.getUTCMonth() === 0 ? `${MON[d.getUTCMonth()]} ’${String(d.getUTCFullYear()).slice(2)}` : MON[d.getUTCMonth()]; } } },
        y: { min: spec.min, max: spec.max, suggestedMax: spec.sugMax, grid: { color: CH.grid, lineWidth: 1, drawTicks: false }, border: { display: false },
          ticks: { color: CH.muted, font: { size: 11 }, maxTicksLimit: 5, padding: 6,
            callback(v, i, t) {   // Chart.js's own number format, with a true minus sign
              const f = Chart.Ticks && Chart.Ticks.formatters && Chart.Ticks.formatters.numeric;
              return String(f ? f.call(this, v, i, t) : v).replace(/^-/, "−");
            } },
          title: { display: !!spec.unit, text: spec.unit, color: CH.muted, font: { size: 11 } } },
      },
      plugins: {
        title: { display: false },   // the figure caption above the canvas holds the title and the key
        legend: { display: false },
        tooltip: { backgroundColor: CH.panel, titleColor: CH.title, bodyColor: CH.ink, borderColor: CH.axis, borderWidth: 1, cornerRadius: 8, padding: 9,
          boxPadding: 4, usePointStyle: true, titleFont: { weight: "600" },
          callbacks: { title: (items) => items.length ? dayLabel(new Date(items[0].parsed.x).toISOString().slice(0, 10)) : "",
            labelPointStyle: () => ({ pointStyle: "line", rotation: 0 }),
            labelColor: (it) => ({ borderColor: it.dataset.borderColor, backgroundColor: it.dataset.borderColor, borderWidth: 2 }),
            label: (it) => `${it.dataset.label}: ${fmt(it.parsed.y, spec.d)}${spec.unit ? " " + spec.unit : ""}` } },
      },
    },
  });
}
// A chart's caption: its title and what it shows, and for two or more series a key with a line and point per series.
function chartCaption(spec) {
  const key = spec.sets.length > 1 ? `<ul class="chart-key">${spec.sets.map(([label, , color, open]) =>
    `<li><i class="lk${open ? " open" : ""}" style="--c:${color}" aria-hidden="true"></i>${esc(label)}</li>`).join("")}</ul>` : "";
  return `<span class="chart-t">${esc(spec.title)}</span>${spec.sub ? `<span class="chart-s">${esc(spec.sub)}</span>` : ""}${key}`;
}
function renderFieldCharts() {
  const p = state.fieldShown;
  if (!p) return;
  const boxes = [...document.querySelectorAll("#fieldbody .chart")];
  state.charts.forEach((ch) => ch.destroy());
  state.charts = [];
  const hide = (note) => { boxes.forEach((b) => { b.hidden = true; }); $("chartnote").textContent = note; };
  if (!state.ts) { hide("Loading this field's radar record…"); $("tsvalues").hidden = true; return; }
  const t = state.ts[String(p.id)];
  if (!t || typeof t !== "object") { hide("No radar record was exported for this field."); $("tsvalues").hidden = true; return; }
  $("tstable").innerHTML = tsTable(t);
  $("tsvalues").hidden = false;
  if (typeof Chart === "undefined") { hide("The charts need Chart.js, which did not load; the values are in the table below."); return; }
  if (!state.chartsStyled) { chartTokens(); Chart.defaults.font.family = getComputedStyle(document.body).fontFamily; Chart.defaults.color = CH.muted; state.chartsStyled = true; }
  const S = { hv: pts(t.hv), hh: pts(t.hh), coh: pts(t.coh), sm: pts(t.sm) };
  const xs = [].concat(...Object.values(S)).map((q) => q.x);
  if (!xs.length) { hide("This field's radar record is empty."); return; }
  const x0 = Math.min(...xs) - 6 * DAY, x1 = Math.max(...xs) + 6 * DAY;
  const specs = [
    { el: "tschart", title: "NISAR backscatter", sub: "Rises with crop canopy", unit: "dB", d: 1, sets: [["HV backscatter", S.hv, CH.hv], ["HH backscatter", S.hh, CH.hh, true]] },
    { el: "tschart2", title: "12-day coherence", sub: "0 = surface changed, 1 = unchanged", d: 2, min: 0, max: 1, sets: [["12-day coherence", S.coh, CH.ink]] },
    { el: "tschart3", title: "Soil moisture", sub: "200 m grid", unit: "m³/m³", d: 2, min: 0, sugMax: 0.4, sets: [["Soil moisture", S.sm, CH.ink]] },
  ];
  specs.forEach((s, i) => {
    s.sets = s.sets.filter(([, d]) => d.length);
    if (!boxes[i]) return;
    boxes[i].hidden = !s.sets.length;
    const cap = $(s.el + "-cap");
    if (cap) cap.innerHTML = s.sets.length ? chartCaption(s) : "";
    if (s.sets.length) state.charts.push(makeChart($(s.el), s, x0, x1));
  });
  // Name the long break between the seasons, which the time axis shows as a gap in the lines.
  const days = [...new Set(xs)].sort((a, b) => a - b);
  let gap = null;
  for (let i = 1; i < days.length; i++) if (days[i] - days[i - 1] > 40 * DAY && (!gap || days[i] - days[i - 1] > gap[1] - gap[0])) gap = [days[i - 1], days[i]];
  const iso = (v) => new Date(v).toISOString().slice(0, 10);
  $("chartnote").textContent = (gap ? `NISAR has no dates between ${dayLabel(iso(gap[0]))} and ${dayLabel(iso(gap[1]))}, so the lines break there. ` : "") +
    "HV is the signal the farmed rule uses; HH and the other two signals are shown for context.";
}
function tsTable(t) {
  const cols = [["hv", "HV dB", 1], ["hh", "HH dB", 1], ["coh", "Coherence", 2], ["sm", "Soil moisture m³/m³", 2]].filter(([k]) => Array.isArray(t[k]) && t[k].length);
  const maps = Object.fromEntries(cols.map(([k]) => [k, new Map(t[k].filter(Array.isArray))]));
  const dates = [...new Set(cols.flatMap(([k]) => [...maps[k].keys()]))].sort();
  return `<table><tr><th>Date</th>${cols.map(([, h]) => `<th class="num">${h}</th>`).join("")}</tr>${dates.map((d) =>
    `<tr><td>${esc(d)}</td>${cols.map(([k, , dd]) => `<td class="num">${maps[k].has(d) ? fmt(maps[k].get(d), dd) : "–"}</td>`).join("")}</tr>`).join("")}</table>`;
}
function exampleLayer() {
  const ex = state.byId[EXAMPLE_FIELD];
  if (ex && fieldClass(ex.feature.properties) === "winter_only") return ex;
  let best = null;   // fallback: the largest winter-only field that Sentinel-2 also sees green in winter only
  state.fields.features.forEach((f) => {
    const p = f.properties || {};
    if (fieldClass(p) !== "winter_only" || p.s2_winter_check === false || p.s2_summer_check === true) return;
    if (state.ts && !state.ts[String(p.id)]) return;
    if (!best || (num(p.area_ha) || 0) > (num(best.area_ha) || 0)) best = p;
  });
  return best ? state.byId[best.id] : null;
}
function showExample(zoom) {
  const lyr = exampleLayer();
  if (!lyr) { $("examplefield").hidden = true; return; }
  if (!$("showfields").checked) { $("showfields").checked = true; state.fieldsLayer.addTo(map); raiseMarkers(); }
  if (zoom) {
    try { const b = lyr.getBounds(); map.fitBounds(b, { maxZoom: 14, animate: !reduceMotion, ...fitOpts(b, 24, 14) }); } catch (e) { /* keep the view */ }
  }
  showField(lyr.feature.properties, true, lyr);
}
function loadTs() {
  if (!state.tsPromise) {
    state.tsPromise = getJSON("data/timeseries.json").catch(() => ({})).then((ts) => {
      state.ts = ts && typeof ts === "object" ? ts : {};
      if (state.fieldShown) { safe(renderFieldInfo, "fieldinfo"); safe(renderFieldCharts, "chartnote"); }
      return state.ts;
    });
  }
  return state.tsPromise;
}

/* ---------- Method ---------- */
function hvDates() {
  const hv = overlaysFor("NISAR HV backscatter").filter((o) => isDate(o.date)).map((o) => o.date).sort();
  return { all: hv, winter: hv.filter((d) => seasonOf(d) === "winter"), summer: hv.filter((d) => seasonOf(d) === "summer") };
}
function renderSteps() {
  const S = get(state.summary, "supply") || {}, V = get(state.summary, "validation") || {}, nf = S.national_flags || {}, D = hvDates();
  const span = (a) => a.length > 1 ? `${dayLabel(a[0])} to ${dayLabel(a[a.length - 1])}` : a.map(dayLabel).join("");
  const dates = D.all.length ? ` Here: ${D.all.length} HV dates, ${D.winter.length} in winter (${span(D.winter)}) and ${D.summer.length} in summer (${span(D.summer)}).` : "";
  const head = get(S, "pumping_head", "rule");
  const matched = num(nf.matched_fields) != null ? ` (${fmt(nf.matched_fields)} fields, ${fmt(nf.matched_ha)} ha matched)` : "";
  $("steps").innerHTML = [
    "<b>Fields</b> are mapped from ESA Sentinel-2 greenness: seasonal maximum NDVI from offset-corrected surface reflectance, 20 m.",
    `<b>NISAR L-band radar</b> (NASA-ISRO) gives three independent signals per field every 12 days: HV backscatter (crop canopy), 12-day coherence (surface being worked or irrigated) and soil moisture.${dates}`,
    `A field is <b>farmed in a season</b> when ${ruleText(V)}`,
    `<b>Classes</b> follow the national rules: a field farmed in winter only is a winter crop, treated as wheat; in summer only, a summer crop; in both seasons, wheat followed by a summer crop where the national Sentinel-2 spring check finds the field brown in late spring, otherwise year-round fodder; with tree cover of 30% or more and farmed in both seasons, a palm grove. The spring check comes from the national field covering at least half of each field${matched}; fields without one stay year-round, as in the national run.`,
    `<b>Water</b> = farmed area × irrigation depth by class (published for winter and year-round fields; summer crops get half the perennial depth, a rotation gets both) ÷ pivot efficiency; <b>energy</b> = water × pumping head ÷ pump efficiency, with ${head ? esc(head) : "the depth to water as the head"}; <b>CO₂</b> for grid or diesel pumps.`,
    "<b>Wheat straw</b> from winter-only and rotation fields and <b>palm fronds</b> from palm groves feed a model that places <b>hypothetical biochar plants</b> (none exists or is planned), with transport emissions for feed in and char out (back to the fields, or to the nearest existing cement plant). Removal is credited with the Puro.earth 2025 soil persistence model for both outlets, each feed with its own char factors; only truck emissions are subtracted, so it is a technical potential.",
  ].map((t) => `<li>${t}</li>`).join("");
}
function renderDiffers() {
  // qd-1, tx-11: why this run's figures differ from the national run's for the same ground.
  const S = get(state.summary, "supply") || {}, V = get(state.summary, "validation") || {}, nf = S.national_flags || {}, N = state.national, D = hvDates();
  const t = V.hv_threshold_db || {}, boxes = (N && N.boxes) || [];
  const farmed = num(S.farmed_ha) ?? sum(FARMED.map((k) => get(S, "area_ha_by_class", k)));
  let intro = boxes.length ? `The national results map this ground too, in regions ${esc(list(boxes.map((r) => r.id)))}, but in a separate run, so their figures for the same fields differ and the two are never added together.` :
    "The national results map this ground too, in a separate run with fewer radar dates and a coarser grid, so their figures for the same fields differ and the two are never added together.";
  const same = N && N.same;
  if (same && same.farmed > 0 && farmed) intro += ` Inside this cluster's bounding box the national run finds <b>${fmt(same.farmed)} ha</b> farmed on ${fmt(same.field_ha)} ha of fields; this run finds <b>${fmt(farmed)} ha</b> on ${fmt(S.field_ha)} ha, ${fmt(Math.abs(100 * (farmed / same.farmed - 1)))}% ${farmed >= same.farmed ? "more" : "less"} farmed area.`;
  const rngTxt = (a, d = 0) => { const v = a.filter((x) => num(x) != null); if (!v.length) return null; const lo = Math.min(...v), hi = Math.max(...v); return lo === hi ? fmt(lo, d) : `${fmt(lo, d)}–${fmt(hi, d)}`; };
  let nat = "the national boxes read fewer dates (at most 3 in winter and 4 in summer), each against a threshold from its own desert";
  if (boxes.length) {
    const nw = boxes.map((r) => (r.dates || []).filter((d) => seasonOf(d) === "winter").length), ns = boxes.map((r) => (r.dates || []).filter((d) => seasonOf(d) === "summer").length);
    const tw = rngTxt(boxes.map((r) => get(r, "validation", "thresholds_db", "winter")), 1), ts = rngTxt(boxes.map((r) => get(r, "validation", "thresholds_db", "summer")), 1);
    nat = `the national boxes read ${rngTxt(nw.map((w, i) => w + ns[i]))} dates (${rngTxt(nw)} in winter, ${rngTxt(ns)} in summer), each against a threshold from its own desert${tw && ts ? ` (${tw} dB in winter, ${ts} dB in summer)` : ""}`;
  }
  const here = D.all.length ? `this run reads ${D.all.length} HV dates (${D.winter.length} in winter, ${D.summer.length} in summer)` : "this run reads more radar dates";
  const thr = num(t.winter) != null ? ` (${fmt(t.winter, 2)} dB in winter, ${fmt(t.summer, 2)} dB in summer)` : "";
  const flags = num(nf.matched_fields) != null ? ` from the national field covering at least half of each field (${fmt(nf.matched_fields)} fields, ${fmt(nf.matched_ha)} ha; the other ${fmt(nf.unmatched_fields)} fields, ${fmt(nf.unmatched_ha)} ha, have none and stay year-round if farmed in both seasons${nf.national_table_current === false ? "; transferred from an earlier version of the national field table" : ""})` : "";
  $("differs").innerHTML = `<p class="note">${intro}</p><ul class="note differs">
    <li><b>Radar detection</b>, about two-thirds of the farmed-area gap: ${here} against one threshold from this cluster's own desert${thr}; ${nat}.</li>
    <li><b>Field outlines</b>, about one-third: fields here come from 20 m Sentinel-2 composites of up to 30 scenes per tile and orbit with no WorldCover filter, the national fields from 40 m composites of up to 8 scenes, so the two runs outline partly different fields.</li>
    <li><b>Classes</b> follow the same rules in both runs: this run takes the national spring check${flags} and marks palm groves from each field's own WorldCover tree cover.</li>
    <li><b>Sentinel-2 winter window</b>, used by the radar + Sentinel-2 tier: ${windowText()}.</li></ul>
    <p class="note">The split of the gap comes from a field-by-field comparison of the two runs on this ground. Use the national results for totals; this page shows what more radar dates and a finer grid add, field by field.</p>`;
}
// The Sentinel-2 winter windows of the two runs: s2_filled.windows when exported, otherwise read from the rule texts
// (this run's s2_filled.rule and fills.winter_fill.rule; the national summary's s2_filled.rule).
function windowText() {
  const SF = get(state.summary, "supply", "s2_filled") || {}, W = obj(SF.windows) || {};
  const DAY_RE = "(\\d{1,2} [A-Z][a-z]{2})\\s*[-–]\\s*(\\d{1,2} [A-Z][a-z]{2})";
  const rx = (s, lead) => { const m = String(s || "").match(new RegExp(lead + DAY_RE)); return m ? [m[1], m[2]] : null; };
  const arr = (a) => Array.isArray(a) && a.length === 2 ? a.map((d) => { const m = String(d).match(/^(?:\d{4}-)?(\d{2})-(\d{2})$/); return m ? `${+m[2]} ${MON[+m[1] - 1]}` : String(d); }) : null;
  const here = arr(W.winter) || rx(SF.rule, "s2_winter_active over ") || rx(get(SF, "fills", "winter_fill", "rule"), "green over ");
  const nat = arr(W.national_winter) || rx(get(state, "national", "s2rule"), "s2_winter_active over ") || rx(SF.rule, "national flags use ");
  const long = (d) => String(d).replace(/\b([A-Z][a-z]{2})\b/, (m) => MONTH[MON.indexOf(m)] || m);
  const dayOf = (d) => { const m = String(d).match(/(\d{1,2}) ([A-Z][a-z]{2})/); const i = m ? MON.indexOf(m[2]) : -1; return i < 0 ? null : ((i + 2) % 12) * 31 + +m[1]; };   // season order, November first
  // the day after a window end ("31 Jan" gives "1 February"): wheat greening after both ends is missed by both runs
  const next = (d) => { const m = String(d).match(/(\d{1,2}) ([A-Z][a-z]{2})/); const t = new Date(Date.UTC(2001, MON.indexOf(m[2]), +m[1] + 1)); return `${t.getUTCDate()} ${MONTH[t.getUTCMonth()]}`; };
  if (!here || !nat) return "shorter here than in the national run, so wheat that greens only late in winter is missed here";
  const a = dayOf(here[1]), b = dayOf(nat[1]);
  if (a == null || b == null || a === b) return `to ${long(here[1])} here and nationally`;
  return `to ${long(here[1])} here, to ${long(nat[1])} nationally, so wheat that greens only from ${next(a < b ? here[1] : nat[1])} to ${long(a < b ? nat[1] : here[1])} is missed ${a < b ? "here" : "nationally"}`;
}
function renderHead() {
  const H = get(state.summary, "supply", "pumping_head");
  if (!H || typeof H !== "object") { $("headinfo").innerHTML = ""; return; }
  const c = (k) => get(H, k, "central");
  const comp = H.elec_kwh_by_component || {}, parts = [["static depth", "static_depth"], ["drawdown", "drawdown"], ["pivot pressure", "pivot_pressure"]];
  const tot = sum(parts.map(([, k]) => get(comp, k, "central")));
  const split = tot ? `Of the central electricity, ${list(parts.map(([n, k]) => `${n} gives ${pct(get(comp, k, "central") / tot)}`))}.` : "";
  const mh = H.mean_head_m || {}, cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
  const span = (k, d = 0) => { const o = H[k]; return o && num(o.low) != null && num(o.high) != null ? `${fmt(o.low, d)}–${fmt(o.high, d)} m` : null; };
  const spans = [["static depth to water", span("pumping_lift_m")], ["drawdown", span("drawdown_m")], ["pivot pressure", span("pivot_pressure_head_m", 1)]].filter(([, s]) => s);
  // review issue 6: the head rule is read from pumping_head.detail; the paraphrase is only for an older summary without it.
  const detail = typeof H.detail === "string" && H.detail ? esc(plain(H.detail).replace(/ × head \/ /, " × head ÷ ").replace(/\.?$/, ".")) :
    "Pumping electricity per field = pumped water × ρg × head ÷ pump wire-to-water efficiency, as in the national run. Head = static depth to water (the national run's Qassim lift) + drawdown + pivot pressure on centre pivots only, each at the estimate's own level.";
  const pg = obj(H.palm_grove_pivots) || {}, pgKwh = num(get(pg, "pressure_elec_kwh_not_charged", "central"));
  // the detail paragraph above may already state the palm-grove rule; then this paragraph gives only the numbers
  const pgRule = typeof H.detail === "string" && /palm groves get no pivot pressure/i.test(H.detail);
  const NOTE_LABEL = { depth_age: "Sensitivity, in no total" };
  const notes = Object.entries(obj(H.notes) || {}).filter(([, v]) => typeof v === "string" && v).map(([k, v]) => [NOTE_LABEL[k], plain(v).replace(/\.?$/, ".")]);
  $("headinfo").innerHTML = `<details class="more"><summary>Pumping head and its caveats</summary>
    ${H.rule && !H.detail ? `<p><b>${esc(cap(H.rule))}.</b> ${detail}</p>` : `<p>${detail}</p>`}
    ${spans.length ? `<p>Low to high: ${list(spans.map(([n, s]) => `${n} ${s}`))}, each at the estimate's own level.</p>` : ""}
    ${H.pivot_rule ? `<p>${esc(cap(plain(H.pivot_rule)))}: ${fmt(H.pivot_fields)} pivots (${fmt(H.pivot_ha)} ha) take ${pct(c("pivot_share_of_pumped_water"))} of the pumped water.</p>` : ""}
    ${num(pg.fields) > 0 ? `<p>Pivot-shaped palm groves${pgRule ? "" : " get no pivot pressure"}: ${fmt(pg.fields)} fields (${fmt(pg.ha)} ha)${pgKwh != null ? `; pivot pressure on their water would add ${fmt(pgKwh / 1e6, 1)} GWh a year (central), which is in no total` : ""}.</p>` : ""}
    ${num(mh.central) != null ? `<p>Mean head ${fmt(mh.central)} m (central; ${fmt(mh.low)} m low, ${fmt(mh.high)} m high), weighted by pumped water. ${split}</p>` : ""}
    ${notes.map(([h, n]) => `<p>${h ? `<b>${esc(h)}.</b> ` : ""}${esc(n)}</p>`).join("")}</details>`;
}

const PARAM_GROUPS = [
  ["Biochar plants", ["plant_sizes_t_dry", "min_load_fraction"]],
  ["Wheat straw", ["wheat_grain_yield_t_ha", "straw_t_dry_per_ha", "collectable_fraction", "straw_dry_matter", "alfalfa_collectable_residue_t_ha"]],
  ["Palm fronds", ["palms_per_ha", "palm_residue_kg_dry_per_palm", "palm_frond_dry_matter"]],
  ["Irrigation water", ["irrigation_mm_winter_only", "irrigation_mm_summer_crop", "irrigation_mm_year_round", "pivot_application_efficiency"]],
  ["Pumping energy and CO₂", ["pumping_lift_m", "drawdown_m", "pivot_pressure_head_m", "pump_wire_to_water_eff", "grid_kgco2e_per_kwh", "diesel_water_kwh_per_litre", "diesel_kgco2e_per_litre"]],
  ["Transport", ["road_circuity", "truck_kgco2e_per_tkm"]],
  ["Char and crediting", ["char_yield_dry", "char_c_org", "h_c_org_straw", "palm_char_yield_dry", "palm_char_c_org", "h_c_org_fronds", "soil_temp_c", "straw_char_persistence", "fronds_char_persistence", "cement_retention"]],
];
const PARAM_LABEL = {
  plant_sizes_t_dry: "Plant sizes (kt dry feed / year)", min_load_fraction: "Minimum load to place a plant",
  wheat_grain_yield_t_ha: "Wheat grain yield (t/ha)", straw_t_dry_per_ha: "Collectable straw (t dry/ha)", collectable_fraction: "Collectable share of that straw",
  straw_dry_matter: "Straw dry matter (for haulage)", alfalfa_collectable_residue_t_ha: "Alfalfa residue collected (t/ha)",
  palms_per_ha: "Palms per ha", palm_residue_kg_dry_per_palm: "Fronds per palm (kg dry / year)", palm_frond_dry_matter: "Frond dry matter (for haulage)",
  irrigation_mm_winter_only: "Irrigation depth, winter crop (mm)", irrigation_mm_summer_crop: "Irrigation depth, summer crop (mm)",
  irrigation_mm_year_round: "Irrigation depth, year-round (mm)", pivot_application_efficiency: "Irrigation application efficiency",
  pumping_lift_m: "Static depth to water (m)", drawdown_m: "Drawdown while pumping (m)", pivot_pressure_head_m: "Pivot pressure head (m)",
  pump_wire_to_water_eff: "Pump wire-to-water efficiency", grid_kgco2e_per_kwh: "Grid electricity (kg CO₂e/kWh)",
  diesel_water_kwh_per_litre: "Diesel pump water work (kWh/litre)", diesel_kgco2e_per_litre: "Diesel (kg CO₂e/litre)",
  road_circuity: "Road distance ÷ straight line", truck_kgco2e_per_tkm: "Truck (kg CO₂e per tonne-km)",
  char_yield_dry: "Straw char yield (t char / t dry feed)", char_c_org: "Straw char organic carbon", h_c_org_straw: "Straw char H/C_org (molar)",
  palm_char_yield_dry: "Frond char yield (t char / t dry feed)", palm_char_c_org: "Frond char organic carbon", h_c_org_fronds: "Frond char H/C_org (molar)",
  soil_temp_c: "Soil temperature (°C)", straw_char_persistence: "Straw char carbon kept over 200 years", fronds_char_persistence: "Frond char carbon kept over 200 years",
  cement_retention: "Char carbon kept in cement in service (reported, not credited)",
};
const INVERTED = new Set(["pivot_application_efficiency"]);   // model/supply.py: the Low estimate uses the high efficiency
const AS_PCT = new Set(["min_load_fraction", "collectable_fraction", "straw_dry_matter", "palm_frond_dry_matter", "pivot_application_efficiency",
  "pump_wire_to_water_eff", "char_c_org", "palm_char_c_org", "straw_char_persistence", "fronds_char_persistence", "cement_retention"]);
function smart(x, asPct) {
  const v = num(x);
  if (v == null) return "–";
  if (asPct) return (100 * v).toLocaleString("en-US", { maximumFractionDigits: 1 }) + "%";
  const a = Math.abs(v), d = Number.isInteger(v) || a >= 100 ? 0 : a >= 10 ? 1 : a >= 1 ? 2 : 3;
  return v.toLocaleString("en-US", { maximumFractionDigits: d });
}
function renderParams() {
  const P = get(state.summary, "params");
  if (!P || typeof P !== "object") { $("params").innerHTML = "<p class='note'>The factor table is missing from the results summary.</p>"; return; }
  const keys = Object.keys(P).filter((k) => !k.startsWith("_") && P[k] && typeof P[k] === "object");
  const grouped = new Set(PARAM_GROUPS.flatMap(([, ks]) => ks));
  const groups = PARAM_GROUPS.map(([g, ks]) => [g, ks.filter((k) => keys.includes(k))]).concat([["Other", keys.filter((k) => !grouped.has(k))]]).filter(([, ks]) => ks.length);
  const show = (x, k) => Array.isArray(x) ? x.map((y) => smart(num(y) / 1000)).join(", ") : smart(x, AS_PCT.has(k));
  const row = (k) => {
    const v = P[k], inv = INVERTED.has(k), lo = inv ? v.high : v.low, hi = inv ? v.low : v.high;
    const vals = [lo, v.central, hi].map((x) => show(x, k));
    const cells = vals.every((x) => x === vals[0]) ? `<td class="num" colspan="3">${vals[0]}</td>` : vals.map((x) => `<td class="num">${x}</td>`).join("");
    return `<tr><td>${esc(PARAM_LABEL[k] || k.replaceAll("_", " "))}${inv ? " †" : ""}</td>${cells}</tr>${v.source ? `<tr class="src"><td colspan="4">${esc(plain(v.source))}</td></tr>` : ""}`;
  };
  $("params").innerHTML = `<table class="params"><tr><th>Factor</th><th class="num">Low</th><th class="num">Central</th><th class="num">High</th></tr>
    ${groups.map(([g, ks]) => `<tr class="grp"><th colspan="4" scope="colgroup">${esc(g)}</th></tr>${ks.map(row).join("")}`).join("")}</table>
    <p class="note">Each column holds the value that estimate uses; one value across all three means it does not vary. The source of each factor is under it.${keys.some((k) => INVERTED.has(k)) ? " † The Low estimate takes the higher efficiency (less water pumped) and the High estimate the lower." : ""}</p>`;
}

/* ---------- national comparison (deferred: the first view does not wait for it) ---------- */
async function loadNational() {
  let N;
  try { N = await getJSON("data/national/summary.json"); } catch (e) { return; }
  const b = state.fieldsLayer && state.fieldsLayer.getBounds();
  if (!N || !Array.isArray(N.regions) || !b || !b.isValid()) return;
  const W = b.getWest(), E = b.getEast(), So = b.getSouth(), No = b.getNorth();
  const boxes = N.regions.filter((r) => r && r.status === "ok" && Array.isArray(r.bbox) && r.bbox.length === 4 &&
    r.bbox[0] < E && r.bbox[2] > W && r.bbox[1] < No && r.bbox[3] > So);
  state.national = { boxes, same: null, s2rule: get(N, "summary", "s2_filled", "rule") };
  safe(renderDiffers, "differs"); safe(renderLead, "lead");
  if (!boxes.length) return;
  try {
    const rows = await Promise.all(boxes.map((r) => getJSON(`data/national/fields/${encodeURIComponent(r.id)}.json`)));
    let farmed = 0, ha = 0, n = 0;
    rows.forEach((a) => (Array.isArray(a) ? a : []).forEach((q) => {
      if (!Array.isArray(q)) return;
      const [lon, lat, area, code] = q;
      if (!(lon >= W && lon <= E && lat >= So && lat <= No)) return;
      n += 1; ha += num(area) || 0;
      if (NATIONAL_FARMED.has(code)) farmed += num(area) || 0;
    }));
    state.national.same = n ? { farmed, field_ha: ha, fields: n } : null;
    safe(renderDiffers, "differs");
  } catch (e) { /* the comparison sentence is left out */ }
}

// The first data did not load: say so in the panel too, hide the controls that have nothing to act on, and keep the
// Method tab (static text) readable.
function showFailure() {
  const alert = (role) => `<p class="alert"${role ? ' role="alert"' : ""}>${ICO("alert")}<span>The results could not be loaded. Reload the page to try again; the Method tab still explains how they are made.</span></p>`;
  ["overview", "check", "plants", "field"].forEach((n, i) => {
    const tab = $("tab-" + n);
    if (!tab) return;
    [...tab.children].forEach((c) => { c.hidden = true; });
    tab.insertAdjacentHTML("afterbegin", alert(i === 0));
  });
  if ($("params") && !$("params").innerHTML.trim()) $("params").innerHTML = `<p class="note">The factor table is part of the results summary, which did not load.</p>`;
  const t = $("maptools");
  if (t && !state.fieldsLayer) t.hidden = true;
}

window.appStarted = true;  // read by the check that follows app.js in qassim.html
wireTabs();
init().catch((e) => {
  console.error(e);
  const box = $("loading");  // still there if the first data failed to load
  const msg = `Could not load data: ${e && e.message ? e.message : e}`;
  if (box) { box.textContent = msg; box.classList.remove("is-busy"); box.classList.add("error"); }
  else document.body.insertAdjacentHTML("beforeend", `<p style="padding:16px">${esc(msg)}</p>`);
  safe(showFailure);
  const h = location.hash.slice(1);
  if ($("tab-" + h)) openTab(h, { hash: false, scroll: false });
});
