/* SkyMeter: Aquifer outlook. Reads data/v2/summary.json (its insar block) and data/v2/insar/insar.json (the full pilot
   results). Every figure on the page comes from those two files; a missing key hides its sentence, card or cell instead of
   showing NaN or undefined. */
"use strict";

const DATA = "data/v2/";
const FULL = DATA + "insar/insar.json";
const ICO = (id, cls = "") => `<svg class="ico${cls ? " " + cls : ""}" aria-hidden="true"><use href="img/icons.svg#i-${id}"/></svg>`;
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/* ---------- helpers ---------- */
const $ = (id) => document.getElementById(id);
const num = (v) => (v == null || v === "" || typeof v === "boolean" || Array.isArray(v) || isNaN(v)) ? null : Number(v);
const fmt = (v, d = 0) => {
  const x = num(v);
  if (x == null) return "–";
  // toFixed rounds the stored binary value, as the pipeline does (2.05 years prints 2.0 there and here); no "−0.0"
  const r = Number(x.toFixed(d)), y = r === 0 ? 0 : r;
  return y.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }).replace(/^-/, "−");
};
const mm = (v) => { const x = num(v); return x == null ? "–" : fmt(x, Math.abs(x) >= 10 ? 0 : 1); };   // millimetres: 1 decimal under 10
const mm0 = (v) => fmt(v, 0);   // field movement summed over a record: whole millimetres, as in the figures
const whole = (v) => { const x = num(v); return x == null ? "–" : fmt(x, Number.isInteger(x) ? 0 : 1); };
const pct = (x, d = 0) => num(x) == null ? "–" : fmt(100 * x, d) + "%";
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const get = (o, ...path) => path.reduce((a, k) => (a == null ? undefined : a[k]), o);
const obj = (o) => (o && typeof o === "object" && !Array.isArray(o) ? o : null);
const arr = (a) => (Array.isArray(a) ? a : []);
const two = (a) => (Array.isArray(a) && a.length === 2 && a.every((v) => num(v) != null) ? a.map(Number) : null);
const ok = (...v) => v.every((x) => num(x) != null);
const range = (a, b, f) => { const A = f(a), B = f(b); return A === B ? A : `${A}–${B}`; };
const list = (a) => (a.length < 2 ? a.join("") : `${a.slice(0, -1).join(", ")} and ${a[a.length - 1]}`);
const cap = (s) => String(s || "").charAt(0).toUpperCase() + String(s || "").slice(1);
const isDate = (d) => /^\d{4}-\d{2}-\d{2}$/.test(String(d));
const dayLabel = (d) => {
  if (!isDate(d)) return String(d == null ? "–" : d);
  const t = new Date(Date.parse(d + "T00:00:00Z"));
  return isNaN(t) ? String(d) : `${t.getUTCDate()} ${MON[t.getUTCMonth()]} ${t.getUTCFullYear()}`;
};
const show = (id, html) => { const el = $(id); if (!el) return null; if (html) { el.innerHTML = html; el.hidden = false; } else el.hidden = true; return el; };
function safe(fn, el) {
  try { return fn(); } catch (e) {
    console.error(e);
    const box = el && $(el);
    if (box) { box.hidden = false; box.innerHTML = `<p class="alert" role="alert">${ICO("alert")}<span>This part could not be shown (${esc(e.message)}).</span></p>`; }
  }
}

// Data strings shown as prose (method notes, caveats, the technical summary): proper signs, units and dashes, and the
// pipeline's code words in plain names.
const MONTHS = MON.join("|");
const CODE_WORDS = [
  [/\biono_tropo_set\b/g, "ionosphere + troposphere + tides"], [/\biono_tropo\b/g, "ionosphere + troposphere"],
  [/\biono_set\b/g, "ionosphere + tides"], [/\biono\b/g, "ionosphere"],
  [/\bsee reference_patch\b/g, "see Reference area under The pilot in brief"],
  [/\bin pairs\[\]\.noise_mm\b/g, "in the full results file"],
];
function prose(s) {
  let t = String(s == null ? "" : s);
  CODE_WORDS.forEach(([re, w]) => { t = t.replace(re, w); });
  return t
    .replace(/\s->\s/g, " to ").replace(/>=/g, "≥").replace(/<=/g, "≤").replace(/\+\/-/g, "±")
    .replace(/\blambda\s*\/\s*4\s*pi\b/g, "λ/4π").replace(/\blambda\b/g, "λ").replace(/\b4 pi\b/g, "4π")
    .replace(/\bkm2\b/g, "km²").replace(/\bmm2\b/g, "mm²").replace(/ x /g, " × ").replace(/\^-(\d)/g, "^−$1")
    .replace(new RegExp(`\\b(${MONTHS})-(${MONTHS})\\b`, "g"), "$1–$2")
    .replace(new RegExp(`\\b(\\d{1,2})-(\\d{1,2}) (${MONTHS})\\b`, "g"), "$1–$2 $3")
    .replace(/(^|[\s=])-\(/g, "$1−(").replace(/\b(\d) sigma\b/g, "$1σ")
    .replace(/(^|[^\d.\-−])(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)(?=\s?(?:mm|km|cm|m\b|years?|yr|%|dB))/g, "$1$2–$3")
    .replace(/(^|[\s(\[])-(\d)/g, "$1−$2").replace(/~\s*/g, "about ")
    .replace(/ {2,}/g, " ").trim();
}
const proseHTML = (s) => esc(prose(s)).replace(/\bT\^(−?[\d.]+)/g, "T<sup>$1</sup>");

/* ---------- data ---------- */
const D = { S: null, I: null };   // S: summary.json insar block; I: insar.json
async function getJSON(p) { const r = await fetch(p); if (!r.ok) throw new Error(`${p} (HTTP ${r.status})`); return r.json(); }

// A field from the summary block first, the full file second (the two hold the same text).
const pickS = (k) => (D.S && D.S[k] != null ? D.S[k] : D.I && D.I[k] != null ? D.I[k] : null);
const det = () => obj(get(D.I, "detectability")) || {};
const expected = () => obj(det().expected) || {};
const sampling = () => num(det().record_sampling_days);
const pairDays = () => { const d = sampling(); return d != null ? `${whole(d)}-day` : "short"; };
// The record each segment covers ("Jun-Oct 2026 chain" reads "Jun–Oct 2026"), from detectability.current_record.
function records() {
  const out = {};
  arr(det().current_record).forEach((r) => {
    if (!r || !r.segment) return;
    const days = num(r.years) != null ? Math.round(r.years * 365.25) : null;
    out[r.segment] = { ...r, name: prose(String(r.label || r.segment).replace(/\s*chain$/i, "")), days };
  });
  return out;
}
const segName = (s) => { const r = records()[s]; return r ? r.name : cap(s); };
// The segment the detectability model is calibrated on ("summer_deramped_5km" gives "summer").
const primarySeg = () => String(det().primary || "summer").split("_")[0];
// The deramp's cut-off, from the method note that states it; null when no note does.
function derampKm() {
  const m = arr(pickS("method_notes")).map(String).join(" ").match(/wavelengths above about (\d+(?:\.\d+)?) km/);
  return m ? num(m[1]) : null;
}

/* ---------- the answer ---------- */
function renderStamp() {
  const T = obj(pickS("track_frame"));
  if (!T || !$("stamptext")) return;
  const bits = [num(T.track) != null ? `track ${whole(T.track)}` : "", num(T.frame) != null ? `frame ${whole(T.frame)}` : "", T.direction ? String(T.direction) : ""].filter(Boolean);
  if (bits.length) $("stamptext").textContent = `NISAR L-band radar interferometry, ${bits.join(", ")}`;
}

function renderLead() {
  const E = expected(), rec = records()[primarySeg()], saq = two(E.saq_band_vertical_mm_yr), sig = two(E.summer_window_signal_los_mm);
  const noise = num(E.summer_window_noise_5km_deramped_mm), days = num(E.summer_window_days) ?? (rec && rec.days);
  const parts = [];
  if (days != null && noise != null && saq && sig) {
    parts.push(`Over the ${whole(days)} days of the ${esc(rec ? rec.name : "summer")} radar record, the noise over desert was <b>${mm(noise)} mm</b> for 5 km averages, while sinking of ${range(saq[0], saq[1], whole)} mm a year, the rate published for the Saq aquifer belt, would move the ground only <b>${range(sig[0], sig[1], mm)} mm</b> along the radar's line of sight in that time.`);
  }
  if (rec && num(rec.mdr) != null) parts.push(`The smallest rate this record could pick out is about <b>${mm(rec.mdr)} mm a year</b>.`);
  const FY = obj(det().first_year_below) || {}, lo = saq ? `${Math.round(saq[0])}mm` : null, hi = saq ? `${Math.round(saq[1])}mm` : null;
  if (lo && ok(FY[`network_low_${lo}`], FY[`network_high_${lo}`])) {
    parts.push(`With continuous data processed as a network with long pairs, ${whole(saq[0])} mm a year would become detectable after about ${range(FY[`network_low_${lo}`], FY[`network_high_${lo}`], (v) => fmt(v, 1))} years${hi && num(FY[`chain_${hi}`]) != null ? `; chaining today's ${pairDays()} pairs, ${whole(saq[1])} mm a year would take about ${fmt(FY[`chain_${hi}`], 1)} years` : ""}.`);
  }
  if (!parts.length) {   // the full file did not load: the summary's own conclusion, as written
    const c = pickS("conclusion");
    $("lead").innerHTML = c ? proseHTML(c) : "The pilot's results could not be read.";
    return;
  }
  $("lead").innerHTML = parts.join(" ");
}

function renderKpis() {
  const E = expected(), rec = records()[primarySeg()], saq = two(E.saq_band_vertical_mm_yr), FY = obj(det().first_year_below) || {};
  const C = get(D.I, "false_movement", "cumulative", primarySeg()) || {};
  const years = arr(det().years).map(num).filter((v) => v != null), maxY = years.length ? Math.max(...years) : null;
  const tiles = [];
  if (rec && num(rec.mdr) != null) {
    tiles.push(["satellite", "Smallest rate the record can detect now", mm(rec.mdr), "mm a year",
      `Vertical, 2σ, from the ${esc(rec.name)} record${ok(rec.pairs) ? ` (${whole(rec.pairs)} pairs${rec.days != null ? ` over ${whole(rec.days)} days` : ""})` : ""}.`]);
  }
  if (saq) tiles.push(["official", "Sinking published for the Saq aquifer belt", range(saq[0], saq[1], whole), "mm a year", "From earlier published radar studies (sources under Method). Treated as vertical."]);
  const lo = saq ? `${Math.round(saq[0])}mm` : null;
  if (lo && ok(FY[`network_low_${lo}`], FY[`network_high_${lo}`])) {
    const ch = num(FY[`chain_${lo}`]);
    tiles.push(["calendar", `Record needed to detect ${whole(saq[0])} mm a year`, range(FY[`network_low_${lo}`], FY[`network_high_${lo}`], (v) => fmt(v, 1)), "years",
      `As a network with long pairs. Chaining ${pairDays()} pairs: ${ch != null ? `about ${fmt(ch, 1)} years` : maxY != null ? `more than ${whole(maxY)} years` : "much longer"}.`]);
  }
  if (ok(get(C, "active_mm", "median"))) {
    tiles.push(["water", "False movement on irrigated fields", mm0(C.active_mm.median), `mm${ok(C.days) ? ` in ${whole(C.days)} days` : ""}`,
      `Median of ${ok(C.n_active) ? `${whole(C.n_active)} fields` : "the irrigated fields"}${ok(get(C, "idle_mm", "median")) ? `; idle fields ${mm0(C.idle_mm.median)} mm` : ""}. Water in the soil, not ground motion.`]);
  }
  $("kpis").innerHTML = tiles.map(([ico, label, value, unit, sub]) => `<div class="kpi"><div class="kpi-label">${ICO(ico, "sm")}${esc(label)}</div>` +
    `<div class="kpi-value">${value}<span class="kpi-unit">${esc(unit)}</span></div><p class="kpi-sub">${sub}</p></div>`).join("");
  $("kpis").hidden = !tiles.length;
}

// Expected sinking against the noise, on one millimetre scale.
function renderSignal() {
  const E = expected(), sig = two(E.summer_window_signal_los_mm), saq = two(E.saq_band_vertical_mm_yr);
  const nd = num(E.summer_window_noise_5km_deramped_mm), nc = num(E.summer_window_noise_5km_corrected_mm), days = num(E.summer_window_days);
  if (!sig || nd == null) { $("signal").innerHTML = ""; return; }
  const rows = [
    { cls: "sig", label: `Expected sinking${saq ? ` at ${range(saq[0], saq[1], whole)} mm a year` : ""}`, a: Math.min(...sig), b: Math.max(...sig), v: `${range(sig[0], sig[1], mm)} mm` },
    { cls: "", label: "Radar noise over desert, 5 km averages", a: 0, b: nd, v: `${mm(nd)} mm` },
  ];
  if (nc != null) rows.push({ cls: "alt", label: "The same without the deramp, which keeps broad bowls", a: 0, b: nc, v: `${mm(nc)} mm` });
  const top = Math.ceil(Math.max(...rows.map((r) => r.b)) * 1.1);
  const pos = (x) => `${(100 * x / top).toFixed(2)}%`;
  $("signal").innerHTML = `<figure class="sn" aria-labelledby="sn-cap">
    <figcaption id="sn-cap"><b>The signal is smaller than the noise.</b> Millimetres along the radar's line of sight${days != null ? ` over ${whole(days)} days` : ""}, ${esc(segName(primarySeg()))}.</figcaption>
    ${rows.map((r) => `<div class="sn-row ${r.cls}"><span class="sn-l">${esc(r.label)}</span><span class="sn-track" aria-hidden="true"><i style="--a:${pos(r.a)};--b:${pos(r.b)}"></i></span><span class="sn-v">${r.v}</span></div>`).join("")}
    <div class="sn-axis" aria-hidden="true"><span></span><span><span>0</span><span>${whole(top)} mm</span></span><span></span></div></figure>`;
}

function renderConclusion() {
  const c = pickS("conclusion");
  if (!c) return;
  $("conclusion").innerHTML = proseHTML(c);
  $("techsum").hidden = false;
}

/* ---------- figures, with click-to-zoom ---------- */
function figMeta(key) {
  const p = pairDays(), dk = derampKm();
  return {
    noise_floor_map: ["Radar noise over the desert, one pair at a time", `The typical noise of one ${p} pair, averaged over 1 km. Farms, other green land and towns are greyed out: only stable desert is used to measure the noise.`],
    chain_noise: ["Noise builds up as pairs are added", `The spread of desert values after each added ${p} pair, for 1 km and 5 km averages, in both records.`],
    false_movement: ["Apparent movement on fields, pair by pair", "Irrigated fields (green in Sentinel-2) against idle fields, relative to the nearby desert; below zero means away from the satellite. The lines show each median's uncertainty."],
    false_movement_cumulative: ["Apparent movement summed over the summer record", "How many fields show each total; the dashed lines mark the two medians."],
    detectability: ["Smallest detectable sinking rate against the length of the record", `Lower is better. Shaded bands: the published Saq-belt rates and slower sinking. Dotted lines: records under a year, when the seasons cannot be separated.${dk != null ? ` The dashed line keeps bowls wider than about ${whole(dk)} km, which the deramp removes.` : ""}`],
  }[key] || [cap(String(key).replaceAll("_", " ")), ""];
}
function renderFigs(boxId, keys) {
  const F = obj(pickS("figures")) || {}, box = $(boxId);
  if (!box) return;
  box.innerHTML = keys.filter((k) => obj(F[k]) && /^[\w.-]+\.(?:png|jpe?g|webp|svg)$/i.test(String(F[k].file || ""))).map((k) => {
    const [title, sub] = figMeta(k), src = DATA + "insar/" + F[k].file, alt = String(F[k].alt || title);
    return `<figure class="fig" id="fig-${esc(k)}">
      <div class="fig-frame"><img src="${esc(src)}" alt="${esc(alt)}" loading="lazy" decoding="async" data-zoom="${esc(k)}">
        <button type="button" class="fig-zoom" data-zoom="${esc(k)}" aria-label="Enlarge: ${esc(title)}">${ICO("expand", "sm")}<span>Enlarge</span></button></div>
      <figcaption><b>${esc(title)}</b> ${esc(sub)}</figcaption></figure>`;
  }).join("");
}
let zoomFrom = null;
function openZoom(key) {
  const F = obj(pickS("figures")) || {}, f = obj(F[key]);
  if (!f) return;
  const src = DATA + "insar/" + f.file, dlg = $("zoom");
  if (!dlg || typeof dlg.showModal !== "function") { window.open(src, "_blank", "noopener"); return; }
  zoomFrom = document.activeElement;
  $("zoom-title").textContent = figMeta(key)[0];
  $("zoom-img").alt = String(f.alt || "");
  $("zoom-img").src = src;
  setActual(false);
  dlg.showModal();
  $("zoom-close").focus();
}
function setActual(on) {
  $("zoom-body").classList.toggle("actual", on);
  $("zoom-size").setAttribute("aria-pressed", on);
  $("zoom-size").textContent = on ? "Fit to window" : "Actual size";
}
function wireZoom() {
  document.addEventListener("click", (e) => {
    const t = e.target.closest("[data-zoom]");
    if (t) { e.preventDefault(); openZoom(t.dataset.zoom); }
  });
  const dlg = $("zoom");
  if (!dlg) return;
  $("zoom-close").addEventListener("click", () => dlg.close());
  $("zoom-size").addEventListener("click", () => setActual(!$("zoom-body").classList.contains("actual")));
  $("zoom-img").addEventListener("click", () => setActual(!$("zoom-body").classList.contains("actual")));
  dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });   // a click on the backdrop
  dlg.addEventListener("close", () => { if (zoomFrom && zoomFrom.focus) zoomFrom.focus(); zoomFrom = null; });
}

/* ---------- why not yet ---------- */
function renderWhy() {
  const N = get(D.I, "noise_summary_mm", "noise_map_12day_1km") || {}, E = expected(), rec = records()[primarySeg()];
  const days = num(E.summer_window_days) ?? (rec && rec.days), sig = two(E.summer_window_signal_los_mm), saq = two(E.saq_band_vertical_mm_yr);
  const s = [];
  if (ok(N.median_mm)) s.push(`Over desert, where nothing should move, one ${pairDays()} pair has a typical noise of <b>${mm(N.median_mm)} mm</b> for 1 km averages${ok(N.p90_mm) ? `, and less than ${mm(N.p90_mm)} mm over nine tenths of the desert` : ""}.`);
  if (days != null && ok(E.summer_window_noise_5km_deramped_mm)) s.push(`Adding pairs up to follow the ground over time adds their noise too: after ${whole(days)} days the spread of 5 km averages reaches <b>${mm(E.summer_window_noise_5km_deramped_mm)} mm</b>${ok(E.summer_window_noise_5km_corrected_mm) ? ` (${mm(E.summer_window_noise_5km_corrected_mm)} mm without the deramp)` : ""}.`);
  if (days != null && sig && saq) s.push(`Over the same ${whole(days)} days, sinking of ${range(saq[0], saq[1], whole)} mm a year would move the ground only <b>${range(sig[0], sig[1], mm)} mm</b> along the radar's line of sight: less than the noise.`);
  show("why-noise", s.join(" "));
  const dk = derampKm();
  show("why-deramp", `The <b>deramp</b> removes smooth tilts across the whole scene, which are mostly atmosphere. It also removes real sinking bowls ${dk != null ? `wider than about ${whole(dk)} km` : "that span the whole scene"}, so the numbers without it are the ones that matter for broad regional sinking, and they are noisier.`);
}

/* ---------- false movement on farms ---------- */
function renderFarms() {
  const FM = obj(get(D.I, "false_movement")) || {}, per = arr(FM.per_pair).filter((p) => p && ok(get(p, "active", "median_mm"), get(p, "idle", "median_mm")));
  if (per.length) {
    const below = per.filter((p) => p.active.median_mm < p.idle.median_mm).length;
    show("farms-pairs", `In <b>${whole(below)} of ${whole(per.length)} pairs</b>, irrigated fields appear to move away from the satellite more than idle fields nearby.`);
  }
  const C = obj(FM.cumulative) || {}, seg = primarySeg(), P = obj(C[seg]), others = Object.keys(C).filter((k) => k !== seg && obj(C[k]));
  const s = [];
  if (P && ok(get(P, "active_mm", "median"), get(P, "idle_mm", "median"))) {
    s.push(`Summed over the ${ok(P.days) ? `${whole(P.days)}-day ` : ""}${esc(segName(seg))} record, irrigated fields show a median of <b>${mm0(P.active_mm.median)} mm</b> of apparent movement${ok(P.n_active) ? ` (${whole(P.n_active)} fields)` : ""}, against <b>${mm0(P.idle_mm.median)} mm</b> on idle fields${ok(P.n_idle) ? ` (${whole(P.n_idle)})` : ""}.`);
    if (ok(P.auc_active_below_idle)) s.push(`Take one irrigated and one idle field at random: the irrigated one shows more apparent sinking ${pct(P.auc_active_below_idle)} of the time.`);
  }
  others.forEach((k) => {
    const Q = C[k];
    if (!ok(get(Q, "active_mm", "median"), get(Q, "idle_mm", "median"))) return;
    s.push(`Over the ${ok(Q.days) ? `${whole(Q.days)}-day ` : ""}${esc(segName(k))} record the gap is smaller, ${mm0(Q.active_mm.median)} mm against ${mm0(Q.idle_mm.median)} mm${ok(Q.n_idle) ? `, with only ${whole(Q.n_idle)} idle field${Q.n_idle === 1 ? "" : "s"}` : ""}.`);
  });
  show("farms-sum", s.join(" "));
}

/* ---------- how long ---------- */
function renderWhen() {
  const T = det(), FY = obj(T.first_year_below) || {}, E = expected(), saq = two(E.saq_band_vertical_mm_yr), weak = two(E.weak_band_vertical_mm_yr);
  const years = arr(T.years).map(num).filter((v) => v != null), maxY = years.length ? Math.max(...years) : null;
  const rates = Object.keys(FY).map((k) => (k.match(/^chain_(\d+(?:\.\d+)?)mm$/) || [])[1]).filter(Boolean).map(Number).sort((a, b) => b - a);
  if (!rates.length) return;
  const yrs = (v) => { const x = num(v); return x == null ? (maxY != null ? `more than ${whole(maxY)} years` : "beyond the modelled record") : x === 1 ? "about 1 year" : `about ${fmt(x, 1)} years`; };
  const net = (r) => {
    const lo = num(FY[`network_low_${r}mm`]), hi = num(FY[`network_high_${r}mm`]);
    if (lo == null && hi == null) return yrs(FY[`network_mid_${r}mm`]);
    if (lo == null || hi == null) return yrs(lo ?? hi);
    return fmt(lo, 1) === fmt(hi, 1) ? yrs(lo) : `${fmt(Math.min(lo, hi), 1)}–${fmt(Math.max(lo, hi), 1)} years`;
  };
  const band = (r) => saq && r >= Math.min(...saq) && r <= Math.max(...saq) ? `<span class="tag">Saq belt</span>` :
    weak && r >= Math.min(...weak) && r <= Math.max(...weak) ? `<span class="tag">slower sinking</span>` : "";
  const noDeramp = rates.some((r) => FY[`network_no_deramp_${r}mm`] !== undefined);
  $("det-table").innerHTML = `<table class="det"><thead><tr><th scope="col">Sinking rate</th><th scope="col">${esc(cap(pairDays()))} pairs chained</th>` +
    `<th scope="col">Network with long pairs</th>${noDeramp ? `<th scope="col">Network, no deramp</th>` : ""}</tr></thead><tbody>` +
    rates.map((r) => `<tr><th scope="row">${whole(r)} mm a year ${band(r)}</th><td>${yrs(FY[`chain_${r}mm`])}</td><td>${net(r)}</td>${noDeramp ? `<td>${yrs(FY[`network_no_deramp_${r}mm`])}</td>` : ""}</tr>`).join("") +
    `</tbody></table>`;
  const dk = derampKm();
  $("det-note").innerHTML = `Vertical rates, 2σ. The network range assumes from half to double today's noise variance per pass.${noDeramp ? ` “No deramp” keeps bowls ${dk != null ? `wider than about ${whole(dk)} km` : "that span the scene"}.` : ""} These times assume continuous ${pairDays()} passes from now on and a noise model fitted to one summer record; seasonal moisture and long-pair effects may lengthen them, and the lowest rates are optimistic (see Caveats).`;
  $("det-card").hidden = false;
  const s = [];
  if (saq) {
    const hi = Math.round(Math.max(...saq)), lo = Math.round(Math.min(...saq));
    if (FY[`chain_${hi}mm`] !== undefined) s.push(`Chaining today's ${pairDays()} pairs, ${whole(hi)} mm a year becomes detectable after ${yrs(FY[`chain_${hi}mm`])}${FY[`chain_${lo}mm`] !== undefined ? ` and ${whole(lo)} mm a year after ${yrs(FY[`chain_${lo}mm`])}` : ""}.`);
    if (FY[`network_low_${lo}mm`] !== undefined) s.push(`Processed as a network with long pairs, ${whole(lo)} mm a year needs ${net(lo)} of continuous data.`);
  }
  show("when-text", s.join(" "));
}

/* ---------- what it means ---------- */
function renderMeaning() {
  const T = det(), FY = obj(T.first_year_below) || {}, E = expected(), saq = two(E.saq_band_vertical_mm_yr), rec = records()[primarySeg()];
  const C = get(D.I, "false_movement", "cumulative", primarySeg()) || {};
  const years = arr(T.years).map(num).filter((v) => v != null), maxY = years.length ? Math.max(...years) : null;
  const lo = saq ? Math.round(Math.min(...saq)) : null, hi = saq ? Math.round(Math.max(...saq)) : null;
  const yr = (v) => { const x = num(v); return x == null ? (maxY != null ? `more than ${whole(maxY)} years` : "much longer") : `about ${fmt(x, 1)} years`; };
  const items = [];
  items.push(`<b>Today's record can neither confirm nor rule out sinking</b>${saq ? ` at the ${range(saq[0], saq[1], whole)} mm a year published for the Saq belt` : ""}${rec && ok(rec.mdr) ? `: it could only show sinking faster than about ${mm(rec.mdr)} mm a year` : ""}.`);
  if (lo != null && ok(FY[`network_low_${lo}mm`], FY[`network_high_${lo}mm`])) {
    items.push(`<b>A year or so of continuous NISAR data could reach the Saq-belt rates</b> if it is processed as a network with long pairs: ${whole(lo)} mm a year after ${range(FY[`network_low_${lo}mm`], FY[`network_high_${lo}mm`], (v) => fmt(v, 1))} years.${FY[`chain_${hi}mm`] !== undefined ? ` Chaining today's ${pairDays()} products would take ${yr(FY[`chain_${hi}mm`])} for ${whole(hi)} mm a year${FY[`chain_${lo}mm`] !== undefined ? ` and ${yr(FY[`chain_${lo}mm`])} for ${whole(lo)} mm a year` : ""}.` : ""}`);
  }
  if (ok(get(C, "active_mm", "median"))) items.push(`<b>Measure on stable desert around the farms, not on the fields.</b> Over irrigated land, short pairs carry false movement (${mm0(C.active_mm.median)} mm${ok(C.days) ? ` in ${whole(C.days)} days` : ""}) far larger than the sinking being sought.`);
  if (lo != null && FY[`network_no_deramp_${lo}mm`] !== undefined) {
    const dk = derampKm();
    items.push(`<b>Broad regional bowls need processing without the deramp</b>${dk != null ? `, since they are wider than about ${whole(dk)} km` : ""}; that is noisier, and ${whole(lo)} mm a year then needs ${yr(FY[`network_no_deramp_${lo}mm`])}.`);
  }
  items.push(`<b>No sinking and no change in water level is claimed.</b> The pilot sets a baseline for monitoring: the noise floor to beat and the irrigation bias to avoid. Wells remain the direct measure of the water table.`);
  $("meaning-list").innerHTML = items.map((t) => `<li>${t}</li>`).join("");
}

/* ---------- pairs ---------- */
function flagText(f) {
  const m = String(f).match(/corrected 1 km sd ([\d.]+) mm > ([\d.]+)/);
  return m ? `Flagged: ${mm(m[1])} mm of noise at 1 km before the deramp (limit ${whole(num(m[2]))} mm)` : esc(prose(f));
}
function renderPairs() {
  const full = arr(get(D.I, "pairs")).filter((p) => p && p.ref), base = arr(pickS("pairs")).filter((p) => p && p.ref);
  const rows = full.length ? full : base;
  if (!rows.length) { $("pairs-table").innerHTML = `<p class="note">No radar pairs were exported.</p>`; return; }
  const rich = full.length > 0;
  const noise = (p) => { const n = get(p, "noise_mm", p.correction_used, "deramped", "sd_1km"); return n != null ? mm(n) : "–"; };
  const rain = (v) => { const x = num(v); return x == null ? "–" : x < 0.05 ? "0" : fmt(x, x < 10 ? 1 : 0); };
  const head = `<tr><th scope="col">Reference date</th><th scope="col">Secondary date</th><th scope="col" class="num">Days</th><th scope="col">Segment</th>` +
    (rich ? `<th scope="col" class="num">Desert noise, 1 km (mm)</th><th scope="col" class="num">Irrigated fields (mm)</th><th scope="col" class="num">Idle fields (mm)</th><th scope="col" class="num">Rain (mm)</th><th scope="col">Note</th>` : "") + `</tr>`;
  const body = rows.map((p) => `<tr><td>${esc(dayLabel(p.ref))}</td><td>${esc(dayLabel(p.sec))}</td><td class="num">${whole(p.dt_days)}</td>` +
    `<td><span class="seg-name">${esc(cap(p.segment))}</span>${records()[p.segment] ? ` <span class="seg-rec">${esc(records()[p.segment].name)}</span>` : ""}</td>` +
    (rich ? `<td class="num">${noise(p)}</td><td class="num">${mm(get(p, "false_movement_mm", "active", "median_mm"))}</td><td class="num">${mm(get(p, "false_movement_mm", "idle", "median_mm"))}</td>` +
      `<td class="num">${rain(p.rain_mm_power)}</td><td class="pnote">${arr(p.flags).map(flagText).join("; ")}</td>` : "") + `</tr>`).join("");
  $("pairs-table").innerHTML = `<table class="pairs"><caption class="sr-only">NISAR interferogram pairs used by the pilot</caption><thead>${head}</thead><tbody>${body}</tbody></table>`;
}

/* ---------- method and caveats ---------- */
function renderFacts() {
  const I = D.I || {}, T = obj(pickS("track_frame")) || {}, B = obj(I.box) || {}, L = obj(I.phase_to_los) || {}, M = obj(I.masks) || {}, R = obj(I.reference_patch) || {};
  const rows = [];
  const geo = [num(T.track) != null ? `track ${whole(T.track)}` : "", num(T.frame) != null ? `frame ${whole(T.frame)}` : "", T.direction || "", T.look ? `${T.look}-looking` : ""].filter(Boolean);
  if (geo.length) rows.push(["Radar", `NISAR L-band${ok(L.wavelength_m) ? ` (${fmt(100 * L.wavelength_m, 1)} cm wavelength)` : ""}, ${esc(geo.join(", "))}`]);
  const bb = arr(B.bbox_lonlat).map(num), sh = arr(B.shape).map(num);
  if (bb.length === 4 && bb.every((v) => v != null)) {
    const size = sh.length === 2 && sh.every((v) => v != null) && ok(B.posting_m) ? `about ${fmt(sh[1] * B.posting_m / 1000)} by ${fmt(sh[0] * B.posting_m / 1000)} km, ` : "";
    rows.push(["Area", `${size}${fmt(bb[0], 2)}–${fmt(bb[2], 2)}°E, ${fmt(bb[1], 2)}–${fmt(bb[3], 2)}°N${ok(B.posting_m) ? `, grid spacing ${whole(B.posting_m)} m` : ""}`]);
  }
  const used = arr(B.regions_used).filter((r) => typeof r === "string");
  if (used.length) rows.push(["Same ground as", `national record regions ${esc(list(used))}`]);
  const recs = records(), order = arr(get(D.I, "pairs")).map((p) => p && p.segment);
  const segs = Object.keys(recs).sort((a, b) => (order.indexOf(a) + 1 || 1e9) - (order.indexOf(b) + 1 || 1e9));   // in date order
  const pairs = arr(get(D.I, "pairs")).length || arr(pickS("pairs")).length;
  if (pairs) rows.push(["Pairs", `${whole(pairs)}${segs.length ? `, in ${segs.length === 1 ? "one record" : "separate records never chained together"}: ${esc(list(segs.map((s) => `${recs[s].name}${ok(recs[s].pairs) ? ` (${whole(recs[s].pairs)})` : ""}`)))}` : ""}`]);
  if (ok(L.incidence_deg_median) || ok(L.los_up_median)) rows.push(["Viewing angle", `${ok(L.incidence_deg_median) ? `${fmt(L.incidence_deg_median)}° incidence` : ""}${ok(L.incidence_deg_median, L.los_up_median) ? "; " : ""}${ok(L.los_up_median) ? `vertical movement = line-of-sight movement ÷ ${fmt(L.los_up_median, 2)}` : ""}`]);
  if (ok(R.km2)) rows.push(["Reference area", `${fmt(R.km2)} km² of stable desert${ok(R.min_distance_from_irrigated_m) ? ` at least ${fmt(R.min_distance_from_irrigated_m)} m from irrigated land` : ""}; every value is relative to it`]);
  if (ok(M.irrigated_share_of_box, M.desert_share_of_box)) rows.push(["Land in the area", `${pct(M.irrigated_share_of_box)} irrigated land and its buffer (masked out); ${pct(M.desert_share_of_box)} desert used for the noise`]);
  $("facts").innerHTML = rows.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${v}</dd></div>`).join("");
  $("facts-card").hidden = !rows.length;
}
function renderNotes() {
  const li = (a) => arr(a).filter((t) => typeof t === "string" && t).map((t) => `<li>${proseHTML(t)}</li>`).join("");
  const cav = li(pickS("caveats")), notes = li(pickS("method_notes"));
  $("caveats").innerHTML = cav || `<li>No caveats were exported.</li>`;
  $("method-notes").innerHTML = notes || `<li>No method notes were exported.</li>`;
  const src = li(expected().sources);
  if (src) { $("sources").innerHTML = src; $("sources").hidden = false; $("sources-h").hidden = false; }
  const full = pickS("full"), path = typeof full === "string" && /^[\w/.-]+\.json$/.test(full) && !full.includes("..") ? DATA + full : FULL;
  show("download", `${ICO("table", "sm")}<span>Every number on this page comes from the pilot's results file: <a href="${esc(path)}">insar.json</a>${D.I && D.I.generated ? `, generated ${esc(dayLabel(D.I.generated))}` : ""}.</span>`);
}

/* ---------- start ---------- */
async function init() {
  wireZoom();
  const [sm, ins] = await Promise.allSettled([getJSON(DATA + "summary.json"), getJSON(FULL)]);
  D.S = sm.status === "fulfilled" ? obj(get(sm.value, "insar")) : null;
  D.I = ins.status === "fulfilled" ? obj(ins.value) : null;
  if (!D.S && !D.I) throw (ins.reason || sm.reason || new Error("no InSAR results"));
  if (!D.I) show("loadfail", `<p class="alert" role="alert">${ICO("alert")}<span>The full pilot results could not be loaded, so only the summary is shown. Reload the page to try again.</span></p>`);
  safe(renderStamp); safe(renderLead, "lead"); safe(renderKpis, "kpis"); safe(renderSignal, "signal"); safe(renderConclusion, "conclusion");
  safe(renderWhy, "why-noise"); safe(() => renderFigs("figs-why", ["noise_floor_map", "chain_noise"]), "figs-why");
  safe(renderFarms, "farms-sum"); safe(() => renderFigs("figs-farms", ["false_movement", "false_movement_cumulative"]), "figs-farms");
  safe(renderWhen, "det-table"); safe(() => renderFigs("figs-when", ["detectability"]), "figs-when");
  safe(renderMeaning, "meaning-list"); safe(renderPairs, "pairs-table"); safe(renderFacts, "facts"); safe(renderNotes, "caveats");
}

init().catch((e) => {
  console.error(e);
  $("lead").textContent = "The pilot's results could not be loaded. Reload the page to try again.";
  show("loadfail", `<p class="alert" role="alert">${ICO("alert")}<span>Could not load the data (${esc(e && e.message ? e.message : e)}).</span></p>`);
  ["meaning-list", "caveats", "method-notes"].forEach((id) => { const el = $(id); if (el) el.innerHTML = "<li>Not available: the data did not load.</li>"; });
  const pt = $("pairs-table"); if (pt) pt.innerHTML = `<p class="note">Not available: the data did not load.</p>`;
});
