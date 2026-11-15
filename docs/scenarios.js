/* Circle to Char — scenarios. Reads docs/data/scenarios/*.json (written by scripts/export_scenarios.py).
   All figures are central estimates; uncertainty is the Monte Carlo P5-P95 (and, for reference, the all-low/all-high corners). */
const S = { data: null, sel: null, plantLayer: null, cementLayer: null, watchLayer: null, watch: null, drawSeq: 0 };
const $ = (id) => document.getElementById(id);
const fmt = (v, d = 0) => (v == null || isNaN(v)) ? "–" : Number(v).toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d });
const pct = (x, d = 0) => (x == null || isNaN(x)) ? "–" : fmt(100 * x, d) + "%";
const esc = (t) => String(t == null ? "" : t).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const bn = (v, d = 2) => fmt(v / 1e9, d), kt = (v) => fmt(v / 1e3), mt = (v, d = 2) => fmt(v / 1e6, d);
async function j(p) { const r = await fetch(p); if (!r.ok) throw new Error(p); return r.json(); }

const map = L.map("map", { preferCanvas: true }).setView([24.5, 44.5], 5);
L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
  maxZoom: 17, attribution: "Imagery © Esri, Maxar, Earthstar Geographics" }).addTo(map);

const sc = (id) => (S.data.scenarios || {})[id];
const fam = (f) => Object.entries(S.data.scenarios).filter(([k, v]) => v.family === f);
const C = (o) => o ? o.central : null;

async function init() {
  S.data = await j("data/scenarios/scenarios.json");
  const Cs = fam("C");
  $("csel").innerHTML = Cs.map(([k, v]) => `<option value="${k}">${esc(v.name)} · ${fmt(v.plant_size_t / 1000)} kt</option>`).join("");
  S.sel = (Cs.find(([k]) => k === "C1_F3") || Cs[0] || [null])[0];
  if (S.sel) $("csel").value = S.sel;
  $("csel").onchange = async (e) => { S.sel = e.target.value; renderC(); await drawMap(); };
  $("showwatch").onchange = async (e) => { e.target.checked ? await drawWatch() : (S.watchLayer && map.removeLayer(S.watchLayer)); };
  document.querySelectorAll(".tabs button").forEach(b => b.onclick = () => {
    document.querySelectorAll(".tabs button").forEach(x => x.classList.toggle("on", x === b));
    document.querySelectorAll(".tab").forEach(x => x.classList.toggle("on", x.id === "tab-" + b.dataset.tab));
  });
  renderA(); renderB(); renderR(); renderC(); renderP(); await drawMap();
}

function valLine(v) {
  if (!v) return "–";
  return ["summer", "winter"].filter(k => v[k]).map(k => `${k} kappa ${fmt(v[k].kappa, 2)} (precision ${pct(v[k].precision)}, recall ${pct(v[k].recall)}, ${fmt(v[k].validated_ha / 1e3)} kha checked)`).join("; ");
}

function renderA() {
  const a1 = sc("A1_floor"), swl = sc("A1_southwest_line"), q0so = sc("A2_qc0_swout_wradar"), q0si = sc("A2_qc0_swin_wradar");
  if (!a1) { $("ta").innerHTML = "<p>No headline scenario in this export.</p>"; return; }
  const mc = a1.monte_carlo || {};
  const kpi = (name, key, div, d, unit) => `<div class="kpi"><div class="u">${name}</div><div class="v">${fmt(C(a1[key]) / div, d)}</div><div class="u">${unit}</div>
    <div class="r">${mc[key] ? `P5–P95 ${fmt(mc[key].p5 / div, d)}–${fmt(mc[key].p95 / div, d)}` : ""}<br>all-low / all-high corners ${fmt(a1[key].low / div, d)}–${fmt(a1[key].high / div, d)}</div></div>`;
  const grid = fam("A2"), br = ["A4_both", "A4_radar", "A4_s2fill", "A4_either"].map(sc).filter(Boolean);
  const cls = a1.area_ha_by_class || {};
  const swField = swl ? swl.field_ha : null, swUnusable = swl ? (swl.area_ha_by_class || {}).radar_unusable : null;
  $("ta").innerHTML = `<p class="lead">Where NISAR's data pass the quality check (southwest reported apart), the radar finds <b>${fmt(a1.farmed_ha)} ha</b> farmed in 2025/26: winter ${fmt(a1.active_ha.winter)} ha, summer ${fmt(a1.active_ha.summer)} ha.</p>
    <div class="kpis">${kpi("Groundwater pumped", "water_m3", 1e9, 2, "billion m³/yr")}${kpi("Pumping electricity", "elec_kwh", 1e9, 2, "TWh/yr")}
      ${kpi("Average June–September load", "summer_pumping_avg_mw", 1, 0, "MW")}${kpi("Pumping CO₂ (grid)", "co2_t_grid", 1e6, 2, "Mt/yr")}</div>
    <p class="note">Central estimates. P5–P95: Monte Carlo over every factor's low–high range (depths move together, lift moves together across regions). The corners set every factor to its low or high bound at once, so they fall outside P5–P95. Water is estimated from crop water needs (published irrigation depths), not metered. Energy is a lower-bound model (static lift, a best-practice 0.66 wire-to-water pump, no sprinkler pressure), so its band is a parameter range, not a full uncertainty.</p>
    <p class="note">Agreement with Sentinel-2 on this table: ${valLine(a1.validation)}. Quality check off, southwest also out: ${valLine(q0so && q0so.validation)}. Quality check off, southwest in: ${valLine(q0si && q0si.validation)}.</p>
    ${swl ? `<p class="note">Southwest regions alone (low confidence): ${fmt(swl.farmed_ha)} ha farmed and ${bn(C(swl.water_m3))} bn m³ where the radar passed the quality check; the radar could not classify ${fmt(swUnusable)} ha (${pct(swField ? swUnusable / swField : null)}) of southwest field area.</p>` : ""}
    <h3>What the floor leaves out</h3>
    <p>Seasons the radar did not observe: winter unknown on ${fmt(a1.season_unknown_ha.winter)} ha, summer on ${fmt(a1.season_unknown_ha.summer)} ha (fields with neither season classified: ${fmt(cls.radar_unusable)} ha); fields Sentinel-2 saw green that the radar did not detect (${fmt(cls.idle)} ha); the 54 smaller boxes not processed (~12% of WorldCover farmland); pumping energy for the Arabian Shield regions; sprinkler pressure head.</p>
    ${br.length ? `<h3>Floor to ceiling against official figures (quality check on, southwest in)</h3>
      <table><tr><th>Season rule</th><th class="num">Farmed ha</th><th class="num">Water bn m³</th><th class="num">Wheat ha</th><th class="num">Year-round ha</th></tr>
      ${br.map(s => `<tr><td>${esc(s.name)}</td><td class="num">${fmt(s.farmed_ha)}</td><td class="num">${bn(C(s.water_m3))}</td><td class="num">${fmt((s.area_ha_by_class.winter_only || 0) + (s.area_ha_by_class.wheat_rotation || 0))}</td><td class="num">${fmt(s.area_ha_by_class.year_round)}</td></tr>`).join("")}
      <tr><td>Official: MEWA 2024 farm groundwater; GASTAT 2024 wheat and fodder</td><td></td><td class="num">11.56</td><td class="num">180,455</td><td class="num">214,500 (fodder)</td></tr></table>
      <p class="note">"Either" is a ceiling: fields were outlined from green Sentinel-2 pixels. The Sentinel-2-based rows count southwest greenness, largely rain-fed or spate farming, as irrigated. Official figures cover all farms; radar covers the mapped fields of the 60 largest regions.</p>` : ""}
    ${grid.length ? `<h3>Data-rule robustness (8 runs)</h3><table><tr><th>Run</th><th class="num">Water bn m³</th><th class="num">TWh</th><th class="num">Farmed ha</th><th class="num">Summer kappa</th></tr>
      ${grid.map(([k, s]) => `<tr><td>${esc(s.name)}</td><td class="num">${bn(C(s.water_m3))}</td><td class="num">${bn(C(s.elec_kwh))}</td><td class="num">${fmt(s.farmed_ha)}</td><td class="num">${s.validation && s.validation.summer ? fmt(s.validation.summer.kappa, 2) : "–"}</td></tr>`).join("")}</table>
      <p class="note">Agreement is computed only for seasons the radar classified; seasons filled from Sentinel-2 are not validated against Sentinel-2.</p>` : ""}`;
}

function renderB() {
  const rows = fam("B");
  const s0 = rows.length ? rows[0][1] : null;
  if (!s0) { $("tb").innerHTML = "<p>No fodder-halt scenarios in this export.</p>"; return; }
  const base = s0.baseline, reg = Object.entries(s0.scope_by_region_ha || {}).sort((a, b) => b[1] - a[1]);
  const gap = s0.scope_baseline_water_per_ha_m3 ? 1 - s0.scope_baseline_water_per_ha_m3 / 32000 : null;
  $("tb").innerHTML = `<p class="lead">MEWA stops perennial fodder from <b>16 November 2026</b> in Al-Jouf, Riyadh, Hail, the Eastern Province, Qassim and Tabuk. The 2025/26 radar record is a field-level baseline from the season before: <b>${fmt(s0.scope_fields)} year-round fields, ${fmt(s0.scope_ha)} ha</b>.</p>
    <table><tr><th>Region</th><th class="num">Year-round ha (radar)</th></tr>${reg.map(([r, h]) => `<tr><td>${esc(r.replace(" Region", ""))}</td><td class="num">${fmt(h)}</td></tr>`).join("")}</table>
    <h3>If those fields switch (central estimate)</h3>
    <table><tr><th>What-if</th><th class="num">Water saved bn m³/yr</th><th class="num">TWh saved</th><th class="num">Jun–Sep MW cut</th><th class="num">CO₂ avoided Mt/yr</th></tr>
    ${rows.map(([k, s]) => `<tr><td>${esc(s.name)}</td><td class="num">${bn(base.water_m3 - s.water_m3.central)}</td><td class="num">${bn(base.elec_kwh - s.elec_kwh.central)}</td><td class="num">${fmt(s.baseline_summer_mw - s.summer_pumping_avg_mw.central)}</td><td class="num">${mt(base.co2_t_grid - s.co2_t_grid.central)}</td></tr>`).join("")}</table>
    <p class="note">The model gives every year-round field the same perennial depth: about ${fmt(s0.scope_baseline_water_per_ha_m3)} m³/ha a year pumped, ${gap != null ? `about ${pct(gap)} below` : "below"} the ~32,000 m³/ha MEWA figures reported in the press (seasonal fodder at most ~9,000). Seasonal winter fodder is cut green, so it adds no straw; the wheat variant does. The scope is a baseline, not an exact count: where a region had no usable winter pass (notably the Eastern Province), year-round fields cannot be told from summer crops; and some year-round fields may be other two-season crops rather than perennial fodder. From summer 2027, NISAR's 12-day passes can show which of these fields stopped irrigating in summer: toggle the watch-list on the map. A field is not a farm or a licence; the list is for screening, not enforcement.</p>`;
}

function renderR() {
  const rows = fam("B2");
  if (!rows.length) { $("tr").innerHTML = "<p>No retrofit scenarios in this export.</p>"; return; }
  const any = rows[0][1].by_rebound[Object.keys(rows[0][1].by_rebound)[0]];
  $("tr").innerHTML = `<p class="lead">Subsidised low-pressure pivots save pumped water only if the freed water is not used to irrigate more land; the lower pressure still cuts some energy either way. ${fmt(any.pivot_fields)} sprinkler pivots (${fmt(any.pivot_ha)} ha) on the headline table.</p>
    <table><tr><th>Retrofit</th><th>Freed water re-used</th><th class="num">Pumped water saved bn m³</th><th class="num">TWh saved</th><th class="num">Jun–Sep MW</th><th class="num">CO₂ Mt</th></tr>
    ${rows.flatMap(([k, s]) => Object.entries(s.by_rebound).map(([r, v]) => `<tr><td>${esc(s.name)}</td><td>${pct(+r)}</td><td class="num">${bn(v.pumped_water_saved_m3)}</td><td class="num">${bn(v.elec_saved_kwh)}</td><td class="num">${fmt(v.summer_mw_saved)}</td><td class="num">${mt(v.co2_saved_t)}</td></tr>`)).join("")}</table>
    <p class="note">Central estimate. Efficiencies and pressures are US values (Amosson et al. 2011); no Saudi figures were found. Energy here includes the sprinkler pressure head that the headline omits. This is pumped water, not depletion: crop water needs do not change, and how much of today's losses returns to the aquifer is unknown. The "0%" row holds only if allocations are cut to post-retrofit need, or irrigated area and seasons are frozen at the radar baseline (which the radar can check); a volume cap at today's use would leave the freed water free to be re-used.</p>`;
}

function renderC() {
  const rows = fam("C");
  const s = S.sel ? sc(S.sel) : null;
  const f1 = sc("C1_F1"), f3 = sc("C1_F3"), un = sc("C1_F3_soil_unlimited"), ac = sc("C1_F3_all_feeds_to_cement"), c0 = sc("C0_published");
  const dz = fam("C").filter(([k]) => k.startsWith("C1_F3_dose_")).map(([k, v]) => v.credited_tco2);
  $("tc").innerHTML = !rows.length ? "<p>No biochar scenarios in this export.</p>" : `<p class="lead">How much durable removal stands on residues the radar measured, and what do modelled manure and litter add once outlets are realistic?</p>
    ${f1 && f3 && un ? `<div class="card"><b>What decides the number is where manure and litter char can go.</b> Radar-measured straw and fronds alone: <b>${mt(f1.credited_tco2)} Mt CO₂/yr</b>. All feeds, with farmland as the only soil outlet: ${mt(f3.credited_tco2)} Mt${ac ? `; letting manure and litter chars into cement as well: ${mt(ac.credited_tco2)} Mt` : ""}; with soil absorption unlimited: ${mt(un.credited_tco2)} Mt.${dz.length ? ` Across cement doses of 0.25–5% the all-feeds figure ranges only ${mt(Math.min(f3.credited_tco2, ...dz))}–${mt(Math.max(f3.credited_tco2, ...dz))} Mt: only straw and frond chars qualify for cement, and there is little of them.` : ""}${c0 ? ` For reference, the national page's gross figure at 50 kt plants (same crediting, soil absorption and cement uptake unlimited, published field table) is ${mt(c0.credited_tco2)} Mt.` : ""}</div>` : ""}
    <table><tr><th>Scenario</th><th class="num">Plants</th><th class="num">Char kt/yr</th><th class="num">Cement kt</th><th class="num">Soil kt</th><th class="num">Unplaced kt</th><th class="num">Credited Mt CO₂/yr</th><th class="num">Radar feed</th></tr>
    ${rows.map(([k, x]) => `<tr${k === S.sel ? ' style="background:#f1f6f5"' : ""}><td>${esc(x.name)}<span class="sub">${fmt(x.plant_size_t / 1000)} kt plants${x.radius_km && x.radius_km !== 100 ? ", " + fmt(x.radius_km) + " km" : ""}${x.note ? " · " + esc(x.note) : ""}</span></td>
      <td class="num">${fmt(x.plants)}</td><td class="num">${kt(x.char_t)}</td><td class="num">${kt(x.char_to_cement_t)}</td><td class="num">${kt(x.char_to_soil_t)}</td><td class="num">${kt(x.char_unplaced_t)}</td>
      <td class="num"><b>${mt(x.credited_tco2)}</b><span class="sub">${mt(x.retained_tco2)} in-service</span></td><td class="num">${pct(x.radar_feed_share)}</td></tr>`).join("")}</table>
    <p class="note"><b>Credited</b>: Puro.earth Biochar Methodology 2025 v2 applies the soil decay model to char in concrete (rule 6.2.4 and its remark), so a tonne earns the same in cement as in soil. <b>In-service</b>: char in cement counted at ${fmt(S.data.cement_retention, 2)} retention; reported, not creditable under that standard. Outlets: each cement plant takes at most the dose times its 2024 cement sales (Yamama sector statistics, local plus export, 51.15 Mt in total), and only low-ash straw and frond chars within 300 km; with farmland limited, those chars go to cement wherever allowance remains, keeping farmland for chars only soil can take. Soil takes at most the dose on radar-active fields within 100 km (manure and litter chars at half the dose). A plant draws its most creditable feed first and is built only if at least 80% of its char has an outlet. Soil doses are a declared assumption, not an agronomic limit; modelled manure and litter are national (southwest included).</p>
    ${s ? `<h3>${esc(s.name)}</h3><p>${fmt(s.plants)} plants make ${kt(s.char_t)} kt of char a year: ${kt(s.char_to_cement_t)} kt to cement, ${kt(s.char_to_soil_t)} kt to soil, ${kt(s.char_unplaced_t)} kt unplaced. Credited (Puro) ${mt(s.credited_tco2)} Mt CO₂ a year after transport; in-service ${mt(s.retained_tco2)} Mt.${s.avoided_cement_tco2_not_removal ? ` Char replacing cement would avoid about ${kt(s.avoided_cement_tco2_not_removal.central)} kt CO₂ a year of cement emissions: an emission reduction, not a removal, shown apart.` : ""}</p>
      ${s.cement_use && s.cement_use.length ? `<table><tr><th>Cement plant</th><th class="num">Allowance kt</th><th class="num">Char kt</th><th>At cap</th></tr>${s.cement_use.map(c => `<tr><td>${esc(c.plant)}</td><td class="num">${fmt(c.allowance_t / 1e3, 1)}</td><td class="num">${fmt(c.char_t / 1e3, 1)}</td><td>${c.at_cap ? "yes" : ""}</td></tr>`).join("")}</table>` : (s.id === "C0_published" ? `<p class="note">C0 is the national page's siting: each plant sends its char to soil or to the nearest open cement plant, whichever haul is shorter, with no limit on either.</p>` : "")}` : ""}`;
}

function renderP() {
  const P = S.data.params || {};
  const show = (v) => {
    const parts = [];
    if (v.central !== undefined) parts.push(`central ${v.central}`);
    if (Array.isArray(v.values)) parts.push(v.values.join(", "));
    ["low", "high", "n", "seed", "value", "baseline_efficiency", "lesa_efficiency", "lepa_efficiency", "baseline_pressure_head_m", "low_pressure_head_m", "bg_max_db", "thr_max_db", "manure_litter_central", "return_radius_km", "perennial_m3", "seasonal_max_m3"].forEach(k => v[k] !== undefined && parts.push(`${k.replaceAll("_", " ")} ${v[k]}`));
    return parts.join("; ");
  };
  $("tp").innerHTML = `<p class="lead">Scenario inputs and sources. Every other factor is the national model's (national view, Method tab).</p>
    <table><tr><th>Input</th><th>Value</th><th>Source</th></tr>
    ${Object.entries(P).filter(([k, v]) => !k.startsWith("_") && v && typeof v === "object").map(([k, v]) => `<tr><td>${esc(k.replaceAll("_", " "))}</td><td>${esc(show(v))}</td><td>${esc(v.source)}</td></tr>`).join("")}</table>
    <p class="note">Run: ${esc(S.data.run_id || "")}. ${esc(S.data.baseline_check || "")}.</p>`;
}

async function drawMap() {
  const tok = ++S.drawSeq;
  if (!S.sel) return;
  const s = sc(S.sel);
  let rows = [];
  try { rows = await j(`data/scenarios/plants_${S.sel}.json`); } catch (e) {}
  if (tok !== S.drawSeq) return;  // a newer selection superseded this one
  if (S.plantLayer) map.removeLayer(S.plantLayer);
  if (S.cementLayer) map.removeLayer(S.cementLayer);
  S.plantLayer = L.layerGroup(rows.map(([lon, lat, ch, cem, soil, cred, parts]) => L.circleMarker([lat, lon], {
    radius: 4 + Math.sqrt(ch) / 40, color: "#fff", weight: 1.5, fillColor: cem >= ch / 2 ? "#5b2c83" : "#0f6e6a", fillOpacity: 0.95 })
    .bindTooltip(`${fmt(ch)} t char/yr: ${fmt(cem)} t to cement, ${fmt(soil)} t to soil${ch - cem - soil > 1 ? `, ${fmt(ch - cem - soil)} t unplaced` : ""}<br>credited ${fmt(cred)} t CO₂/yr${parts ? "<br>" + esc(parts.replaceAll(";", ", ")) : ""}`))).addTo(map);
  const use = {};
  (s.cement_use || []).forEach(c => { use[c.plant] = c; });
  S.cementLayer = L.layerGroup(S.data.cement.map(c => {
    const u = use[`${c.city} (${c.company})`], got = u ? u.char_t : 0, al = u ? u.allowance_t : null;
    return L.circleMarker([c.lat, c.lon], { radius: 4 + Math.sqrt(c.output_mt) * 3, color: "#5b2c83", weight: 2,
      fillColor: "#5b2c83", fillOpacity: al ? Math.min(1, got / al) * 0.8 : 0.05 })
      .bindTooltip(`${esc(c.company)}, ${esc(c.city)}: ${fmt(c.output_mt, 2)} Mt cement sold in 2024${u ? `<br>char ${fmt(got)} of ${fmt(al)} t allowance` : ""}`);
  })).addTo(map);
}

async function drawWatch() {
  if (!S.watch) { try { S.watch = await j("data/scenarios/watchlist.json"); } catch (e) { S.watch = []; } }
  if (!$("showwatch").checked) return;  // unticked while loading
  if (S.watchLayer) map.removeLayer(S.watchLayer);
  S.watchLayer = L.layerGroup(S.watch.map(([lon, lat, ha, adm, wm, sm]) => L.circleMarker([lat, lon], {
    radius: Math.max(1.5, Math.min(6, Math.sqrt(ha) / 3)), stroke: false, fillColor: "#b23a00", fillOpacity: 0.8 })
    .bindTooltip(`Year-round field, ${esc(adm)}: ${fmt(ha, 1)} ha<br>radar margin above threshold: winter ${fmt(wm, 1)} dB, summer ${fmt(sm, 1)} dB`))).addTo(map);
}

init().catch(e => document.body.insertAdjacentHTML("beforeend", `<p style="padding:16px">Could not load data: ${esc(e.message)}</p>`));
