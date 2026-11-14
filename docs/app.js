/* Circle to Char — front end. Reads precomputed JSON from data/. */
const COLORS = { winter_only: "#e08a1e", summer_only: "#3b7dd8", year_round: "#2e9e5b", idle: "#9aa0a6" };
const CLASS_NAME = { winter_only: "Winter only (wheat)", summer_only: "Summer only", year_round: "Year-round (fodder, palms)", idle: "Idle" };
const state = { level: "central", size: 25, group: null, overlays: [], layer: null, fieldsLayer: null, plantLayer: null,
  summary: null, ts: null, fields: null, chart: null, chart2: null };

const fmt = (v, d = 0) => (v == null || isNaN(v)) ? "–" : Number(v).toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d });
const $ = (id) => document.getElementById(id);

const map = L.map("map", { zoomControl: true, preferCanvas: true }).setView([26.33, 43.52], 10);
L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
  maxZoom: 17, attribution: "Imagery © Esri, Maxar, Earthstar Geographics",
}).addTo(map);

async function getJSON(p) { const r = await fetch(p); if (!r.ok) throw new Error(p); return r.json(); }

async function init() {
  [state.overlays, state.summary, state.fields] = await Promise.all([
    getJSON("data/overlays.json"), getJSON("data/summary.json"), getJSON("data/fields.geojson")]);
  try { state.ts = await getJSON("data/timeseries.json"); } catch (e) { state.ts = {}; }
  try { addCement(await getJSON("data/cement.geojson")); } catch (e) { /* optional */ }

  const groups = [...new Set(state.overlays.map(o => o.group))];
  $("group").innerHTML = groups.map(g => `<option>${g}</option>`).join("");
  state.group = groups[0];
  $("group").onchange = (e) => { state.group = e.target.value; setupDates(); };
  $("date").oninput = showOverlay;
  $("opacity").oninput = () => state.layer && state.layer.setOpacity($("opacity").value / 100);
  $("showfields").onchange = (e) => e.target.checked ? state.fieldsLayer.addTo(map) : map.removeLayer(state.fieldsLayer);
  $("showplants").onchange = (e) => e.target.checked ? state.plantLayer.addTo(map) : map.removeLayer(state.plantLayer);
  document.querySelectorAll(".level button").forEach(b => b.onclick = () => {
    document.querySelectorAll(".level button").forEach(x => x.classList.toggle("on", x === b));
    state.level = b.dataset.level; renderOverview(); renderPlants();
  });
  document.querySelectorAll(".sizes button").forEach(b => b.onclick = () => {
    document.querySelectorAll(".sizes button").forEach(x => x.classList.toggle("on", x === b));
    state.size = +b.dataset.size; renderPlants();
  });
  document.querySelectorAll(".tabs button").forEach(b => b.onclick = () => openTab(b.dataset.tab));

  drawFields();
  setupDates();
  renderOverview(); renderValidation(); renderPlants(); renderParams();
}

function openTab(name) {
  document.querySelectorAll(".tabs button").forEach(x => x.classList.toggle("on", x.dataset.tab === name));
  document.querySelectorAll(".tab").forEach(x => x.classList.toggle("on", x.id === "tab-" + name));
}

function setupDates() {
  const list = state.overlays.filter(o => o.group === state.group);
  $("date").max = list.length - 1; $("date").value = list.length - 1;
  showOverlay();
}

function showOverlay() {
  const list = state.overlays.filter(o => o.group === state.group);
  const o = list[+$("date").value];
  if (!o) return;
  if (state.layer) map.removeLayer(state.layer);
  state.layer = L.imageOverlay("data/overlays/" + o.file, o.bounds, { opacity: $("opacity").value / 100 }).addTo(map);
  if (state.fieldsLayer) state.fieldsLayer.bringToFront();
  $("datelabel").textContent = o.date; $("legend").textContent = o.legend;
}

function fieldClass(p) {
  const w = p.winter_active ?? p.s2_winter_active, s = p.summer_active ?? p.s2_summer_active;
  return p.class || (w && s ? "year_round" : w ? "winter_only" : s ? "summer_only" : "idle");
}

function drawFields() {
  state.fieldsLayer = L.geoJSON(state.fields, {
    style: f => ({ color: COLORS[fieldClass(f.properties)], weight: 1.2, fillOpacity: 0.08, opacity: 0.9 }),
    onEachFeature: (f, lyr) => lyr.on("click", () => showField(f.properties)),
  }).addTo(map);
}

function addCement(gj) {
  L.geoJSON(gj, { pointToLayer: (f, ll) => L.circleMarker(ll, { radius: 6, color: "#5b2c83", weight: 2, fillOpacity: .7 })
    .bindTooltip(`Cement plant: ${f.properties.owner_name || ""} ${f.properties.city || ""}`) }).addTo(map);
}

function renderOverview() {
  const S = state.summary.supply, L_ = state.level;
  const get = (k) => S[k] ? S[k][L_] : null;
  const rng = (k, div, d = 0) => S[k] ? `${fmt(S[k].low / div, d)}–${fmt(S[k].high / div, d)}` : "";
  const area = S.area_ha_by_class || {};
  const farmed = Object.entries(area).filter(([k]) => k !== "idle").reduce((a, [, v]) => a + v, 0);
  $("lead").innerHTML = `In the core Qassim pivot cluster, radar finds <b>${fmt(farmed)} ha</b> farmed in 2025/26 across <b>${fmt(S.fields)}</b> fields.`;
  const k = [
    ["Water pumped", get("water_m3") / 1e6, "million m³ / year", rng("water_m3", 1e6)],
    ["Pumping electricity", get("elec_kwh") / 1e6, "GWh / year", rng("elec_kwh", 1e6)],
    ["Pumping CO₂ (grid)", get("co2_t_electric") / 1e3, "kt CO₂e / year", rng("co2_t_electric", 1e3)],
    ["Pumping CO₂ (diesel)", get("co2_t_diesel") / 1e3, "kt CO₂e / year", rng("co2_t_diesel", 1e3)],
    ["Collectable straw", get("residue_t_dry") / 1e3, "kt dry / year", rng("residue_t_dry", 1e3, 1), 1],
  ];
  $("kpis").innerHTML = k.map(([n, v, u, r, d]) => `<div class="kpi"><div class="u">${n}</div><div class="v">${fmt(v, d || 0)}</div><div class="u">${u}</div><div class="r">range ${r}</div></div>`).join("");
  const max = Math.max(...Object.values(area), 1);
  $("classbars").innerHTML = ["winter_only", "summer_only", "year_round"].filter(c => area[c] != null).map(c =>
    `<div class="bar"><span><span class="swatch" style="background:${COLORS[c]}"></span>${CLASS_NAME[c]}</span>
     <div class="track"><div class="fill" style="width:${100 * area[c] / max}%;background:${COLORS[c]}"></div></div>
     <span class="num">${fmt(area[c])} ha</span></div>`).join("");
}

function renderValidation() {
  const V = state.summary.validation;
  if (!V) { $("validation").innerHTML = "<p class='note'>Validation runs once radar data is processed.</p>"; return; }
  const rows = ["winter", "summer"].filter(s => V[s]).map(s => {
    const v = V[s];
    return `<tr><td>${s}</td><td class="num big">${fmt(100 * v.area_agreement)}%</td><td class="num">${fmt(v.kappa, 2)}</td>
      <td class="num">${fmt(v.radar_active_ha)}</td><td class="num">${fmt(v.s2_active_ha)}</td></tr>`;
  }).join("");
  $("validation").innerHTML = `<table><tr><th>Season</th><th class="num">Area agreement</th><th class="num">Kappa</th>
    <th class="num">Radar farmed ha</th><th class="num">Sentinel-2 farmed ha</th></tr>${rows}</table>
    <p class="note">Rule: a field is farmed when its seasonal peak HV backscatter exceeds ${V.hv_threshold_db} dB, a break found in the radar data itself (Otsu). Sentinel-2 is used only to check, never to tune.</p>`;
}

function renderPlants() {
  const tag = `${state.level}_${state.size}kt`;
  const plants = (state.summary.siting || {})[tag] || [];
  if (state.plantLayer) map.removeLayer(state.plantLayer);
  state.plantLayer = L.layerGroup();
  if (!plants.length) {
    $("plantlist").innerHTML = `<p class="plant">No site can be filled to 80% of a <b>${state.size} kt/y</b> plant with the straw radar finds here (${state.level} estimate). The local limit is supply, not distance: pooling a wider region or other residues would be needed.</p>`;
  } else {
    const tot = plants.reduce((a, p) => a + p.feed_t_dry, 0);
    $("plantlist").innerHTML = `<p><span class="big">${plants.length}</span> plant${plants.length > 1 ? "s" : ""} of ${state.size} kt/y using ${fmt(tot / 1e3, 1)} kt dry straw.</p>` +
      plants.map(p => `<div class="plant"><b>Plant ${p.plant}</b> at ${p.lat.toFixed(3)}°N, ${p.lon.toFixed(3)}°E (${p.kind === "cement" ? "at a cement plant" : "grid site"})<br>
        ${fmt(p.fields)} fields, mean haul ${fmt(p.mean_feed_haul_km, 1)} km, load ${fmt(100 * p.load_factor)}%<br>
        Char: ${fmt(p.char_t)} t/y → carbon removed ${fmt(p.soil_removal_tco2)} t CO₂/y if spread on the fields${p.cement_removal_tco2 && p.cement_km ? `, ${fmt(p.cement_removal_tco2)} t in cement (${fmt(p.cement_km)} km away)` : ""}<br>
        Transport uses <b>${fmt(100 * p.penalty, 1)}%</b> of the removal (best outlet: ${p.best_outlet}).</div>`).join("");
    plants.forEach(p => {
      L.circleMarker([p.lat, p.lon], { radius: 10, color: "#fff", weight: 2, fillColor: "#0f6e6a", fillOpacity: 1 })
        .bindTooltip(`Plant ${p.plant}: ${state.size} kt/y, transport ${fmt(100 * p.penalty, 1)}% of removal`).addTo(state.plantLayer);
    });
  }
  if ($("showplants").checked) state.plantLayer.addTo(map);
}

function showField(p) {
  openTab("field");
  const c = fieldClass(p);
  $("fieldhint").textContent = `Field ${p.id}`;
  $("fieldinfo").innerHTML = `<table>
    <tr><th>Radar class</th><td><span class="swatch" style="background:${COLORS[c]}"></span>${CLASS_NAME[c]}</td></tr>
    <tr><th>Area</th><td>${fmt(p.area_ha, 1)} ha</td></tr>
    <tr><th>Water pumped (central)</th><td>${fmt(p.water_m3_central / 1e3)} thousand m³/y</td></tr>
    <tr><th>Pumping electricity</th><td>${fmt(p.elec_kwh_central / 1e3)} MWh/y</td></tr>
    <tr><th>Collectable straw</th><td>${fmt(p.residue_t_dry_central, 1)} t dry/y</td></tr>
    <tr><th>Sentinel-2 says</th><td>winter ${p.s2_winter_active ? "farmed" : "not farmed"}, summer ${p.s2_summer_active ? "farmed" : "not farmed"}</td></tr>
    ${p.plant_25kt ? `<tr><th>Feeds</th><td>Plant ${p.plant_25kt} (25 kt/y, central)</td></tr>` : ""}</table>`;
  const t = (state.ts || {})[String(p.id)] || {};
  const pts = (arr) => (arr || []).map(([d, v]) => ({ x: d, y: v }));
  if (state.chart) state.chart.destroy();
  if (state.chart2) state.chart2.destroy();
  state.chart = new Chart($("tschart"), {
    type: "line", data: { datasets: [
      { label: "HV backscatter (dB)", data: pts(t.hv), borderColor: "#0f6e6a", tension: .2 },
      { label: "HH backscatter (dB)", data: pts(t.hh), borderColor: "#9aa0a6", tension: .2 }] },
    options: { parsing: true, scales: { x: { type: "category" } }, plugins: { title: { display: true, text: "NISAR backscatter: rises with crop canopy" } } },
  });
  state.chart2 = new Chart($("tschart2"), {
    type: "line", data: { datasets: [
      { label: "12-day coherence", data: pts(t.coh), borderColor: "#7a2e8c", yAxisID: "y", tension: .2 },
      { label: "Soil moisture (m³/m³)", data: pts(t.sm), borderColor: "#3b7dd8", yAxisID: "y", tension: .2 }] },
    options: { scales: { x: { type: "category" }, y: { min: 0, max: 1 } }, plugins: { title: { display: true, text: "Coherence drops when the field is worked or irrigated" } } },
  });
}

function renderParams() {
  const P = state.summary.params;
  const rows = Object.entries(P).filter(([k]) => !k.startsWith("_")).map(([k, v]) => {
    const show = (x) => Array.isArray(x) ? x.map(y => fmt(y / 1000)).join("/") + " kt" : fmt(x, 3);
    return `<tr><td>${k.replaceAll("_", " ")}</td><td class="num">${show(v.low)}</td><td class="num">${show(v.central)}</td><td class="num">${show(v.high)}</td><td>${v.source}</td></tr>`;
  }).join("");
  $("params").innerHTML = `<table><tr><th>Factor</th><th class="num">Low</th><th class="num">Central</th><th class="num">High</th><th>Source</th></tr>${rows}</table>`;
}

init().catch(e => { document.body.insertAdjacentHTML("beforeend", `<p style="padding:16px">Could not load data: ${e.message}</p>`); });
