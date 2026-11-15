/* Circle to Char: what-if scenarios.
   Data: data/scenarios/scenarios.json, plants_<id>.json and watchlist.json (scripts/export_scenarios.py), plus
   data/national/summary.json for the links to the national page. Every figure on the page comes from these files:
   a missing key hides its line or shows "–", and nothing throws.
   Central estimates unless a range is named. P5–P95 is the Monte Carlo interval; the all-low / all-high corners set
   every factor to a bound at once and are not probability intervals. Rows marked "not credited" (family C_upside)
   are hypothetical upper bounds and never sit in a credited column. */
"use strict";

const S = { data: null, nat: null, ctx: {}, sel: null, plants: {}, sites: null, plantLayer: null, cementLayer: null,
  watchLayer: null, watch: null, watchCounts: null, drawSeq: 0, fitted: false, autoView: null, mapNote: null };

/* ---------- Small helpers ---------- */
const $ = (id) => document.getElementById(id);
const ok = (v) => typeof v === "number" && isFinite(v);
const obj = (v) => (v && typeof v === "object" && !Array.isArray(v)) ? v : null;
const arr = (v) => Array.isArray(v) ? v : [];
const get = (o, path) => path.split(".").reduce((a, k) => (a == null ? undefined : a[k]), o);
const fmt = (v, d = 0) => {
  if (v == null || v === "" || isNaN(v)) return "–";
  let n = Number(v);
  if (Math.abs(n) < 0.5 * Math.pow(10, -d)) n = 0;  // no "-0.00"
  return n.toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d });
};
const pct = (x, d = 0) => ok(x) ? fmt(100 * x, d) + "%" : "–";
const share = (x) => ok(x) ? `${+(100 * x).toFixed(2)}%` : "–";   // 0.015 -> "1.5%", 0.25 -> "25%"
const esc = (t) => String(t == null ? "" : t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const bn = (v, d = 2) => ok(v) ? fmt(v / 1e9, d) : "–";
const kt = (v, d = 0) => ok(v) ? fmt(v / 1e3, d) : "–";
const mt = (v, d = 2) => ok(v) ? fmt(v / 1e6, d) : "–";
const smt = (v) => ok(v) ? (mt(v) === mt(0) ? "" : v > 0 ? "+" : "−") + mt(Math.abs(v)) : "–";   // signed Mt, true minus sign
const C = (o) => ok(o) ? o : (obj(o) && ok(o.central) ? o.central : null);
const cap = (t) => t ? t.charAt(0).toUpperCase() + t.slice(1) : "";
const list = (xs) => xs.length < 2 ? xs.join("") : xs.slice(0, -1).join(", ") + " and " + xs[xs.length - 1];
const plural = (n, one, many) => `${fmt(n)} ${n === 1 ? one : many}`;
const safe = (name, fn, fallback) => {
  try { return fn(); } catch (e) { if (window.console) console.error("scenarios: " + name, e); return fallback; }
};
async function j(p) {
  const r = await fetch(p);
  if (!r.ok) throw new Error(`${p}: HTTP ${r.status}`);
  return r.json();
}
const narrow = () => window.matchMedia ? window.matchMedia("(max-width: 860px)").matches : window.innerWidth <= 860;
const isoDate = (s) => (typeof s === "string" && /^\d{4}-\d{2}-\d{2}$/.test(s)) ? new Date(s + "T00:00:00Z") : null;
const hav = (lon1, lat1, lon2, lat2) => {   // great-circle km
  const r = Math.PI / 180, a = Math.sin((lat2 - lat1) * r / 2) ** 2 + Math.cos(lat1 * r) * Math.cos(lat2 * r) * Math.sin((lon2 - lon1) * r / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.min(1, Math.sqrt(a)));
};
const sentence = (t) => { const s = String(t == null ? "" : t).trim(); return s ? cap(s) + (/[.!?]$/.test(s) ? "" : ".") : ""; };
/* Record notes are written for the pipeline: drop the script, file and column names a reader cannot use (out/ is not
   published) and name the rows in the page's own words. Only references go; every caveat in the text stays. */
const plain = (t) => String(t == null ? "" : t)
  .replace(/;?\s*full rule:[^;]*?\b(?:out|data)\/[\w.\/-]+\.json\b/gi, "")
  .replace(/\s+(?:of|in|from)\s+model\/[\w.\/-]+\.py\b/gi, "").replace(/\s*\bmodel\/[\w.\/-]+\.py\b/gi, "")
  .replace(/\s*\(s2_tier\)/gi, "")
  .replace(/:\s*family B_s2\b[^.]*?\brows\b,?/gi, ": the radar + Sentinel-2 fodder-halt rows, the Sentinel-2 row of the floor-to-ceiling table and the radar + Sentinel-2 robustness runs,")
  .replace(/\s+that\s+(?:data|out)\/[\w.\/-]+\.(?:csv|json)\s+carries\s+and\b/gi, " that")
  .replace(/\bclass_s2\b/g, "Sentinel-2 class")
  .replace(/\s{2,}/g, " ").replace(/\s+([,.;:)])/g, "$1").trim();

/* Map colours: the shared data-colour tokens in style.css (fallbacks are the same values) */
const css = (name, fb) => safe("css", () => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fb, fb);
const MARK = { cement: css("--c-cement", "#5b2c83"), soil: css("--c-soil", "#0f6e6a"), year: css("--c-year", "#2e9e5b") };
/* Cement-ring fill: the cement colour mixed with white (35:65), the same tint as the key's "used" ring glyph */
const tint = (hex, w) => {
  const m = /^#?([0-9a-f]{6})$/i.exec(String(hex).trim());
  if (!m) return "#c6b5d4";
  const n = parseInt(m[1], 16);
  return "#" + [16, 8, 0].map((b) => Math.round(w * ((n >> b) & 255) + (1 - w) * 255).toString(16).padStart(2, "0")).join("");
};
const CEM_TINT = tint(MARK.cement, 0.35);

/* Names as the national page spells them; the data use the boundary file's names ("Al Jawf Region", "Hayel Region") */
const ADMIN = { "Al Jawf": "Al-Jouf", "Al-Jawf": "Al-Jouf", "Al Jouf": "Al-Jouf", "Hayel": "Hail", "Ha'il": "Hail",
  "Al-Qassim": "Qassim", "Al Qassim": "Qassim", "Eastern": "Eastern Province", "'Asir": "Asir", "Jizan": "Jazan",
  "Al Bahah": "Al-Baha", "Al Baha": "Al-Baha", "Al Madinah": "Madinah", "N. Borders": "Northern Borders" };
const admin = (r) => { const k = String(r == null ? "" : r).replace(/\s+Region$/i, "").trim(); return ADMIN[k] || k; };
const inSentence = (n) => n === "Eastern Province" ? "the Eastern Province" : n;
const FEED = { straw: "wheat straw", fronds: "palm fronds", litter: "poultry litter", manure: "manure" };
const FEEDC = { straw: "straw", fronds: "frond", litter: "litter", manure: "manure" };   // "straw and frond chars"
const RADAR_FEEDS = ["straw", "fronds"];
/* MEWA's halt date, a policy date, used only if data/national/summary.json carries no fodder_halt.effective */
const HALT_DATE = "2026-11-16";

/* ---------- Scenario records ---------- */
const SC = () => obj(S.data && S.data.scenarios) || {};
const sc = (id) => { const x = obj(SC()[id]); return x ? Object.assign({ id }, x) : null; };
const fam = (...fs) => Object.entries(SC()).filter(([, v]) => obj(v) && fs.includes(v.family)).map(([k, v]) => [k, Object.assign({ id: k }, v)]);
const isUpside = (x) => !!(x && (x.upside === true || x.family === "C_upside"));
const feedsOf = (x) => Array.isArray(x && x.feeds) ? x.feeds.slice() : Object.keys(obj(x && x.supply_by_feed_t) || {});
const used = (x, f) => get(x, "feed_used_by_feed_t." + f);
const displayName = (id, x) => {
  const n = String((x && x.name) || id);
  return id === "C0_published" ? n.replace(/\s*\(gross\)\s*$/i, "") : n;   // "outlets unconstrained", not "gross"
};
const plantsTxt = (x) => ok(x && x.plants) ? plural(x.plants, "plant", "plants") : "";
const dose = (x) => share(x && x.dosage);

/* ---------- Map ---------- */
const map = (() => {
  if (!window.L) return null;
  try {
    const m = L.map("map", { preferCanvas: true, zoomSnap: 0.25 }).setView([24.5, 44.5], 5);
    L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
      maxZoom: 17, attribution: "Imagery © Esri, Maxar, Earthstar Geographics" }).addTo(m);
    return m;
  } catch (e) { if (window.console) console.error("scenarios: map", e); return null; }
})();

function mapNote(text, kind) {
  const el = $("mapnote");
  if (!el) return;
  el.classList.toggle("error", kind === "error");
  el.classList.toggle("upside", kind === "upside");
  el.textContent = text || "";
  el.hidden = !text;
}
const plantNote = () => mapNote(S.mapNote ? S.mapNote.text : "", S.mapNote ? S.mapNote.kind : null);

/* ---------- Tabs: follow the URL hash (#floor, #fodder, #retrofits, #biochar, #assumptions) ---------- */
const TABS = ["floor", "fodder", "retrofits", "biochar", "assumptions"];
const LEGACY = { A: "floor", B: "fodder", R: "retrofits", C: "biochar", P: "assumptions" };

function openTab(name, opt = {}) {
  const n = LEGACY[name] || name;
  if (!TABS.includes(n) || !$("tab-" + n)) return false;
  document.querySelectorAll('.tabs [role="tab"]').forEach((b) => {
    const on = b.dataset.tab === n;
    b.classList.toggle("on", on);
    b.setAttribute("aria-selected", on ? "true" : "false");
    b.tabIndex = on ? 0 : -1;
  });
  document.querySelectorAll("aside .tab").forEach((p) => p.classList.toggle("on", p.id === "tab-" + n));
  const btn = $("tabbtn-" + n), strip = btn && btn.parentElement;
  if (strip && (btn.offsetLeft < strip.scrollLeft || btn.offsetLeft + btn.offsetWidth > strip.scrollLeft + strip.clientWidth)) {
    strip.scrollLeft = Math.max(0, btn.offsetLeft - 16);   // keep the chosen tab visible in a strip that scrolls
  }
  if ((opt.hash !== false || name !== n) && location.hash.slice(1) !== n) {   // an old #A–#P link is rewritten
    try { history.replaceState(null, "", "#" + n); } catch (e) { /* sandboxed or file: page */ }
  }
  if (opt.scroll !== false) {
    const aside = document.querySelector("aside");
    if (aside && !narrow()) aside.scrollTop = 0;   // a tab never opens mid-content
    else if (aside) {   // phones: bring the panel top under the site bar only if it is scrolled past
      const bar = document.querySelector("nav.site"), h = bar ? bar.offsetHeight : 44, top = aside.getBoundingClientRect().top;
      if (top < h) window.scrollTo(0, Math.max(0, top + window.scrollY - h));
    }
  }
  if (opt.focus && btn) btn.focus();
  return true;
}

function setupTabs() {
  const strip = document.querySelector('.tabs[role="tablist"]');
  if (!strip) return;
  strip.addEventListener("click", (e) => { const b = e.target.closest('[role="tab"]'); if (b) openTab(b.dataset.tab); });
  strip.addEventListener("keydown", (e) => {
    const tabs = [...strip.querySelectorAll('[role="tab"]')], i = tabs.indexOf(document.activeElement);
    if (i < 0) return;
    const k = { ArrowRight: (i + 1) % tabs.length, ArrowLeft: (i - 1 + tabs.length) % tabs.length, Home: 0, End: tabs.length - 1 }[e.key];
    if (k == null) return;
    e.preventDefault();
    openTab(tabs[k].dataset.tab, { focus: true });
  });
  const h = safe("hash", () => decodeURIComponent(location.hash.slice(1)), "");
  if (h) openTab(h, { hash: false, scroll: false });
  window.addEventListener("hashchange", () => openTab(safe("hash", () => decodeURIComponent(location.hash.slice(1)), ""), { hash: false }));
}

/* ---------- Start ---------- */
async function init() {
  setupTabs();
  document.addEventListener("click", onAction);
  if (!map) mapNote("The map could not load; the figures in the panel are not affected.", "error");
  const [s, n] = await Promise.allSettled([j("data/scenarios/scenarios.json"), j("data/national/summary.json")]);
  S.nat = n.status === "fulfilled" ? obj(n.value) : null;
  const D = s.status === "fulfilled" ? obj(s.value) : null;
  if (!D || !obj(D.scenarios)) { failed(s.status === "rejected" ? s.reason : new Error("no scenarios in the data file")); return; }
  S.data = D;
  S.ctx = safe("context", context, {});
  S.sel = defaultSel();
  [["ta", renderA], ["tb", renderB], ["tr", renderR], ["tc", renderC], ["tp", renderP]].forEach(([id, fn]) => {
    try { fn(); } catch (e) {
      if (window.console) console.error("scenarios: " + id, e);
      $(id).innerHTML = `<p class="note loadfail">This part could not be drawn from the data export (${esc(e.message)}).</p>`;
    }
  });
  safe("select", buildSelect);
  safe("watch", setupWatch);
  safe("readout", renderReadout);
  if (!map) return;
  mapNote("");
  fitOnce([]);   // frame the cement plants at once; the plants load next
  await drawMap();
}

function failed(e) {
  if (window.console) console.error("scenarios: load", e);
  const msg = `Could not load the scenario data${e && e.message ? ` (${e.message})` : ""}. Reload the page to try again.`;
  mapNote(msg, "error");
  ["ta", "tb", "tr", "tc", "tp"].forEach((id) => { const el = $(id); if (el) el.innerHTML = `<p class="note loadfail">${esc(msg)}</p>`; });
  const sel = $("csel");
  if (sel) { sel.innerHTML = "<option>Not available</option>"; sel.disabled = true; }
}

/* Facts the tabs share */
function context() {
  const P = obj(S.data.params) || {};
  const a0 = sc("A0_published"), a1 = sc("A1_floor"), swl = sc("A1_southwest_line");
  const ns = obj(S.nat && S.nat.summary);
  // Is A0 (the published table) the table the national page shows right now? null = cannot tell
  let natMatch = null;
  if (a0 && ns && ok(ns.farmed_ha) && ok(a0.farmed_ha)) {
    const w0 = C(a0.water_m3), wn = C(ns.water_m3);
    natMatch = Math.abs(ns.farmed_ha - a0.farmed_ha) <= 2 && (!ok(w0) || !ok(wn) || Math.abs(wn - w0) <= 1e-3 * w0);
  }
  // Which pumping head the energy figures use: the retrofit records name it
  const reb = fam("B2").flatMap(([, x]) => Object.values(obj(x.by_rebound) || {})).filter(obj);
  const headNew = reb.some((v) => ok(v.headline_elec_kwh) || ok(v.baseline_pressure_head_m));   // lift + drawdown + pivot pressure
  const headOld = !headNew && reb.some((v) => ok(v.elec_baseline_with_pressure_kwh));           // static lift only
  const ph = obj(ns && ns.pumping_head);
  // Is C0 the siting the national page shows right now? true / false, or null when the national siting is absent
  // (a stale siting is not exported: siting is {}), not credited, or on another residue tier
  const c0 = sc("C0_published"), sit = obj(S.nat && S.nat.siting);
  let c0Match = null, c0Nat = null;
  if (c0 && ok(c0.credited_tco2) && ok(c0.plant_size_t) && sit) {
    const e = obj(sit[`central_${Math.round(c0.plant_size_t / 1000)}kt`]);
    if (e && e.credited !== false && (e.residue_tier == null || e.residue_tier === "radar") && ok(e.net_removal_tco2)) {
      c0Nat = e.net_removal_tco2;
      c0Match = Math.abs(c0Nat - c0.credited_tco2) <= 1000;
    }
  }
  // The field tables, as the records name them: "Published table (radar quality check on, southwest in)" and
  // "Radar-verified floor: quality check on, southwest apart" (every C row but C0 runs on the floor table)
  const tPub = (/\(([^()]+)\)\s*$/.exec(String((a0 && a0.name) || "")) || [])[1] || "southwest in";
  const tFloor = (/:\s*(.+)$/.exec(String((a1 && a1.name) || "")) || [])[1] || "southwest apart";
  // The biochar engine that wrote the C rows: the current one records each row's outlet rule ("outlets")
  const newEng = fam("C").some(([k, x]) => k !== "C0_published" && typeof x.outlets === "string");
  const circ = C(get(S.nat, "params.road_circuity"));
  return { P, a0, a1, swl, ns, natMatch, headNew, headOld, ph, c0Match, c0Nat, tPub, tFloor, newEng, circ };
}

/* Wording that depends on whether C0 is the national page's siting (true), differs from it (false) or cannot be
   checked (null: no national siting published) */
const c0Name = () => S.ctx.c0Match === true ? `the <a href="national.html#biochar">national page</a>'s siting` : "the published national siting";
const c0Tag = () => S.ctx.c0Match === true ? "national page" : "reference";
/* C0's own note opens "The national page's siting"; say so only when the national page shows that siting */
const noteOf = (k, x) => { const n = String((x && x.note) || "").trim(); return k === "C0_published" && S.ctx.c0Match !== true ? n.replace(/^the national page's siting/i, "The national model's own siting") : n; };
const c0Tables = () =>`on the published field table (${esc(S.ctx.tPub)}); the other rows use the radar-floor table (${esc(S.ctx.tFloor)}), so part of the gap between them comes from the table, not from the outlets`;

function defaultSel() {
  const recs = fam("C", "C_upside");
  const f3 = recs.find(([k, x]) => k === "C1_F3" && !isUpside(x));
  const first = recs.find(([, x]) => !isUpside(x)) || recs[0];
  return f3 ? f3[0] : (first ? first[0] : null);
}

/* ================================================================ Radar floor */
function renderA() {
  const { P, a0, a1, swl, ns, natMatch, headNew, headOld, ph } = S.ctx, N = S.nat;
  if (!a1) { $("ta").innerHTML = `<p class="note">No radar-floor scenario in this data export.</p>`; return; }
  const mc = obj(a1.monte_carlo) || {}, act = obj(a1.active_ha) || {};
  const sw = arr(get(P, "southwest_admin.values")).map(admin);
  const w = (x) => C(x && x.water_m3);
  const h = [];

  // The national page's headline less the southwest = this floor (shown only where the data add up)
  if (a0 && swl && ok(a0.farmed_ha) && ok(a1.farmed_ha) && ok(swl.farmed_ha) && Math.abs(a0.farmed_ha - a1.farmed_ha - swl.farmed_ha) <= 2
      && ok(w(a0)) && ok(w(a1)) && ok(w(swl)) && Math.abs(w(a0) - w(a1) - w(swl)) <= 1e-3 * w(a0)) {
    const whose = natMatch === true ? `the <a href="national.html">national page</a>'s` : "the published national table's";
    h.push(`<p class="lead">This floor is ${whose} ${fmt(a0.farmed_ha)} ha and ${bn(w(a0))} bn m³ less the southwest regions${sw.length ? ` of ${esc(list(sw))}` : ""} (${fmt(swl.farmed_ha)} ha, ${bn(w(swl))} bn m³), which are reported apart as low confidence.</p>`);
  }
  h.push(`<p class="lead">Where NISAR's data pass the quality check (southwest reported apart), the radar finds <b>${fmt(a1.farmed_ha)} ha</b> farmed in 2025/26: winter ${fmt(act.winter)} ha, summer ${fmt(act.summer)} ha.</p>`);
  if (natMatch === false) h.push(`<p class="callout">The national page currently shows ${fmt(ns.farmed_ha)} ha for the published table: the two pages come from different model runs.</p>`);

  const kpi = (label, key, div, d, unit) => {
    const v = C(a1[key]);
    if (!ok(v)) return "";
    const m = obj(mc[key]), r = obj(a1[key]), lines = [];
    if (m && ok(m.p5) && ok(m.p95)) lines.push(`P5–P95 ${fmt(m.p5 / div, d)}–${fmt(m.p95 / div, d)}`);
    if (r && ok(r.low) && ok(r.high)) lines.push(`all-low / all-high corners ${fmt(r.low / div, d)}–${fmt(r.high / div, d)}`);
    return `<div class="kpi"><div class="kpi-label">${label}</div><div class="kpi-value">${fmt(v / div, d)}<span class="kpi-unit">${unit}</span></div>${lines.length ? `<div class="kpi-range">${lines.join("<br>")}</div>` : ""}</div>`;
  };
  h.push(`<div class="kpis">${kpi("Groundwater pumped", "water_m3", 1e9, 2, "billion m³/yr")}${kpi("Pumping electricity", "elec_kwh", 1e9, 2, "TWh/yr")}${kpi("Average June–September load", "summer_pumping_avg_mw", 1, 0, "MW")}${kpi("Pumping CO₂ (grid)", "co2_t_grid", 1e6, 2, "Mt/yr")}</div>`);

  const eff = C(get(N, "params.pump_wire_to_water_eff"));
  const pump = ok(eff) ? `a best-practice ${fmt(eff, 2)} wire-to-water pump` : "a best-practice wire-to-water pump";
  const half = /half the perennial/i.test(String(get(N, "params.irrigation_mm_summer_crop.source") || ""));
  // The head the energy figures use: the current model adds drawdown and pivot pressure to the static depth, so the
  // old "static lift, no sprinkler pressure" wording applies only to exports that still carry the static-lift records
  const palm = (ph && obj(ph.palm_grove_pivots)) || /palm grove/i.test(String((ph && ph.pivot_rule) || "")) ? " (pivot-shaped palm groves get none)" : "";
  const energy = headNew ? `Energy is modelled, not metered, and likely a lower bound (see below). It uses head = static depth to water + drawdown + the pivot pressure head on centre pivots${palm}, and ${pump}`
    : headOld ? `Energy is a lower-bound model (static lift, ${pump}, no sprinkler pressure)`
    : natMatch === true && ph && typeof ph.rule === "string" ? `Energy is modelled, not metered, and likely a lower bound (see below). It uses ${esc(ph.rule)}, and ${pump}`
    : `Energy is modelled, not metered, and likely a lower bound (see below). It uses the national model's pumping head (<a href="national.html#method">national page, Method tab</a>) and ${pump}`;
  h.push(`<p class="note">Central estimates. P5–P95: Monte Carlo over every factor's low–high range (depths move together, lift moves together across regions). The corners set every factor to its low or high bound at once, so they fall outside P5–P95. Water is estimated from crop water needs, not metered: published irrigation depths for winter and year-round fields and a derived depth${half ? " (half the perennial one)" : ""} for summer crops. ${energy}, so its band is a parameter range, not a full uncertainty.</p>`);

  // The radar threshold is a separate uncertainty (national page, southwest in)
  const cr = obj(ns && ns.classification_range), lo = obj(cr && cr.plus_1db), hi = obj(cr && cr.minus_1db);
  if (lo && hi && ok(lo.farmed_ha) && ok(hi.farmed_ha)) {
    const sh = Math.abs(Number(get(cr, "shift_db.plus_1db"))) || 1;
    const wl = C(lo.water_m3), wh = C(hi.water_m3);
    const run = natMatch === false ? " This range comes from the national page's current run, not the run behind the figures above." : "";
    h.push(`<p class="note">These ranges cover the accounting factors, not the radar classification. Moving every region's radar threshold by ±${fmt(sh, sh % 1 ? 1 : 0)} dB gives ${fmt(Math.min(lo.farmed_ha, hi.farmed_ha))}–${fmt(Math.max(lo.farmed_ha, hi.farmed_ha))} ha farmed${ok(wl) && ok(wh) ? ` and ${bn(Math.min(wl, wh))}–${bn(Math.max(wl, wh))} bn m³ of water` : ""} on the national table (southwest in; <a href="national.html">national page</a>).${run}</p>`);
  }

  if (swl) {
    const field = swl.field_ha, unusable = get(swl, "area_ha_by_class.radar_unusable");
    h.push(`<p class="note">Southwest regions alone (low confidence): ${fmt(swl.farmed_ha)} ha farmed and ${bn(w(swl))} bn m³ where the radar passed the quality check; the radar could not classify ${fmt(unusable)} ha (${pct(ok(field) && field > 0 && ok(unusable) ? unusable / field : null)}) of southwest field area.</p>`);
  }

  // What the floor leaves out (each would raise it) ...
  const cls = obj(a1.area_ha_by_class) || {}, su = obj(a1.season_unknown_ha) || {};
  const cov = obj(ns && ns.coverage), np = obj(cov && cov.not_processed), cf = C(P.coverage_factor);
  const out = [`Seasons the radar did not observe: winter unknown on ${fmt(su.winter)} ha, summer on ${fmt(su.summer)} ha (fields with neither season classified: ${fmt(cls.radar_unusable)} ha).`,
    `Fields Sentinel-2 saw green that the radar did not detect (${fmt(cls.idle)} ha).`];
  // audit sc-7: the share is of the cropland and tree cover inside the boxes; farmland in no box is not in it
  const minCl = (/clusters of at least ([\d,.]+) ha/i.exec(String((cov && cov.rule) || "")) || [])[1];
  const unboxed = `farmland outside every box, which no share here counts: ${minCl ? `farming clusters under ${esc(minCl)} ha` : "small farming clusters"} are not boxed`;
  if (np && ok(np.boxes) && ok(np.share)) out.push(`The ${fmt(np.boxes)} smaller region boxes not processed (~${pct(np.share)} of the WorldCover cropland and tree cover in all ${fmt(cov.boxes)} boxes), and ${unboxed}.`);
  else if (ok(cf)) out.push(`The smaller region boxes not processed (~${pct(1 - cf)} of the WorldCover cropland and tree cover in the region boxes), and ${unboxed}.`);
  out.push("Pumping energy for the Arabian Shield regions.");
  if (headOld) out.push("Sprinkler pressure head.");
  if (!headOld && (get(N, "lift_notes._age") || get(ph, "notes._age"))) out.push(`Deeper water tables since the depths were measured, which would raise pumping energy (<a href="national.html#method">national page, Method tab</a>).`);
  h.push(`<h3>What the floor leaves out</h3><ul class="items">${out.map((t) => `<li>${t}</li>`).join("")}</ul>`);

  // ... and what pushes it the other way (audit sc-6)
  const v = obj(a1.validation) || {}, vw = obj(v.winter), vs = obj(v.summer);
  const both = sc("A4_both"), rad = sc("A4_radar"), down = [];
  if (vs && ok(vs.precision)) down.push(`Radar detections Sentinel-2 does not confirm: precision ${vw && ok(vw.precision) ? `${pct(vw.precision)} in winter and ` : ""}${pct(vs.precision)} in summer on this table, so about ${pct(1 - vs.precision)} of the radar's checked summer area is not green in Sentinel-2. In winter, Sentinel-2 cannot confirm crops that have not greened up by the radar's dates, so some unconfirmed winter detections are real.`);
  if (both && rad && ok(both.farmed_ha) && ok(rad.farmed_ha) && rad.farmed_ha > 0 && ok(w(both)) && ok(w(rad)) && w(rad) > 0 && both.farmed_ha < rad.farmed_ha) {
    down.push(`Requiring radar and Sentinel-2 to agree lowers the farmed area by about ${pct(1 - both.farmed_ha / rad.farmed_ha)} and water by about ${pct(1 - w(both) / w(rad))} (quality check on, southwest in: the first two rows of the bracket below).`);
  }
  if (down.length) h.push(`<h3>What could lower it</h3><ul class="items">${down.map((t) => `<li>${t}</li>`).join("")}</ul>`);

  // Agreement with Sentinel-2, as a table
  const vt = [["This table: quality check on, southwest apart", a1.validation], ["Quality check off, southwest also out", get(sc("A2_qc0_swout_wradar"), "validation")],
    ["Quality check off, southwest in", get(sc("A2_qc0_swin_wradar"), "validation")]]
    .map(([label, vv]) => [label, ["summer", "winter"].map((se) => [se, obj(obj(vv) && vv[se])]).filter(([, x]) => x)]).filter(([, rows]) => rows.length);
  if (vt.length) {
    h.push(`<h3>Agreement with Sentinel-2</h3><table><tr><th>Table and season</th><th class="num">Kappa</th><th class="num">Precision</th><th class="num">Recall</th><th class="num">Checked kha</th></tr>${vt.map(([label, rows]) => `<tr class="grp"><td colspan="5">${label}</td></tr>` + rows.map(([se, x]) => `<tr><td class="tier">${cap(se)}</td><td class="num">${fmt(x.kappa, 2)}</td><td class="num">${pct(x.precision)}</td><td class="num">${pct(x.recall)}</td><td class="num">${ok(x.validated_ha) ? fmt(x.validated_ha / 1e3) : "–"}</td></tr>`).join("")).join("")}</table>
      <p class="note">Area-weighted over fields where both are known. Precision: share of the area the radar calls farmed that Sentinel-2 sees green; recall: share of the green area the radar calls farmed.</p>`);
  }

  // Floor to ceiling against official figures
  const br = ["A4_both", "A4_radar", "A4_s2fill", "A4_either"].map(sc).filter(Boolean);
  const same = (x, y) => y && ok(x.farmed_ha) && x.farmed_ha === y.farmed_ha && ok(w(x)) && ok(w(y)) && Math.abs(w(x) - w(y)) <= 1;
  const tagPub = (x) => same(x, a0) ? ` <span class="tag">${natMatch === true ? "national page" : "published table"}</span>` : same(x, a1) ? ' <span class="tag">this floor</span>' : "";
  if (br.length) {
    const vo = obj(ns && ns.vs_official), byr = arr(get(sc("A4_radar") || br[0], "by_region")).filter(obj);
    const sumR = (k) => byr.length && byr.some((r) => ok(r[k])) ? byr.reduce((a, r) => a + (ok(r[k]) ? r[k] : 0), 0) : null;
    const off = (k) => vo && ok(vo[k]) ? vo[k] : sumR(k);
    const oW = off("mewa_agri_groundwater_m3"), oWh = off("gastat_wheat_ha"), oF = off("gastat_fodder_ha");
    const area = (x, ...ks) => { const c = obj(x.area_ha_by_class) || {}; return ks.reduce((a, k) => a + (ok(c[k]) ? c[k] : 0), 0); };
    const nm = (x) => String(x.name || x.id).replace(/\s*\(QC on, southwest in\)\s*$/i, "");
    const n60 = get(ns, "regions_done") || get(cov, "processed.boxes");
    h.push(`<h3>Floor to ceiling against official figures (quality check on, southwest in)</h3>
      <table><tr><th>Season rule</th><th class="num">Farmed ha</th><th class="num">Water bn m³</th><th class="num">Wheat ha</th><th class="num">Year-round ha<span class="sub">official: fodder</span></th></tr>
      ${br.map((x) => `<tr><td class="rule">${esc(nm(x))}${tagPub(x)}</td><td class="num">${fmt(x.farmed_ha)}</td><td class="num">${bn(w(x))}</td><td class="num">${fmt(area(x, "winter_only", "wheat_rotation"))}</td><td class="num">${fmt(area(x, "year_round"))}</td></tr>`).join("")}
      ${ok(oW) || ok(oWh) || ok(oF) ? `<tr><td class="rule">Official: MEWA 2024 farm groundwater; GASTAT 2024 wheat and fodder</td><td></td><td class="num">${bn(oW)}</td><td class="num">${fmt(oWh)}</td><td class="num">${fmt(oF)}</td></tr>` : ""}</table>
      <p class="note">"Either" is a ceiling: fields were outlined from green Sentinel-2 pixels. The Sentinel-2-based rows count southwest greenness, largely rain-fed or spate farming, as irrigated. Official figures cover all farms; radar covers the mapped fields of the ${ok(n60) ? fmt(n60) + " " : ""}largest regions.</p>`);
  }

  // Data-rule robustness
  const grid = fam("A2");
  if (grid.length) {
    // The Sentinel-2 runs either fill unobserved winters only (older exports) or use the radar + Sentinel-2 tier, which
    // also fills partly-seen fields and classifies fields with no usable radar season: say which the records hold
    const tierRuns = grid.filter(([, x]) => /Sentinel-2 tier/i.test(String(x.name || "")) || x.s2_tier || (typeof x.note === "string" && /tier/i.test(x.note)));
    const how = tierRuns.length
      ? `and uses the radar's seasons only or the radar + Sentinel-2 tier (what that tier adds: Fodder halt tab, "How the radar + Sentinel-2 record is built")`
      : "and leaves unobserved winters unknown (radar only) or fills them from Sentinel-2";
    h.push(`<h3>Data-rule robustness (${plural(grid.length, "run", "runs")})</h3>
      <p class="note">Each run sets the radar quality check on or off, keeps or drops the southwest, ${how}.</p>
      <table><tr><th>Run</th><th class="num">Water bn m³</th><th class="num">TWh</th><th class="num">Farmed ha</th><th class="num">Summer kappa</th></tr>
      ${grid.map(([, x]) => `<tr><td class="rule">${esc(x.name || x.id)}${tagPub(x)}</td><td class="num">${bn(w(x))}</td><td class="num">${bn(C(x.elec_kwh))}</td><td class="num">${fmt(x.farmed_ha)}</td><td class="num">${ok(get(x, "validation.summer.kappa")) ? fmt(x.validation.summer.kappa, 2) : "–"}</td></tr>`).join("")}</table>
      <p class="note">Agreement is computed only for seasons the radar classified; seasons filled from Sentinel-2 are not validated against Sentinel-2.</p>
      ${tierPanel(tierRuns)}`);
  }
  $("ta").innerHTML = h.join("");
}

/* The tier runs' notes differ only in their first bracket (which table the tier rule runs on): print the shared text
   once, then each group of runs with its bracket. Notes that differ in more than that are printed whole. */
function tierPanel(runs) {
  const recs = runs.map(([, x]) => {
    const n = plain(x.note), m = /\s*\(([^()]+)\)/.exec(n);
    return { x, n, rest: m ? (n.slice(0, m.index) + n.slice(m.index + m[0].length)).trim() : n, par: m ? m[1].trim() : "" };
  }).filter((r) => r.n);
  if (!recs.length) return "";
  const wrap = (body) => `<details class="more"><summary>What the radar + Sentinel-2 runs fill</summary>${body}</details>`;
  const rests = [...new Set(recs.map((r) => r.rest))], pars = [...new Set(recs.map((r) => r.par))];
  if (rests.length > 1 || pars.length < 2 || pars.includes("")) return wrap([...new Set(recs.map((r) => r.n))].map((n) => `<p>${esc(sentence(n))}</p>`).join(""));
  // name each group by what its run names share that the other tier runs do not ("QC on", "QC off")
  const bits = (x) => String(x.name || x.id).split(/,\s*/).map((s) => s.trim()).filter(Boolean);
  const common = (xs) => xs.map(bits).reduce((a, b) => a.filter((s) => b.includes(s)));
  const everyRun = common(recs.map((r) => r.x));
  const groups = pars.map((p) => {
    const xs = recs.filter((r) => r.par === p).map((r) => r.x), own = common(xs).filter((s) => !everyRun.includes(s));
    return `<li><b>${esc(own.length ? `${own.join(", ")} runs` : list(xs.map((x) => String(x.name || x.id))))}:</b> ${esc(sentence(p))}</li>`;
  });
  return wrap(`<p>${esc(sentence(rests[0]))}</p><ul class="items">${groups.join("")}</ul>`);
}

/* ================================================================ Fodder halt */
function renderB() {
  const P = S.ctx.P || {}, el = $("tb");
  const radar = fam("B"), s2all = fam("B_s2");
  const s0 = sc("B1_seasonal_100") || ((radar[0] || [])[1]) || null;
  if (!s0) { el.innerHTML = `<p class="note">No fodder-halt scenarios in this data export.</p>`; return; }
  const pairOf = (x) => { const hit = s2all.find(([, v]) => v.radar_tier_id === x.id) || s2all.find(([k]) => k === x.id + "_s2fill"); return hit ? hit[1] : null; };
  const t0 = pairOf(s0);
  const byName = (o) => { const m = {}; Object.entries(obj(o) || {}).forEach(([k, v]) => { if (ok(v)) m[admin(k)] = (m[admin(k)] || 0) + v; }); return m; };
  const rad = byName(s0.scope_by_region_ha), rs2 = t0 ? byName(t0.scope_by_region_ha) : null;
  const names = [...new Set([...arr(get(P, "mewa_fodder_halt_regions.values")).map(admin), ...Object.keys(rad)])];

  const eff = isoDate(get(S.nat, "fodder_halt.effective")) || isoDate(HALT_DATE);
  const dTxt = eff ? eff.toLocaleDateString("en-GB", { timeZone: "UTC", day: "numeric", month: "long", year: "numeric" }) : "";
  const started = eff && Date.now() >= eff.getTime();
  const verb = !dTxt ? "is stopping perennial fodder" : started ? `has stopped perennial fodder since <b>${dTxt}</b>` : `stops perennial fodder from <b>${dTxt}</b>`;
  const h = [];
  // how the Sentinel-2 fields got their seasons: one season filled, or classified from Sentinel-2 alone
  const byF = obj(t0 && t0.scope_s2_filled_ha_by_fill), fillParts = byF ? [ok(byF.season_fill) && byF.season_fill > 0 ? `${fmt(byF.season_fill)} ha with one season filled` : "",
    ok(byF.s2_only) && byF.s2_only > 0 ? `${fmt(byF.s2_only)} ha classified from Sentinel-2 alone` : ""].filter(Boolean) : [];
  h.push(`<p class="lead">MEWA ${verb}${names.length ? ` in ${esc(list(names.map(inSentence)))}` : ""}. The 2025/26 radar record is a field-level baseline from the season before: <b>${fmt(s0.scope_fields)} year-round fields, ${fmt(s0.scope_ha)} ha</b>.${t0 ? ` With Sentinel-2 filling what the radar did not observe, the radar + Sentinel-2 record holds <b>${fmt(t0.scope_fields)} fields, ${fmt(t0.scope_ha)} ha</b>, an upper value: the area it adds is measured by Sentinel-2, not by the radar${ok(t0.scope_s2_filled_ha) ? ` (${fmt(t0.scope_s2_filled_ha)} ha${ok(t0.scope_s2_filled_fields) ? ` on ${fmt(t0.scope_s2_filled_fields)} fields` : ""} with a season from Sentinel-2${fillParts.length ? `: ${list(fillParts)}` : ""})` : ""}.` : ""}</p>`);

  // By region, against GASTAT's fodder area (audit sc-2)
  const hr = arr(s0.halt_regions).filter(obj), gas = {};
  hr.forEach((r) => { if (ok(r.gastat_fodder_ha)) gas[admin(r.admin)] = r.gastat_fodder_ha; });
  if (!Object.keys(gas).length) arr(get(S.nat, "official")).forEach((r) => { if (obj(r) && ok(r.gastat_fodder_ha) && names.includes(admin(r.region))) gas[admin(r.region)] = r.gastat_fodder_ha; });
  const hasG = names.length > 0 && names.every((n) => ok(gas[n]));
  // totals: the records' own scope figures where present (the lead quotes them), else the column sums
  const tot = (m) => m === rad && ok(s0.scope_ha) ? s0.scope_ha : m === rs2 && t0 && ok(t0.scope_ha) ? t0.scope_ha : names.reduce((a, n) => a + (ok(m[n]) ? m[n] : 0), 0);
  const order = names.slice().sort((a, b) => (rad[b] || 0) - (rad[a] || 0));
  h.push(`<table><tr><th>Region</th><th class="num">Year-round ha, radar</th>${rs2 ? `<th class="num">Radar + Sentinel-2</th>` : ""}${hasG ? `<th class="num">GASTAT 2024 fodder ha</th>` : ""}</tr>
    ${order.map((n) => `<tr><td>${esc(n)}</td><td class="num">${fmt(rad[n] || 0)}</td>${rs2 ? `<td class="num">${fmt(rs2[n] || 0)}</td>` : ""}${hasG ? `<td class="num">${fmt(gas[n])}</td>` : ""}</tr>`).join("")}
    ${names.length > 1 ? `<tr class="total"><td>All ${fmt(names.length)} regions</td><td class="num">${fmt(tot(rad))}</td>${rs2 ? `<td class="num">${fmt(tot(rs2))}</td>` : ""}${hasG ? `<td class="num">${fmt(tot(gas))}</td>` : ""}</tr>` : ""}</table>`);
  const notes = [];
  if (hasG && tot(gas) > 0) notes.push(`The radar's year-round area is ${pct(tot(rad) / tot(gas))} of GASTAT's 2024 fodder area in these regions${rs2 ? ` (${pct(tot(rs2) / tot(gas))} with Sentinel-2)` : ""}: a lower bound on the share of perennial fodder it finds, since GASTAT's figure also counts licensed seasonal fodder.`);
  const sumK = (k) => hr.reduce((a, r) => a + (ok(r[k]) ? r[k] : 0), 0);
  const top = (k) => hr.filter((r) => ok(r[k]) && r[k] > 0).sort((a, b) => b[k] - a[k]);
  const lst = (rs, k) => rs.length === 1 ? `all in ${admin(rs[0].admin)}` : list(rs.slice(0, 3).map((r) => `${admin(r.admin)} ${fmt(r[k])} ha`)) + (rs.length > 3 ? ", among others" : "");
  const swu = top("summer_active_winter_unknown_ha"), ru = top("radar_unusable_ha");
  if (swu.length || ru.length) {
    const bits = [];
    if (swu.length) bits.push(`${fmt(sumK("summer_active_winter_unknown_ha"))} ha of fields active in summer whose winter it did not observe (${esc(lst(swu, "summer_active_winter_unknown_ha"))})`);
    if (ru.length) bits.push(`${fmt(sumK("radar_unusable_ha"))} ha with no usable radar season (${esc(lst(ru, "radar_unusable_ha"))})`);
    notes.push(`More year-round fields may hide where the radar did not see both seasons: ${bits.join(", and ")}.${t0 ? " The radar + Sentinel-2 record classifies part of them." : ""}`);
  }
  if (notes.length) h.push(notes.map((t) => `<p class="note">${t}</p>`).join(""));

  // What the switch saves
  const saved = (x, k) => {
    const sv = obj(x.saved);
    if (sv && ok(sv[k])) return sv[k];
    if (k === "summer_mw") return ok(x.baseline_summer_mw) && ok(C(x.summer_pumping_avg_mw)) ? x.baseline_summer_mw - C(x.summer_pumping_avg_mw) : null;
    const b = obj(x.baseline);
    return b && ok(b[k]) && ok(C(x[k])) ? b[k] - C(x[k]) : null;
  };
  const what = (x) => cap(String(x.name || x.id).replace(/^Fodder halt[^:]*:\s*/i, "").replace(/^year-round fields\s+/i, ""));
  const cells = (x) => `<td class="num">${bn(saved(x, "water_m3"))}</td><td class="num">${bn(saved(x, "elec_kwh"))}</td><td class="num">${fmt(saved(x, "summer_mw"))}</td><td class="num">${mt(saved(x, "co2_t_grid"))}</td>`;
  const anyS2 = radar.some(([, x]) => pairOf(x));
  h.push(`<h3>If those fields switch (central estimate)</h3>
    <table><tr><th>${anyS2 ? "What-if and record" : "What-if"}</th><th class="num">Water saved bn m³/yr</th><th class="num">Electricity saved TWh/yr</th><th class="num">Jun–Sep load cut MW</th><th class="num">CO₂ avoided Mt/yr</th></tr>
    ${radar.map(([, x]) => { const y = pairOf(x); return anyS2 ? `<tr class="grp"><td colspan="5">${esc(what(x))}</td></tr><tr><td class="tier">Radar</td>${cells(x)}</tr>${y ? `<tr><td class="tier">Radar + Sentinel-2</td>${cells(y)}</tr>` : ""}` : `<tr><td>${esc(what(x))}</td>${cells(x)}</tr>`; }).join("")}</table>
    ${anyS2 ? `<p class="note">Savings on the radar record are a floor for the radar-mapped fields; the radar + Sentinel-2 rows are the upper value. Each record is measured against its own baseline.</p>` : ""}`);

  const pw = obj(P.press_water_per_ha) || obj(P.mewa_water_per_ha) || {};
  const per = s0.scope_baseline_water_per_ha_m3, gap = ok(per) && ok(pw.perennial_m3) && pw.perennial_m3 > 0 ? 1 - per / pw.perennial_m3 : null;
  const wheat = sc("B1_wheat_100");
  const strawW = !wheat ? null : ok(wheat.straw_t_dry_change) ? wheat.straw_t_dry_change
    : (ok(C(wheat.straw_t_dry)) && ok(get(wheat, "baseline.straw_t_dry")) ? C(wheat.straw_t_dry) - wheat.baseline.straw_t_dry : null);
  const t = [];
  if (ok(per)) t.push(`The model gives every year-round field the same perennial depth: about ${fmt(per)} m³/ha a year pumped${ok(pw.perennial_m3) ? `, ${gap != null ? `about ${pct(Math.abs(gap))} ${gap >= 0 ? "below" : "above"}` : "against"} the ~${fmt(pw.perennial_m3)} m³/ha reported in the press for perennial fodder${ok(pw.seasonal_max_m3) ? ` (seasonal fodder at most ~${fmt(pw.seasonal_max_m3)})` : ""}. These are press figures, a cross-check only (sources in the Assumptions tab)` : ""}.`);
  t.push(`Seasonal winter fodder is cut green, so it adds no straw; the wheat variant does${ok(strawW) && strawW > 0 ? ` (${kt(strawW)} kt a year)` : ""}.`);
  t.push("The scope is a baseline, not an exact count: where a region had no usable winter pass (notably the Eastern Province), year-round fields cannot be told from summer crops; and some year-round fields may be other two-season crops rather than perennial fodder.");
  t.push(`From summer ${eff ? eff.getUTCFullYear() + 1 : 2027}, NISAR's 12-day passes can show which of these fields stopped irrigating in summer: toggle the watch-list on the map. A field is not a farm or a licence; the list is for screening, not enforcement.`);
  h.push(`<p class="note">${t.join(" ")}</p>`);

  const wl = (t0 && t0.watchlist) ? t0 : (s0.watchlist ? s0 : null);
  h.push(`<p><button type="button" data-act="watch" aria-pressed="false">Show the watch-list on the map</button></p>`);
  if (wl) {
    // exports with fill codes tell apart one filled season, Sentinel-2 alone, and fields the radar never observed
    const shapes = wl !== t0 ? "" : byF && ok(byF.s2_only)
      ? ". On the map a solid dot has both seasons from the radar; a ring has one season filled from Sentinel-2; a diamond was classified from Sentinel-2 alone where the radar covered the field but classified no season; a square was classified from Sentinel-2 alone outside every radar swath, so the radar never observed it. A season from Sentinel-2 has no radar margin, and fields from Sentinel-2 alone have none at all"
      : "; a field with a season from Sentinel-2 is drawn as a ring and has no radar margin for that season";
    h.push(`<p class="note">The watch-list holds the ${fmt(wl.scope_fields)} fields of the ${wl === t0 ? "radar + Sentinel-2" : "radar"} scope${shapes}.</p>`);
  }
  const tNote = t0 ? plain(t0.note) : "", tierSrc = plain(get(P, "s2_tier.source"));
  if (t0 && (tNote || tierSrc)) h.push(`<details class="more"><summary>How the radar + Sentinel-2 record is built</summary>${tNote ? `<p>${esc(sentence(tNote))}</p>` : ""}${tierSrc ? `<p>${esc(sentence(tierSrc))}</p>` : ""}</details>`);
  el.innerHTML = h.join("");
  syncWatch();
}

/* ================================================================ Pivot retrofits */
function renderR() {
  const el = $("tr"), rows = fam("B2"), P = S.ctx.P || {};
  if (!rows.length) { el.innerHTML = `<p class="note">No retrofit scenarios in this data export.</p>`; return; }
  const reb = (x) => Object.entries(obj(x.by_rebound) || {}).filter(([, v]) => obj(v)).sort((a, b) => Number(a[0]) - Number(b[0]));
  const first = ((reb(rows[0][1])[0]) || [])[1] || {};
  const low = get(P, "pivot_retrofit.low_pressure_head_m");
  const h = [`<p class="lead">Subsidised low-pressure pivots save pumped water only if the freed water is not used to irrigate more land; the lower pressure still cuts some energy either way. ${fmt(first.pivot_fields)} sprinkler pivots (${fmt(first.pivot_ha)} ha) on the radar-floor table.</p>`];
  h.push(`<table><tr><th>Retrofit and freed water re-used</th><th class="num">Pumped water saved bn m³/yr</th><th class="num">Electricity saved TWh/yr</th><th class="num">Jun–Sep load cut MW</th><th class="num">CO₂ avoided Mt/yr</th></tr>
    ${rows.map(([, x]) => `<tr class="grp"><td colspan="5">${esc(x.name || x.id)}</td></tr>` + reb(x).map(([k, v]) => `<tr><td class="tier">${pct(Number(k))} re-used</td><td class="num">${bn(v.pumped_water_saved_m3)}</td><td class="num">${bn(v.elec_saved_kwh)}</td><td class="num">${fmt(v.summer_mw_saved)}</td><td class="num">${mt(v.co2_saved_t)}</td></tr>`).join("")).join("")}</table>`);
  const head = S.ctx.headNew ? ` The baseline is the headline's own pumping on these pivots (depth to water + drawdown + ${ok(first.baseline_pressure_head_m) ? `a ${fmt(first.baseline_pressure_head_m, 1)} m` : "the"} pivot pressure head); the retrofit lowers only the pressure part${ok(low) ? `, to ${fmt(low, 1)} m` : ""}, so nothing is counted twice.`
    : S.ctx.headOld ? " Energy here includes the sprinkler pressure head that the headline omits."
    : S.ctx.natMatch === true && S.ctx.ph && typeof S.ctx.ph.rule === "string" ? ` The baseline pumps against the national model's head (${esc(S.ctx.ph.rule)}); the retrofit lowers only the pressure part${ok(low) ? `, to ${fmt(low, 1)} m` : ""}.`
    : ` The baseline pumps against the national model's head (<a href="national.html#method">national page, Method tab</a>); the retrofit lowers only the pressure part${ok(low) ? `, to ${fmt(low, 1)} m` : ""}.`;
  h.push(`<p class="note">Central estimate. Efficiencies and pressures are US values (Amosson et al. 2011); no Saudi figures were found.${head} This is pumped water, not depletion: crop water needs do not change, and how much of today's losses returns to the aquifer is unknown. The "0%" row holds only if allocations are cut to post-retrofit need, or irrigated area and seasons are frozen at the radar baseline (which the radar can check); a volume cap at today's use would leave the freed water free to be re-used.</p>`);
  el.innerHTML = h.join("");
}

/* ================================================================ Biochar */
function renderC() {
  const el = $("tc"), P = S.ctx.P || {}, N = S.nat, newEng = !!S.ctx.newEng;
  const all = fam("C", "C_upside"), credited = all.filter(([, x]) => !isUpside(x)), upsides = all.filter(([, x]) => isUpside(x));
  if (!all.length) { el.innerHTML = `<p class="note">No biochar scenarios in this data export.</p>`; return; }
  const f1 = sc("C1_F1"), f3 = sc("C1_F3"), un = sc("C1_F3_soil_unlimited"), c0 = sc("C0_published");
  const vm = sc("C3_F3_vm0044_cement"), ac = sc("C1_F3_all_feeds_to_cement");
  const cred = (x) => x && !isUpside(x) && ok(x.credited_tco2);
  const up3 = upsides.map(([, x]) => x).find((x) => x.upside_of === "C1_F3");
  const modelled = f3 ? feedsOf(f3).filter((f) => !RADAR_FEEDS.includes(f)) : [];
  const modTxt = list(modelled.map((f) => FEED[f] || f));
  const cf = f3 ? arr(f3.cement_feeds) : [];
  const allEligible = !!(f3 && cf.length && feedsOf(f3).every((f) => cf.includes(f)));
  // The current engine routes by haul when every char in a run may go to cement (the Puro default): cement only where
  // it earns more than farmland after haul, then farmland, then the remainder to cement plants with allowance left
  const byHaul = newEng && allEligible;
  const litterOut = S.data.litter_credited === false || (!!up3 && !modelled.includes("litter"));
  // organic carbon of the high-ash chars (national params), for the cement caveats (audit sc-5)
  const corgTxt = (fs) => { const v = [...new Set(fs.map((f) => C(get(N, `params.${f}_char_c_org`))).filter(ok).sort((a, b) => a - b).map((x) => pct(x)))]; return v.length ? `organic carbon about ${v.join("–")}` : ""; };
  const h = [];

  h.push(`<p class="lead">How much durable removal stands on residues the radar measured, and what ${modelled.length > 1 ? "do" : "does"} modelled ${esc(modTxt || "feed")} add once outlets are realistic?${litterOut && up3 ? " Poultry litter is not credited: its char fails Puro's H/C eligibility gate, so what it would add is shown apart as a hypothetical upper bound." : ""}</p>`);
  if (cred(un) && cred(f3) && un.credited_tco2 > 2 * f3.credited_tco2 && modTxt) h.push(`<p class="lead"><b>What decides the number is where ${esc(modTxt)} char can go:</b> farmland near the plants takes only limited char.</p>`);

  // Separate cases, never one range
  const sizeRange = (ids, allowUp) => {
    const xs = ids.map(sc).filter((x) => x && ok(x.credited_tco2) && ok(x.plant_size_t) && (allowUp || !isUpside(x)));
    if (xs.length < 2) return "";
    const vals = xs.map((x) => x.credited_tco2), lo = Math.min(...vals), hi = Math.max(...vals);
    const sizes = list(xs.map((x) => fmt(x.plant_size_t / 1000)));
    return mt(lo) === mt(hi) ? `about ${mt(lo)} Mt at ${sizes} kt plants` : `${mt(lo)}–${mt(hi)} Mt across ${sizes} kt plants`;
  };
  const caseLi = (label, value, meta, cls) => `<li class="case${cls ? " " + cls : ""}"><div class="case-head"><span class="case-label">${label}</span><span class="case-value">${value}</span></div>${meta.filter(Boolean).map((m) => `<div class="case-meta">${m}</div>`).join("")}</li>`;
  const capCount = (x) => { const cu = arr(x && x.cement_use).filter(obj); return { n: cu.filter((c) => c.at_cap).length, of: cu.length }; };
  const atCap = (x) => { const a = capCount(x); return a.of ? `${fmt(a.n)} of the ${fmt(a.of)} cement plants taking char are at their cap` : ""; };
  const cases = [], upCases = [];
  if (cred(f1)) cases.push(caseLi("Radar-measured wheat straw and palm fronds alone", mt(f1.credited_tco2), [plantsTxt(f1), sizeRange(["C1_F1", "C1_F1_25kt", "C1_F1_10kt"])]));
  if (cred(f3)) {
    const lit0 = modelled.includes("litter") && used(f3, "litter") === 0;
    cases.push(caseLi(`${modTxt ? `Adding modelled ${esc(modTxt)}` : "Adding modelled feed"}, outlets limited: farmland and cement take only limited char`, mt(f3.credited_tco2),
      [plantsTxt(f3), sizeRange(["C1_F3", "C1_F3_25kt", "C1_F3_10kt"]),
       lit0 ? (newEng ? "Poultry litter is in the supply but never drawn (0 t), so the litter gate does not bind here."
         : "Poultry litter is in the supply but never drawn (0 t): plants fill with straw, fronds and manure first, so the litter gate does not bind here.") : ""]));
  }
  if (cred(c0)) {
    const { c0Match, c0Nat } = S.ctx, none = !!(S.nat && !Object.keys(obj(S.nat.siting) || {}).length);
    cases.push(caseLi(`Outlets unconstrained: ${c0Name()}`, mt(c0.credited_tco2),
      [[plantsTxt(c0), ok(c0.plant_size_t) ? `${fmt(c0.plant_size_t / 1000)} kt plants` : "", "no limit on soil absorption or cement uptake"].filter(Boolean).join(" · "),
       `${cap(c0Tables())}.`,
       c0Match === false && ok(c0Nat) ? `The national page currently shows ${mt(c0Nat)} Mt: the two pages come from different model runs.` : "",
       c0Match === null && none ? "The national page publishes no siting to compare it with at the moment." : ""]));
  }
  if (cred(un)) cases.push(caseLi("Outlets limited, but soil absorption unlimited", mt(un.credited_tco2), [plantsTxt(un)]));
  if (cred(vm)) cases.push(caseLi(`<span class="tag">Verra sensitivity</span>VM0044 cement rule: only ${esc(list(arr(vm.cement_feeds).map((f) => FEEDC[f] || f)) || "low-ash")} chars in cement`, mt(vm.credited_tco2), [plantsTxt(vm)]));
  if (cred(ac)) {   // older exports only: the Puro default now lets these chars into cement in every row
    const a = capCount(ac), hiAsh = arr(ac.cement_feeds).filter((f) => f === "manure" || f === "litter"), cg = corgTxt(hiAsh.length ? hiAsh : ["manure", "litter"]);
    cases.push(caseLi(`Manure and litter chars also allowed in cement`, mt(ac.credited_tco2),
      [plantsTxt(ac), [atCap(ac), `it needs high-ash chars${cg ? ` (${cg})` : ""} that Verra's VM0044 keeps out of non-soil uses, at a dose that is a technical ceiling, not likely uptake`,
        a.of && a.n > a.of / 2 ? "with most plants at cap, the figure scales with the dose" : ""].filter(Boolean).join("; ")]));
  }
  if (up3 && ok(up3.credited_tco2)) {   // never among the credited cases (decision: a hypothetical upper bound only)
    const add = cred(f3) ? up3.credited_tco2 - f3.credited_tco2 : null;
    const unUp = upsides.map(([, x]) => x).find((x) => x.upside_of === "C1_F3_soil_unlimited");
    upCases.push(caseLi("Adding poultry litter, if its char passed the gate", `<span class="hyp">(${mt(up3.credited_tco2)})</span><span class="hyp-l">hypothetical</span>`,
      [[ok(add) ? `a hypothetical upper bound: ${smt(add)} Mt on the outlets-limited row` : "a hypothetical upper bound", plantsTxt(up3)].filter(Boolean).join(" · "),
       sizeRange(upsides.map(([k]) => k).filter((k) => /^C3_E1_litter_upside(_\d+kt)?$/.test(k)), true),
       unUp && ok(unUp.credited_tco2) ? `with soil absorption unlimited: ${mt(unUp.credited_tco2)} Mt, also hypothetical` : ""], "upside"));
  }
  const sizeKt = f3 && ok(f3.plant_size_t) ? fmt(f3.plant_size_t / 1000) : null;
  if (cases.length || upCases.length) {
    h.push(`<p class="note">Mt CO₂ a year, net of transport${sizeKt ? `, ${sizeKt} kt/yr plants unless named` : ""}: a technical potential. Separate cases, not a range.</p>${cases.length ? `<ul class="cases">${cases.join("")}</ul>` : ""}${upCases.length ? `<p class="cases-sub">Not credited: a hypothetical upper bound, kept out of the cases above</p><ul class="cases cases-up">${upCases.join("")}</ul>` : ""}`);
  }

  // Cement dose (audit sc-3 and sc-5; live check scenarios-8)
  const doses = [f3, ...credited.filter(([k]) => /^C1_F3_dose_/.test(k)).map(([, x]) => x)].filter((x) => cred(x) && ok(x.dosage)).sort((a, b) => a.dosage - b.dosage);
  if (doses.length >= 3) {
    const cv = doses.map((x) => x.credited_tco2), lo = Math.min(...cv), hi = Math.max(...cv), flat = hi - lo <= 0.05 * hi;
    const capped = doses.filter((x) => arr(x.cement_use).some((c) => obj(c) && c.at_cap)), free = doses.filter((x) => !capped.includes(x));
    const placed = doses.every((x) => !ok(x.char_unplaced_t) || !ok(x.char_t) || x.char_unplaced_t <= 0.01 * x.char_t);
    const cem = doses.map((x) => x.char_to_cement_t).filter(ok), av = doses.map((x) => C(x.avoided_cement_tco2_not_removal)).filter(ok);
    const dLo = dose(doses[0]), dHi = dose(doses[doses.length - 1]);
    const capTxt = capped.length ? `cement plants reach their cap at ${list(capped.map(dose))} (${atCap(capped[0]).replace(" are at their cap", "")} at ${dose(capped[0])})` : "no cement plant reaches its cap at any dose";
    const cemTxt = cem.length ? `the char sent to cement (${kt(Math.min(...cem))}–${kt(Math.max(...cem))} kt a year)` : "";
    const avTxt = av.length ? `the cement emissions it would avoid (${kt(Math.min(...av))}–${kt(Math.max(...av))} kt CO₂ a year: an emission reduction, not a removal)` : "";
    let t = `Across cement doses of ${dLo}–${dHi}, `;
    if (flat) {
      t += `${mt(lo) === mt(hi) ? `removal stays at about ${mt(lo)} Mt` : `removal moves only between ${mt(lo)} and ${mt(hi)} Mt`}.`;
      t += ` Puro credits char in cement and in soil alike, so the dose moves char between cement and farmland rather than changing removal: ${capTxt}${capped.length && free.length ? `, none from ${dose(free.find((x) => x.dosage > capped[capped.length - 1].dosage) || free[free.length - 1])} up` : ""}${capped.length && placed ? ", and nearby farmland takes the char they cannot" : ""}.`;
      if (cemTxt) t += ` What changes is ${cemTxt}${avTxt ? ` and ${avTxt}` : ""}.`;
    } else {
      const rises = cv.every((v, i) => i === 0 || v >= cv[i - 1]), falls = cv.every((v, i) => i === 0 || v <= cv[i - 1]);
      const path = `from ${mt(cv[0])} Mt at ${dLo} to ${mt(cv[cv.length - 1])} Mt at ${dHi}`;
      t += rises ? `removal rises with the dose, ${path}` : falls ? `removal falls as the dose rises, ${path}` : `removal ranges from ${mt(lo)} to ${mt(hi)} Mt`;
      t += rises && capped.length ? `, because cement caps bind: ${capTxt}.` : `: ${capTxt}.`;
      const chg = [cemTxt, avTxt].filter(Boolean);
      if (chg.length) t += ` ${cap(list(chg))} ${chg.length > 1 ? "change" : "changes"} with it.`;
      if (capped.length) t += " Where caps bind, the outlets-limited figure depends on the assumed dose, a technical ceiling, not likely uptake.";
    }
    h.push(`<p class="note">${t}</p>`);
  }

  // Which chars the default lets into cement (Puro 2025 v2) and what that assumes (audit sc-5)
  const highAsh = cf.filter((f) => f === "manure" || f === "litter");
  if (f3 && highAsh.length) {
    const cg = corgTxt(highAsh);
    const pah = String(get(P, "cement_eligible_feeds.source") || "").split(/\.\s+/).find((s) => /PAH/.test(s) && highAsh.some((f) => new RegExp(f, "i").test(s)));
    h.push(`<div class="callout"><b>Cement rule.</b> Puro 2025 v2 sets no minimum carbon content for char in cement or concrete, so the outlets-limited rows let every char that passes its H/C<sub>org</sub> gate into cement, ${esc(list(highAsh.map((f) => FEEDC[f] || f)))} char included: high-ash char${cg ? ` (${cg})` : ""} that Verra's VM0044 keeps out of non-soil uses${cred(vm) ? " (the Verra sensitivity case)" : ""}.${pah ? ` ${esc(pah.replace(/\.$/, ""))}.` : ""} The cement dose, ${dose(f3)} of each plant's whole output, is a technical ceiling, not likely uptake${atCap(f3) ? `; ${atCap(f3)}` : ""}.</div>`);
  }
  if (f3 && ok(f3.plants) && ok(f3.plant_size_t) && ok(f3.feed_used_t) && ok(f3.char_t)) {
    h.push(`<p class="note">Plant size is dry feedstock intake: the ${fmt(f3.plants)} plants of ${fmt(f3.plant_size_t / 1000)} kt in the outlets-limited case take ${kt(f3.feed_used_t)} kt of dry residue a year and make ${kt(f3.char_t)} kt of char.</p>`);
  }

  // All credited scenarios (the selected one is on the map)
  const longNotes = [];
  const rowNote = (k, x) => {
    const bits = [];
    if (k === "C3_E1_no_litter" && f3 && used(f3, "litter") === 0) bits.push("same result as the outlets-limited case, which draws no litter either (0 t)");
    // audit sc-3, older exports: where every feed of a row may go to cement but the default's may not, its cement /
    // soil split comes from the routing rule
    const xf = feedsOf(x), xc = arr(x.cement_feeds);
    if (!newEng && !allEligible && x.soil_dose != null && xf.length && xc.length && xf.every((f) => xc.includes(f))) bits.push("its cement / soil split follows the routing rule (cement first while allowance remains), not haul cost");
    const n = noteOf(k, x);
    if (n && n.length <= 110) bits.push(esc(n));
    else if (n) longNotes.push([displayName(k, x), n]);
    return bits.join(" · ");
  };
  const rad0 = f3 && ok(f3.radius_km) ? f3.radius_km : null;
  const tags = (k, x) => [k === S.sel ? "on map" : "", x.cement_rule === "vm0044" ? "Verra sensitivity" : "", x.credit === "retention" ? "not Puro" : "", k === "C0_published" ? c0Tag() : ""]
    .filter(Boolean).map((t) => `<span class="tag">${t}</span>`).join("");
  const pick = (k, x) => `<button type="button" class="pick" data-id="${esc(k)}"${k === S.sel ? ' aria-current="true"' : ""}>${esc(displayName(k, x))}</button>`;
  const sub = (k, x, extra) => [ok(x.plant_size_t) && !/\bkt\b/.test(displayName(k, x)) ? `${fmt(x.plant_size_t / 1000)} kt/yr feed plants` : "", ok(x.radius_km) && ok(rad0) && x.radius_km !== rad0 ? `${fmt(x.radius_km)} km feed haul` : "", extra, rowNote(k, x)].filter(Boolean).join(" · ");
  if (credited.length) {
    h.push(`<h3>Credited scenarios</h3><p class="note">Pick a row to show it on the map. Mt CO₂ a year, net of transport.</p>
      <table><tr><th>Scenario</th><th class="num">Credited Mt CO₂/yr</th><th class="num">Plants</th><th class="num">Char kt/yr</th><th class="num">To cement kt</th><th class="num">To soil kt</th><th class="num">Unplaced kt</th><th class="num">Radar feed</th><th class="num">In-service Mt</th></tr>
      ${credited.map(([k, x]) => `<tr${k === S.sel ? ' class="sel"' : ""}><td class="name">${pick(k, x)}${tags(k, x)}<span class="sub">${sub(k, x)}</span></td><td class="num"><b>${mt(x.credited_tco2)}</b></td><td class="num">${fmt(x.plants)}</td><td class="num">${kt(x.char_t)}</td><td class="num">${kt(x.char_to_cement_t)}</td><td class="num">${kt(x.char_to_soil_t)}</td><td class="num">${kt(x.char_unplaced_t)}</td><td class="num">${pct(x.radar_feed_share)}</td><td class="num">${mt(x.retained_tco2)}</td></tr>`).join("")}</table>`);
  }
  // Hypothetical upper bounds: never in a credited column
  if (upsides.length) {
    h.push(`<h3>Not credited: hypothetical upper bounds</h3>
      <table><tr><th>Scenario</th><th class="num">Hypothetical Mt CO₂/yr</th><th class="num">Above its credited case, Mt</th><th class="num">Plants</th><th class="num">Char kt/yr</th><th class="num">Litter used kt</th><th class="num">Radar feed</th></tr>
      ${upsides.map(([k, x]) => { const b = x.upside_of ? sc(x.upside_of) : null, d = cred(b) && ok(x.credited_tco2) ? x.credited_tco2 - b.credited_tco2 : null;
        return `<tr class="upside${k === S.sel ? " sel" : ""}"><td class="name">${pick(k, x)}${tags(k, x)}<span class="sub">${sub(k, x, b ? `adds poultry litter to: ${esc(displayName(b.id, b))}` : "")}</span></td><td class="num">${mt(x.credited_tco2)}</td><td class="num">${smt(d)}</td><td class="num">${fmt(x.plants)}</td><td class="num">${kt(x.char_t)}</td><td class="num">${kt(used(x, "litter"))}</td><td class="num">${pct(x.radar_feed_share)}</td></tr>`; }).join("")}</table>`);
  }
  const seen = new Set(), ln = longNotes.filter(([, n]) => !seen.has(n) && seen.add(n));
  if (ln.length) h.push(`<ul class="notes">${ln.map(([name, n]) => `<li><b>${esc(name)}:</b> ${esc(sentence(n))}</li>`).join("")}</ul>`);

  // How the cases are credited and where the char can go
  const ret = S.data.cement_retention, cemTotal = arr(S.data.cement).reduce((a, c) => a + (obj(c) && ok(c.output_mt) ? c.output_mt : 0), 0);
  const haul = C(P.max_char_haul_km), sd = obj(P.soil_dose_t_per_ha) || {}, mos = C(P.min_outlet_share);
  const ratio = ok(sd.manure_litter_central) && ok(sd.central) && sd.central > 0 ? sd.manure_litter_central / sd.central : null;
  const puro = f3 && f3.cement_rule === "puro";
  const notes = [`<b>Credited</b>: Puro.earth Biochar Methodology 2025 v2 applies the soil decay model to char in concrete (rule 6.2.4 and its remark), so a tonne earns the same in cement as in soil. Every figure is a technical potential net of truck emissions only: production and embodied emissions and leakage are not subtracted.`,
    `<b>In-service</b>: char in cement counted at ${fmt(ret, 2)} retention; reported, not creditable under that standard.`];
  let o = `<b>Outlets</b>: each cement plant takes at most the dose times its 2024 cement sales (Yamama sector statistics, local plus export${cemTotal > 0 ? `, ${fmt(cemTotal, 2)} Mt in total` : ""})`;
  if (cf.length) o += puro ? `, and any char that passes the H/C<sub>org</sub> gate (here ${esc(list(cf.map((f) => FEEDC[f] || f)))} chars) within ${fmt(haul)} km` : `, and only low-ash ${esc(list(cf.map((f) => FEEDC[f] || f)))} chars within ${fmt(haul)} km`;
  o += byHaul ? "; char goes to cement only where that earns more than farmland after haul (Puro credits both alike, so where cement is the shorter haul), then to farmland, and what farmland cannot take goes to the nearest cement plants with allowance left. The cement / soil split and the avoided cement emissions follow this rule."
    : allEligible ? "; with farmland limited, char goes to cement wherever allowance remains, then to farmland, so the cement / soil split and the avoided cement emissions follow this rule, not haul cost."
    : "; with farmland limited, those chars go to cement wherever allowance remains, keeping farmland for chars only soil can take.";
  o += ` Soil takes at most ${ok(sd.central) ? `${auto(sd.central)} t of char per hectare a year` : "the dose"} on radar-active fields within ${fmt(sd.return_radius_km)} km${ok(ratio) ? ` (manure and litter chars at ${ratio === 0.5 ? "half" : share(ratio) + " of"} that dose)` : ""}.`;
  const prio = "cement-eligible feed first, then the feed that earns the most credit per hectare of farmland";
  const vmOut = vm ? feedsOf(vm).filter((f) => !arr(vm.cement_feeds).includes(f)).map((f) => FEEDC[f] || f) : [];
  o += ` A plant draws ${allEligible ? `the nearest feed first, since every char in it may go to cement${vmOut.length ? ` (in the Verra sensitivity, where ${esc(list(vmOut))} char may not: ${prio})` : ""}` : prio}; it is built only if at least ${share(mos)} of its char has an outlet.`;
  // the engine's own outlet rule says which soil-use limits it does not enforce
  const suTxt = typeof (f3 && f3.outlets) === "string" ? f3.outlets.split(/;\s*/).find((s) => /not enforced/i.test(s)) : null;
  if (suTxt) o += ` ${esc(sentence(suTxt.replace(/\s*\((?:params\.json|audit)[^)]*\)/gi, "")))}`;
  o += ` Soil doses are a declared assumption, not an agronomic limit${modTxt ? `; modelled ${esc(modTxt)} ${modelled.length > 1 ? "are" : "is"} national (southwest included)` : ""}.`;
  notes.push(o);
  if (get(N, "params._soil_use")) notes.push(`Which chars may also go to soil under Puro's contaminant limits: <a href="national.html#biochar">national page, Biochar tab</a>.`);
  h.push(notes.map((t) => `<p class="note">${t}</p>`).join(""));

  // The scenario on the map
  const s = S.sel ? sc(S.sel) : null;
  if (s) {
    const up = isUpside(s), base = up && s.upside_of ? sc(s.upside_of) : null;
    const fu = obj(s.feed_used_by_feed_t);
    const fuTxt = fu ? Object.keys(FEED).filter((f) => ok(fu[f]) && (fu[f] > 0 || feedsOf(s).includes(f))).map((f) => `${FEED[f]} ${kt(fu[f])}`) : [];
    let p = `${plantsTxt(s) || "–"}<span id="selsites">${sitesTxt(s)}</span> make ${kt(s.char_t)} kt of char a year${ok(s.feed_used_t) ? ` from ${kt(s.feed_used_t)} kt of dry feed` : ""}: ${kt(s.char_to_cement_t)} kt to cement, ${kt(s.char_to_soil_t)} kt to soil, ${kt(s.char_unplaced_t)} kt unplaced.`;
    p += up ? ` Hypothetical removal ${mt(s.credited_tco2)} Mt CO₂ a year net of transport, not credited${cred(base) && ok(s.credited_tco2) ? `: ${mt(Math.abs(s.credited_tco2 - base.credited_tco2))} Mt ${s.credited_tco2 >= base.credited_tco2 ? "more" : "less"} than “${esc(displayName(base.id, base))}”` : ""}.`
      : ` Credited (Puro) ${mt(s.credited_tco2)} Mt CO₂ a year net of transport; in-service ${mt(s.retained_tco2)} Mt.`;
    const av = C(s.avoided_cement_tco2_not_removal);
    if (ok(av)) p += ` Char replacing cement would avoid about ${kt(av)} kt CO₂ a year of cement emissions: an emission reduction, not a removal, shown apart.`;
    h.push(`<h3 id="onmap">On the map: ${esc(displayName(s.id, s))}${up ? ' <span class="tag">not credited</span>' : ""}</h3><p>${p}</p>`);
    if (fuTxt.length) h.push(`<p class="note">Feed used, kt dry a year: ${esc(fuTxt.join(", "))}.</p>`);
    if (noteOf(s.id, s) && s.id !== "C0_published") h.push(`<p class="note">${esc(sentence(noteOf(s.id, s)))}</p>`);   // C0's is in its own note below
    const cu = arr(s.cement_use).filter(obj);
    if (cu.length) h.push(`<table><tr><th>Cement plant</th><th class="num">Allowance kt</th><th class="num">Char kt</th><th>At cap</th></tr>${cu.map((c) => `<tr><td>${esc(c.plant)}</td><td class="num">${fmt(c.allowance_t / 1e3, 1)}</td><td class="num">${fmt(c.char_t / 1e3, 1)}</td><td>${c.at_cap ? "yes" : ""}</td></tr>`).join("")}</table>`);
    if (s.id === "C0_published") h.push(`<p class="note">C0 is ${c0Name()}, with Puro crediting: each plant sends its char to soil or to the nearest open cement plant, whichever haul is shorter, with no limit on either, so its cement rings show which plants take char, not a share of an allowance. It runs ${c0Tables()}.</p>`);
  }
  el.innerHTML = h.join("");
}
const sitesTxt = (x) => ok(S.sites) && S.sites > 0 && x && ok(x.plants) && S.sites < x.plants ? ` on ${fmt(S.sites)} sites (some plants share a site)` : "";

/* ================================================================ Assumptions */
const auto = (x) => ok(x) ? fmt(x, Number.isInteger(x) ? 0 : Math.min(3, (String(x).split(".")[1] || "").length)).replace(/^-/, "−") : esc(x);
const PARAM = {
  qc_thresholds: ["Radar quality check", (v) => [ok(v.bg_max_db) ? `desert background at or below ${auto(v.bg_max_db)} dB on at least one date` : "", ok(v.thr_max_db) ? `threshold at most ${auto(v.thr_max_db)} dB above the desert median` : ""]],
  southwest_admin: ["Southwest regions, reported apart", (v) => [esc(list(arr(v.values).map(admin)))]],
  monte_carlo: ["Monte Carlo", (v) => [ok(v.n) ? `${fmt(v.n)} draws` : "", v.seed != null ? `seed ${esc(v.seed)}` : ""]],
  coverage_factor: [() => {   // audit sc-7: a share of the cropland and tree cover inside the region boxes, not of all farmland
    const cov = obj(get(S.nat, "summary.coverage")), nb = cov && ok(cov.boxes) ? `${fmt(cov.boxes)} ` : "", np = ok(get(cov, "processed.boxes")) ? `${fmt(cov.processed.boxes)} ` : "";
    return `Share of the WorldCover cropland and tree cover in all ${nb}region boxes that lies in the ${np}processed boxes`;
  }, (v) => [ok(v.central) ? `${pct(v.central, 1)} (documentation only); farmland outside every box is not counted` : ""]],
  mewa_fodder_halt_regions: ["Fodder-halt regions (MEWA)", (v) => [esc(list(arr(v.values).map(admin)))]],
  fodder_compliance: ["Fodder-halt compliance", (v) => [arr(v.values).map(share).join(", "), ok(v.central) ? `central ${share(v.central)}` : ""]],
  s2_tier: ["Radar + Sentinel-2 tier used by the scenarios (fodder-halt upper value, the Sentinel-2 bracket row and the robustness runs)", (v) => [v.value ? `“${esc(v.value)}”` : ""]],
  press_water_per_ha: ["Water per hectare, press figures", (v) => pressWater(v)],
  mewa_water_per_ha: ["Water per hectare, press figures", (v) => pressWater(v)],
  pivot_retrofit: ["Pivot retrofit", (v) => [[ok(v.baseline_efficiency) ? `baseline ${share(v.baseline_efficiency)}` : "", ok(v.lesa_efficiency) ? `LESA ${share(v.lesa_efficiency)}` : "", ok(v.lepa_efficiency) ? `LEPA ${share(v.lepa_efficiency)}` : ""].filter(Boolean).join(", ").replace(/^/, "efficiency: "),
    [ok(v.baseline_pressure_head_m) ? `baseline ${auto(v.baseline_pressure_head_m)} m` : "", ok(v.low_pressure_head_m) ? `low-pressure ${auto(v.low_pressure_head_m)} m` : ""].filter(Boolean).join(", ").replace(/^/, "pressure head: ")]],
  rebound_share: ["Freed water re-used (rebound)", (v) => [arr(v.values).map(share).join(", ")]],
  cement_plants_file: ["Cement plants file", (v) => [v.value ? `<code class="path">${esc(v.value)}</code>` : ""]],
  cement_dosage_share: ["Cement dose: char as a share of cement mass", (v) => [arr(v.values).map(share).join(", "), ok(v.central) ? `central ${share(v.central)}` : ""]],
  cement_eligible_feeds: ["Chars allowed in cement", (v) => [arr(v.values).length ? (arr(v.vm0044_values).length ? `default (Puro): ${esc(list(arr(v.values).map((f) => FEEDC[f] || f)))} chars that pass the H/C<sub>org</sub> gate` : `${esc(list(arr(v.values).map((f) => FEEDC[f] || f)))} chars`) : "",
    arr(v.vm0044_values).length ? `Verra VM0044 sensitivity: ${esc(list(arr(v.vm0044_values).map((f) => FEEDC[f] || f)))} chars` : ""]],
  max_char_haul_km: ["Longest char haul to cement", (v) => [ok(v.central) ? `${fmt(v.central)} km` : ""]],
  soil_dose_t_per_ha: ["Char dose on radar-active farmland", (v) => [arr(v.values).length ? `${arr(v.values).map(auto).join(", ")} t/ha a year${ok(v.central) ? ` (central ${auto(v.central)})` : ""}` : "",
    ok(v.manure_litter_central) ? `manure and litter chars ${auto(v.manure_litter_central)} t/ha` : "", ok(v.return_radius_km) ? `fields within ${fmt(v.return_radius_km)} km` : ""]],
  min_outlet_share: ["Char that must have an outlet before a plant is built", (v) => [ok(v.central) ? share(v.central) : ""]],
  avoided_cement_tco2_per_t_char: ["Avoided cement emissions (a reduction, not a removal)", (v) => [ok(v.central) ? `${auto(v.low)} · ${auto(v.central)} · ${auto(v.high)} t CO₂ per t char (low · central · high)` : ""]],
  haul_radius_km: ["Feed haul radius, sensitivity", (v) => [arr(v.values).map((x) => `${fmt(x)} km`).join(", ")]],
};
function pressWater(v) {
  return [ok(v.perennial_m3) ? `perennial fodder ~${fmt(v.perennial_m3)} m³/ha a year` : "", ok(v.seasonal_max_m3) ? `seasonal fodder at most ~${fmt(v.seasonal_max_m3)} m³/ha` : "",
    /cross-check/i.test(String(v.note || "")) ? "press figures" : "press figures, a cross-check only"];   // the note, printed below, says it otherwise
}
function genericParam(v) {   // any input this page does not know yet: low · central · high, lists, then other values
  const out = [];
  if (["low", "central", "high"].some((k) => v[k] !== undefined)) out.push(["low", "central", "high"].filter((k) => v[k] !== undefined).map((k) => `${k} ${auto(v[k])}`).join(" · "));
  if (Array.isArray(v.values)) out.push(v.values.map((x) => ok(x) ? auto(x) : esc(admin(x))).join(", "));
  if (v.value !== undefined && typeof v.value !== "object") out.push(esc(v.value));
  Object.entries(v).forEach(([k, x]) => {
    if (["low", "central", "high", "values", "value", "source", "note"].includes(k) || /_note$/.test(k) || x == null || typeof x === "object") return;
    out.push(`${esc(k.replaceAll("_", " ").replace(/ m3$/, " (m³)").replace(/ db$/, " (dB)").replace(/ km$/, " (km)"))} ${auto(x)}`);
  });
  return out;
}
function runStamp() {
  const ri = obj(S.data.run_inputs);
  let commit = null, pairs = [];
  if (ri) {
    commit = typeof ri.commit === "string" && ri.commit ? ri.commit : null;
    pairs = Object.entries(ri).filter(([k, v]) => k !== "commit" && v != null && v !== "");
  } else {
    String(S.data.run_id || "").split(/\s+/).filter(Boolean).forEach((tok) => {
      const m = /^([A-Za-z_]+):(\S+)$/.exec(tok);
      if (m) { if (m[1] === "commit") commit = m[2]; else pairs.push([m[1], m[2]]); }
      else if (/^[0-9a-f]{7,40}$/.test(tok)) commit = tok;
      // a "<sha>-dirty" token names a commit that does not hold the inputs, so it is not shown
    });
  }
  if (!commit && !pairs.length) return "";
  return `Run: ${commit ? `commit ${esc(commit)}; ` : ""}${pairs.length ? `input fingerprints (short SHA-256 of each input file set): ${pairs.map(([k, v]) => `${esc(k)} ${esc(v)}`).join(" · ")}` : ""}.`;
}
function renderP() {
  const P = obj(S.data.params) || {};
  const rows = Object.entries(P).filter(([k, v]) => !k.startsWith("_") && obj(v)).map(([k, v]) => {
    const def = PARAM[k], label = def ? (typeof def[0] === "function" ? safe("label " + k, def[0], cap(k.replaceAll("_", " "))) : def[0]) : cap(k.replaceAll("_", " "));
    const vals = (safe("param " + k, () => def ? def[1](v) : genericParam(v), []) || []).filter((x) => x && !/^(efficiency|pressure head): ?$/.test(x));
    const src = typeof v.source === "string" && v.source ? esc(sentence(v.source)) : "";
    // every note the input carries ("note", or any "<name>_note"), on its own line so it is not read as the source
    const nts = Object.entries(v).filter(([kk, x]) => (kk === "note" || /_note$/.test(kk)) && typeof x === "string" && x.trim()).map(([, x]) => esc(sentence(x)));
    return `<tr><td>${esc(label)}</td><td class="val">${vals.join("; ") || "–"}${src ? `<span class="sub src">${src}</span>` : ""}${nts.length ? `<span class="sub src pnote"><b>Note:</b> ${nts.join(" ")}</span>` : ""}</td></tr>`;
  });
  const stamp = runStamp();
  $("tp").innerHTML = `<p class="lead">Scenario inputs and their sources. Every other factor is the national model's (<a href="national.html#method">national page, Method tab</a>).</p>
    ${typeof P._note === "string" ? `<p class="note">${esc(P._note)}</p>` : ""}
    ${rows.length ? `<table><tr><th>Input</th><th>Value and source</th></tr>${rows.join("")}</table>` : `<p class="note">No scenario inputs in this data export.</p>`}
    ${stamp || S.data.baseline_check ? `<p class="note">${stamp}${S.data.baseline_check ? ` Check: ${esc(S.data.baseline_check)}.` : ""}</p>` : ""}`;
}

/* ================================================================ Map: scenario select, plants, cement, watch-list */
const GROUPS = [
  ["Feedstock", (k) => /^C1_F\d$/.test(k) || k === "C3_E1_no_litter"],
  ["Plant size", (k) => /^C1_F\d_\d+kt$/.test(k)],
  ["Soil outlet", (k) => /^C1_F3_soil/.test(k)],
  ["Cement dose", (k) => /^C1_F3_dose_/.test(k)],
  ["Cement rule and crediting", (k) => k === "C1_F3_all_feeds_to_cement" || /^C3_F3_/.test(k)],
  ["Feed haul radius", (k) => /^C6_radius_/.test(k)],
  [() => S.ctx.c0Match === true ? "Reference: the national page's siting" : "Reference: the published national siting", (k) => k === "C0_published"],
];
const optLabel = (k, x) => { const n = displayName(k, x); return /\bkt\b/.test(n) || !ok(x.plant_size_t) ? n : `${n} · ${fmt(x.plant_size_t / 1000)} kt plants`; };

function buildSelect() {
  const sel = $("csel");
  if (!sel) return;
  const recs = fam("C", "C_upside");
  if (!recs.length) { sel.innerHTML = "<option>No biochar scenarios</option>"; return; }
  const groups = GROUPS.map(([label]) => ({ label: typeof label === "function" ? label() : label, items: [] })), other = { label: "Other", items: [] }, up = { label: "Not credited: hypothetical upper bounds", items: [] };
  recs.forEach(([k, x]) => {
    if (isUpside(x)) { up.items.push([k, x]); return; }
    const g = GROUPS.findIndex(([, test]) => test(k));
    (g >= 0 ? groups[g] : other).items.push([k, x]);
  });
  sel.innerHTML = [...groups, other, up].filter((g) => g.items.length)
    .map((g) => `<optgroup label="${esc(g.label)}">${g.items.map(([k, x]) => `<option value="${esc(k)}">${esc(optLabel(k, x))}</option>`).join("")}</optgroup>`).join("");
  if (S.sel) sel.value = S.sel;
  sel.disabled = false;
  sel.addEventListener("change", () => choose(sel.value));
}

function choose(id, opt = {}) {
  if (!sc(id)) return;
  S.sel = id;
  S.sites = null;
  const sel = $("csel");
  if (sel && sel.value !== id) sel.value = id;
  safe("biochar", renderC);
  renderReadout();
  if (opt.refocus) {
    const b = [...document.querySelectorAll("#tc .pick")].find((x) => x.dataset.id === id);
    if (b) b.focus({ preventScroll: true });
  }
  drawMap().catch((e) => { if (window.console) console.error("scenarios: map", e); });
}

function renderReadout() {
  const el = $("cread"), btn = document.querySelector('[data-act="open-biochar"]'), x = sc(S.sel);
  if (!el) return;
  const bits = [];
  if (x && ok(x.plants)) bits.push(`${plantsTxt(x)}${ok(S.sites) && S.sites > 0 && S.sites < x.plants ? ` on ${fmt(S.sites)} sites` : ""}`);
  if (x && ok(x.credited_tco2)) bits.push(isUpside(x) ? `${mt(x.credited_tco2)} Mt CO₂/yr net of transport: a hypothetical upper bound, not credited` : `${mt(x.credited_tco2)} Mt CO₂/yr credited, net of transport`);
  if (x && ok(x.radar_feed_share)) bits.push(`${pct(x.radar_feed_share)} of feed radar-measured`);
  el.textContent = bits.join(" · ");
  if (btn) btn.hidden = !bits.length;
}

function onAction(e) {
  const t = e.target.closest("[data-act], .pick");
  if (!t) return;
  if (t.classList.contains("pick")) { if (t.dataset.id && t.dataset.id !== S.sel) choose(t.dataset.id, { refocus: true }); return; }
  const act = t.dataset.act;
  if (act === "open-biochar") {   // the selected scenario's section, at the end of the Biochar tab
    openTab("biochar", { scroll: false });
    const aside = document.querySelector("aside"), el = $("onmap") || aside, tabs = document.querySelector(".tabs"), th = tabs ? tabs.offsetHeight : 0;
    if (!el || !aside) return;
    if (!narrow()) aside.scrollTop += el.getBoundingClientRect().top - aside.getBoundingClientRect().top - th - 8;
    else { const bar = document.querySelector("nav.site"); window.scrollTo(0, Math.max(0, el.getBoundingClientRect().top + window.scrollY - (bar ? bar.offsetHeight : 44) - th - 8)); }
  } else if (act === "watch") {
    const cb = $("showwatch");
    if (!cb || cb.disabled) return;
    cb.checked = !cb.checked;
    cb.dispatchEvent(new Event("change"));
    const mw = $("mapwrap");
    if (cb.checked && mw && narrow()) {   // the map sits above the panel on phones
      const bar = document.querySelector("nav.site"), top = mw.getBoundingClientRect().top, hh = bar ? bar.offsetHeight : 44;
      if (top < hh || top > window.innerHeight * 0.5) window.scrollTo(0, Math.max(0, top + window.scrollY - hh));
    }
  }
}

/* "City (Company):tonnes@kmkm;…" (or "City:tonnes@kmkm" in C0) -> parts */
function parts(str) {
  return String(str || "").split(";").map((p) => p.trim()).filter(Boolean).map((p) => {
    const m = /^(.*):(\d+(?:\.\d+)?)@(\d+(?:\.\d+)?)km$/.exec(p);
    if (!m) return { key: p, label: p, t: null };
    const name = m[1].trim(), nm = /^(.+?) \((.+)\)$/.exec(name);
    return { key: name, city: nm ? nm[1] : name, company: nm ? nm[2] : "", t: Number(m[2]), km: Number(m[3]) };
  });
}
const partText = (x) => x.t == null ? esc(x.label) : `${fmt(x.t)} t to ${esc(x.company ? `${x.company}, ${x.city}` : x.city)} (${fmt(x.km)} km)`;

function siteGroups(rows) {
  const m = new Map();
  rows.forEach((r) => { const k = `${r[0]},${r[1]}`; if (!m.has(k)) m.set(k, { lon: r[0], lat: r[1], plants: [] }); m.get(k).plants.push(r); });
  return [...m.values()];
}

function plantTip(g, upside) {
  const one = (p) => {
    const ch = p[2], cem = p[3], soil = p[4], cr = p[5], rest = ok(ch) && ok(cem) && ok(soil) ? ch - cem - soil : 0;
    const lines = [`${fmt(ch)} t char a year: ${fmt(cem)} t to cement, ${fmt(soil)} t to soil${rest > 1 ? `, ${fmt(rest)} t unplaced` : ""}`,
      upside ? `hypothetical removal ${fmt(cr)} t CO₂ a year net of transport, not credited` : `credited ${fmt(cr)} t CO₂ a year, net of transport`];
    const ps = parts(p[6]);
    if (ps.length) lines.push(`to cement: ${ps.map(partText).join("; ")}`);
    return lines.join("<br>");
  };
  const n = g.plants.length;
  return `<b>${n > 1 ? `${n} biochar plants at this site` : "Biochar plant"}</b><br>` + g.plants.map((p, i) => (n > 1 ? `Plant ${i + 1}: ` : "") + one(p)).join("<br>");
}

function plantLayer(sites, upside) {
  return L.featureGroup(sites.map((g) => {
    const tot = (i) => g.plants.reduce((a, p) => a + (ok(p[i]) ? p[i] : 0), 0), ch = tot(2), cem = tot(3);
    return L.circleMarker([g.lat, g.lon], { radius: 4 + Math.sqrt(Math.max(ch, 0)) / 40, color: "#fff", weight: 1.5,
      fillColor: cem >= ch / 2 ? MARK.cement : MARK.soil, fillOpacity: 0.95 }).bindTooltip(plantTip(g, upside));
  }));
}

function cementLayer(x, rows) {
  const use = {}, got = {}, how = {}, byCity = {};
  arr(x && x.cement_use).forEach((c) => { if (obj(c) && c.plant) use[c.plant] = c; });
  const cem = arr(S.data.cement).filter((c) => obj(c) && ok(c.lat) && ok(c.lon));
  const keyOf = (c) => `${c.city} (${c.company})`;
  cem.forEach((c) => { (byCity[c.city] = byCity[c.city] || []).push(c); });
  const circ = S.ctx.circ;
  rows.forEach((r) => parts(r[6]).forEach((p) => {
    if (!ok(p.t)) return;
    const same = p.company ? [] : (byCity[p.city] || []);   // C0 names the city only
    let k = p.key;
    if (same.length === 1) k = keyOf(same[0]);
    else if (same.length > 1 && ok(circ) && ok(p.km)) {   // two plants in one city: the one whose road distance from this
      const d = same.map((c) => [c, Math.abs(hav(r[0], r[1], c.lon, c.lat) * circ - p.km)]).sort((a, b) => a[1] - b[1]);   // plant best matches the haul
      k = keyOf(d[0][0]);
      how[k] = `${fmt(same.length)} plants in ${esc(p.city)}: attributed by haul distance`;
    } else if (same.length > 1) {   // no way to tell them apart: split evenly, and say so
      same.forEach((c) => { got[keyOf(c)] = (got[keyOf(c)] || 0) + p.t / same.length; how[keyOf(c)] = `${fmt(same.length)} plants in ${esc(p.city)}: split evenly, the data name the city only`; });
      return;
    }
    got[k] = (got[k] || 0) + p.t;
  }));
  const capped = !!x && (ok(x.dosage) || Object.keys(use).length > 0);   // C0 has no allowances
  return L.featureGroup(cem.map((c) => {
    const key = keyOf(c), u = use[key];
    const t = u && ok(u.char_t) ? u.char_t : (got[key] || 0);
    const al = u && ok(u.allowance_t) ? u.allowance_t : null, sh = ok(al) && al > 0 ? Math.min(1, t / al) : null;
    const out = ok(c.output_mt) ? c.output_mt : 0;
    const tip = [`<b>${esc(c.company)}, ${esc(c.city)}</b>: ${fmt(out, 2)} Mt cement sold in 2024`,
      t > 0 ? (sh != null ? `takes ${fmt(t)} t of char a year: ${pct(sh)} of its ${fmt(al)} t allowance${u && u.at_cap ? " (at cap)" : ""}` : `takes ${fmt(t)} t of char a year${capped ? "" : " (no allowance in this siting)"}`)
        : "takes no char in this scenario", t > 0 && how[key] ? how[key] : ""].filter(Boolean);
    // a ring at any fill: the pale tint never matches a solid biochar-plant dot, and the outline stays at full strength
    return L.circleMarker([c.lat, c.lon], { radius: 4 + Math.sqrt(out) * 3, color: MARK.cement, weight: 2, opacity: 1, fillColor: CEM_TINT,
      fillOpacity: t > 0 ? (sh != null ? 0.25 + 0.75 * sh : 0.6) : 0 }).bindTooltip(tip.join("<br>"));
  }));
}

async function drawMap() {
  if (!map || !S.sel) return;
  const tok = ++S.drawSeq, id = S.sel, x = sc(id);
  let rows = S.plants[id], err = null;
  if (!rows) {
    try {
      rows = arr(await j(`data/scenarios/plants_${encodeURIComponent(id)}.json`)).filter((r) => Array.isArray(r) && ok(r[0]) && ok(r[1]));
      S.plants[id] = rows;
    } catch (e) { err = e; rows = []; }
  }
  if (tok !== S.drawSeq) return;   // a newer selection superseded this one
  try {
    if (S.plantLayer) map.removeLayer(S.plantLayer);
    if (S.cementLayer) map.removeLayer(S.cementLayer);
    S.cementLayer = cementLayer(x, rows).addTo(map);                 // drawn first: under everything
    const kc = $("key-cement-txt");   // C0 has no allowances: its fill says only which plants take char
    if (kc) kc.textContent = x && (ok(x.dosage) || arr(x.cement_use).length) ? "cement plant: size = 2024 output; fill = share of its char allowance used (hollow: takes no char)"
      : "cement plant: size = 2024 output; filled = takes char (no allowance in this siting); hollow = takes none";
    if (S.watchLayer && map.hasLayer(S.watchLayer)) S.watchLayer.bringToFront();
    const sites = siteGroups(rows);
    S.sites = err ? null : sites.length;
    S.plantLayer = plantLayer(sites, isUpside(x)).addTo(map);        // drawn last: plants stay clickable
  } catch (e) { if (window.console) console.error("scenarios: draw", e); err = err || e; }
  S.mapNote = err ? { kind: "error", text: `Could not load this scenario's plants for the map (${err.message || err}). Its figures in the panel still apply.` }
    : isUpside(x) ? { kind: "upside", text: "On the map: a hypothetical upper bound, not credited" } : null;
  plantNote();
  renderReadout();
  const ss = $("selsites");
  if (ss) ss.textContent = sitesTxt(x);
  if (!err) fitOnce(rows);
  safe("clear card", clearCard);
}

function fitOnce(rows) {
  if (S.fitted || !map) return;
  const pts = arr(S.data.cement).filter((c) => obj(c) && ok(c.lat) && ok(c.lon)).map((c) => [c.lat, c.lon]);
  rows.forEach((r) => pts.push([r[1], r[0]]));
  if (pts.length < 2) return;
  S.fitted = true;
  const tools = document.querySelector(".maptools"), below = narrow() || !tools ? 0 : tools.offsetHeight;
  safe("fit", () => map.fitBounds(L.latLngBounds(pts), { paddingTopLeft: [24, 24], paddingBottomRight: [24, below + 24], maxZoom: 7, animate: false }));
  S.autoView = viewNow();
}

/* On wide screens the map tools card floats over the map's lower left, and it grows after the first framing (the
   watch-list heading and key lines, a longer readout). Re-frame above the card, never zooming in, only when a drawn
   marker sits under it and the view is still the one this page set: a view the reader moved is left alone. */
const viewNow = () => map ? { c: map.getCenter(), z: map.getZoom() } : null;
function clearCard() {
  if (!map || narrow() || !S.autoView) return;
  const v = viewNow();
  if (v.z !== S.autoView.z || map.latLngToContainerPoint(S.autoView.c).distanceTo(map.latLngToContainerPoint(v.c)) > 2) return;
  const tools = document.querySelector(".maptools"), box = $("map");
  if (!tools || !box) return;
  const pad = tools.offsetHeight + 24, band = box.clientHeight - pad - 24;
  if (band < Math.max(160, 0.3 * box.clientHeight)) return;   // too little map above the card to frame the country in
  const t = tools.getBoundingClientRect(), m = box.getBoundingClientRect();
  const x0 = t.left - m.left, y0 = t.top - m.top, x1 = t.right - m.left, y1 = t.bottom - m.top;
  const layers = [S.watchLayer, S.cementLayer, S.plantLayer].filter((l) => l && map.hasLayer(l));
  const under = layers.some((l) => l.getLayers().some((mk) => {
    const p = map.latLngToContainerPoint(mk.getLatLng());
    return p.x >= x0 && p.x <= x1 && p.y >= y0 && p.y <= y1;
  }));
  if (!under) return;
  const b = L.latLngBounds([]);
  layers.forEach((l) => { const lb = l.getBounds(); if (lb.isValid()) b.extend(lb); });
  if (!b.isValid()) return;
  map.fitBounds(b, { paddingTopLeft: [24, 24], paddingBottomRight: [24, pad], maxZoom: map.getZoom(), animate: false });
  S.autoView = viewNow();
}

function setupWatch() {
  const cb = $("showwatch");
  if (!cb) return;
  cb.disabled = !map;
  cb.addEventListener("change", async () => {
    syncWatch();
    if (cb.checked) await drawWatch();
    else if (S.watchLayer && map) map.removeLayer(S.watchLayer);
    syncWatch();
  });
}

async function drawWatch() {
  if (!map) return;
  if (!S.watch) {
    mapNote("Loading the fodder-halt watch-list…");
    try { S.watch = arr(await j("data/scenarios/watchlist.json")).filter((r) => Array.isArray(r) && ok(r[0]) && ok(r[1])); }
    catch (e) {
      if (window.console) console.error("scenarios: watch-list", e);
      mapNote(`Could not load the fodder-halt watch-list (${e.message}).`, "error");
      $("showwatch").checked = false;
      syncWatch();
      return;
    }
    plantNote();
  }
  if (!$("showwatch").checked) return;   // unticked while loading
  if (!S.watchLayer) S.watchLayer = watchLayer(S.watch);
  if (!map.hasLayer(S.watchLayer)) S.watchLayer.addTo(map);
  if (S.plantLayer) S.plantLayer.bringToFront();   // plants stay on top of the watch-list
  syncWatch();   // grow the key first, so the card is measured at its full height
  safe("clear card", clearCard);
}

/* Watch-list fields by how they got their seasons: fill_code, the 8th element (scripts/export_scenarios.py). Older
   exports carry only the 7th, a Sentinel-2 flag, which does not tell a filled season from Sentinel-2 alone ("s2").
   Circles: the radar classified the field (solid: both seasons; ring: one season filled from Sentinel-2). Angular
   marks: Sentinel-2 alone (diamond: the radar covered it but classified no season; square: the radar never saw it). */
const FILL = {
  0: { shape: "dot", key: "seasons from the radar", tip: "both seasons from the radar" },
  1: { shape: "ring", key: "one season from Sentinel-2", tip: "one season filled from Sentinel-2 (the radar observed the field)" },
  2: { shape: "diamond", key: "Sentinel-2 only: no radar season", tip: "classified from Sentinel-2 alone (no usable radar season: the radar covered the field but classified neither season)" },
  3: { shape: "square", key: "Sentinel-2 only: never seen by radar", tip: "classified from Sentinel-2 alone (outside every radar swath: the radar never observed it)" },
  s2: { shape: "ring", key: "with a season from Sentinel-2", tip: "with a season from Sentinel-2" },
};
const fillCode = (r) => [0, 1, 2, 3].includes(r[7]) ? r[7] : (r[6] === 1 || r[6] === true ? "s2" : 0);
/* A canvas marker drawn as a diamond or a square (Leaflet 1.9.4's canvas renderer; hit-testing stays a circle) */
const ShapeMarker = window.L ? L.CircleMarker.extend({
  _updatePath() {
    const R = this._renderer, sh = this.options.shape;
    if ((sh !== "diamond" && sh !== "square") || !R || !R._ctx || typeof R._fillStroke !== "function") return L.CircleMarker.prototype._updatePath.call(this);
    if (!R._drawing || this._empty()) return;
    const p = this._point, ctx = R._ctx, r = Math.max(Math.round(this._radius), 1);
    ctx.beginPath();
    if (sh === "diamond") { ctx.moveTo(p.x, p.y - r); ctx.lineTo(p.x + r, p.y); ctx.lineTo(p.x, p.y + r); ctx.lineTo(p.x - r, p.y); }
    else { const q = Math.max(1, Math.round(r * 0.8)); ctx.rect(p.x - q, p.y - q, 2 * q, 2 * q); }
    ctx.closePath();
    R._fillStroke(ctx, this);
  },
}) : null;

function watchLayer(rows) {
  const n = { 0: 0, 1: 0, 2: 0, 3: 0, s2: 0 };
  const hollow = { color: MARK.year, weight: 1.5, opacity: 1, fillColor: "#fff", fillOpacity: 0.9 };
  const g = L.featureGroup(rows.map((row) => {
    const [lon, lat, ha, adm, wm, sm] = row, code = fillCode(row), f = FILL[code];
    n[code]++;
    const r = Math.max(1.5, Math.min(6, Math.sqrt(ok(ha) && ha > 0 ? ha : 1) / 3));
    const m = code === 0 ? L.circleMarker([lat, lon], { radius: r, stroke: false, fillColor: MARK.year, fillOpacity: 0.85 })
      : f.shape === "ring" || !ShapeMarker ? L.circleMarker([lat, lon], Object.assign({ radius: Math.max(3, r) }, hollow))
      : new ShapeMarker([lat, lon], Object.assign({ radius: f.shape === "diamond" ? Math.max(4.5, r * 1.3) : Math.max(4, r), shape: f.shape }, hollow));
    const alone = code === 2 || code === 3;
    const mg = (v) => ok(v) ? `${fmt(v, 1)} dB` : code === 0 ? "–" : "from Sentinel-2 (no radar margin)";
    return m.bindTooltip(`Year-round field, ${esc(admin(adm))}: ${fmt(ha, 1)} ha<br>${f.tip}<br>${alone ? "no radar margin: both seasons are from Sentinel-2" : `radar margin above threshold: winter ${mg(wm)}, summer ${mg(sm)}`}`);
  }));
  S.watchCounts = n;
  return g;
}

function syncWatch() {
  const cb = $("showwatch"), on = !!(cb && cb.checked), c = S.watchCounts;
  const line = (id, code, show) => {
    const li = $(id);
    if (!li) return;
    li.hidden = !show;
    const sp = li.querySelector("span");
    if (sp && c) sp.textContent = `${FILL[code].key} (${fmt(c[code])})`;
  };
  const hd = $("key-watch-h");
  if (hd) hd.hidden = !on;
  line("key-watch", 0, on);
  const k1 = c && c.s2 ? "s2" : 1;   // older exports: every field with a season from Sentinel-2 is a ring
  line("key-watch-s2", k1, on && !!c && c[k1] > 0);
  line("key-watch-s2only", 2, on && !!c && c[2] > 0);
  line("key-watch-unseen", 3, on && !!c && c[3] > 0);
  document.querySelectorAll('[data-act="watch"]').forEach((b) => {
    b.disabled = !map;
    b.setAttribute("aria-pressed", on ? "true" : "false");
    b.textContent = on ? "Hide the watch-list on the map" : "Show the watch-list on the map";
  });
}

init().catch((e) => failed(e));
