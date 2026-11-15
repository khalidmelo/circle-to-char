/* Circle to Char — national view. Reads docs/data/national/*.json */
const COL = { 1: "#e08a1e", 6: "#b23a00", 2: "#3b7dd8", 3: "#2e9e5b", 4: "#7a4b1d", 5: "#9aa0a6", 7: "#8e6bbf", 8: "#d1c4e9", 9: "#e0c9a6", 0: "#d0d0d0" };
const CODE = { winter_only: 1, wheat_rotation: 6, summer_only: 2, year_round: 3, palm_grove: 4, partly_seen_active: 7, idle: 5, partly_seen_inactive: 8, radar_unusable: 9, unseen: 0 };
const NAME = { winter_only: "Winter only (wheat)", wheat_rotation: "Wheat, then summer crop", summer_only: "Summer only", year_round: "Year-round (fodder)", palm_grove: "Palm groves",
  partly_seen_active: "One season observed: farmed", idle: "Not detected by radar", partly_seen_inactive: "One season observed: not detected",
  radar_unusable: "Radar not usable (quality check)", unseen: "Not covered by radar" };
const FARMED = ["winter_only", "wheat_rotation", "summer_only", "year_round", "palm_grove", "partly_seen_active"];
const STATUS = { "no fields": "no fields of 3 ha or more", "no radar": "no usable NISAR pass", error: "failed", "not run": "not processed" };
const S = { level: "central", size: 50, data: null, regionLayer: null, plantLayer: null, cementLayer: null, manureLayer: null, fieldLayer: null };
const $ = (id) => document.getElementById(id);
const fmt = (v, d = 0) => (v == null || isNaN(v)) ? "–" : Number(v).toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d });
const pct = (x) => (x == null || isNaN(x)) ? "–" : fmt(100 * x) + "%";
const rng = (o, div, d = 0) => o ? `${fmt(o.low / div, d)}–${fmt(o.high / div, d)}` : "";

const map = L.map("map", { preferCanvas: true }).setView([24.5, 44.5], 5);
L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
  maxZoom: 17, attribution: "Imagery © Esri, Maxar, Earthstar Geographics" }).addTo(map);

async function j(p) { const r = await fetch(p); if (!r.ok) throw new Error(p); return r.json(); }

async function init() {
  S.data = await j("data/national/summary.json");
  try { addCement(await j("data/cement.geojson")); } catch (e) {}
  try { S.manure = await j("data/national/manure.json"); } catch (e) { S.manure = []; }
  drawRegions(); drawManure(); await drawPlants();
  renderOverview(); renderOfficial(); renderBiochar(); renderLenses(); renderMethod();
  document.querySelectorAll(".tabs button").forEach(b => b.onclick = () => tab(b.dataset.tab));
  document.querySelectorAll(".level button").forEach(b => b.onclick = () => {
    document.querySelectorAll(".level button").forEach(x => x.classList.toggle("on", x === b));
    S.level = b.dataset.level; renderOverview(); renderLenses();
  });
  $("size").onchange = async (e) => { S.size = +e.target.value; await drawPlants(); renderBiochar(); };
  $("showregions").onchange = (e) => e.target.checked ? S.regionLayer.addTo(map) : map.removeLayer(S.regionLayer);
  $("showplants").onchange = (e) => e.target.checked ? S.plantLayer.addTo(map) : map.removeLayer(S.plantLayer);
  $("showcement").onchange = (e) => S.cementLayer && (e.target.checked ? S.cementLayer.addTo(map) : map.removeLayer(S.cementLayer));
  $("showmanure").onchange = (e) => e.target.checked ? S.manureLayer.addTo(map) : map.removeLayer(S.manureLayer);
}
function tab(n) {
  document.querySelectorAll(".tabs button").forEach(x => x.classList.toggle("on", x.dataset.tab === n));
  document.querySelectorAll(".tab").forEach(x => x.classList.toggle("on", x.id === "tab-" + n));
}

function drawRegions() {
  S.regionLayer = L.layerGroup().addTo(map);
  S.data.regions.forEach(r => {
    const [x0, y0, x1, y1] = r.bbox, ok = r.status === "ok", used = ok && (r.seasons_classified || ["winter", "summer"]).length > 0;
    const farmed = r.farmed_ha != null ? r.farmed_ha : FARMED.reduce((t, k) => t + (r[k + "_ha"] || 0), 0);
    const rect = L.rectangle([[y0, x0], [y1, x1]], { color: used ? "#ffd166" : "#999", weight: used ? 1.5 : 1, fillOpacity: used ? 0.08 : 0.02, dashArray: used ? null : "4 4" });
    const v = r.validation || {}, why = STATUS[r.status] || r.status;
    const vs = (k) => v[k] && (r.seasons_classified || []).includes(k) ? `agreement ${pct(v[k].area_agreement)}, kappa ${fmt(v[k].kappa, 2)}` : "not classified";
    rect.bindTooltip(`${r.id}${used ? `: ${fmt(farmed)} ha farmed by radar${(r.seasons_classified || []).length === 1 ? ` (${r.seasons_classified[0]} only)` : ""}` : ok ? `: radar not usable (quality check); ${fmt(r.field_ha)} ha of fields mapped` : ` (${why})`}`);
    rect.on("click", () => ok && loadFields(r));
    rect.bindPopup(ok ? `<b>${r.id}</b><br>${fmt(r.fields)} fields, ${fmt(r.field_ha)} ha mapped<br>
      Wheat ${fmt((r.winter_only_ha || 0) + (r.wheat_rotation_ha || 0))} ha (incl. rotation) · summer only ${fmt(r.summer_only_ha)} ha<br>
      Year-round ${fmt(r.year_round_ha)} ha · palms ${fmt(r.palm_grove_ha)} ha<br>
      One season observed ${fmt((r.partly_seen_active_ha || 0) + (r.partly_seen_inactive_ha || 0))} ha (${fmt(r.partly_seen_active_ha)} ha farmed in the season observed)<br>
      Not detected by radar ${fmt(r.idle_ha)} ha${r.radar_unusable_ha ? ` · radar not usable ${fmt(r.radar_unusable_ha)} ha` : ""} · not covered by radar ${fmt(r.unseen_ha)} ha<br>
      Water ${fmt(r.water_m3 / 1e6)} Mm³/y · straw ${fmt(r.straw_t)} t · fronds ${fmt(r.fronds_t)} t<br>
      Radar vs Sentinel-2: winter ${vs("winter")}; summer ${vs("summer")}<br>
      Radar dates: ${(r.dates || []).join(", ")}` : `${r.id}: ${why}`);
    rect.addTo(S.regionLayer);
  });
}

async function loadFields(r) {
  if (S.fieldLayer) map.removeLayer(S.fieldLayer);
  const rows = await j(`data/national/fields/${r.id}.json`);
  S.fieldLayer = L.layerGroup(rows.map(([lon, lat, ha, c]) =>
    L.circleMarker([lat, lon], { radius: Math.max(2, Math.min(9, Math.sqrt(ha) / 1.6)), stroke: false, fillColor: COL[c], fillOpacity: 0.85 }))).addTo(map);
  map.fitBounds([[r.bbox[1], r.bbox[0]], [r.bbox[3], r.bbox[2]]]);
}

function addCement(gj) {
  S.cementLayer = L.geoJSON(gj, { pointToLayer: (f, ll) => L.circleMarker(ll, { radius: 6, color: "#fff", weight: 1.5, fillColor: "#5b2c83", fillOpacity: 1 })
    .bindTooltip(`Cement plant: ${f.properties.city || ""} (${f.properties.cap || "?"} Mt/y)`) }).addTo(map);
}

function drawManure() {
  S.manureLayer = L.layerGroup((S.manure || []).filter(m => m[2] + m[3] > 2000).map(([lon, lat, lt, mt]) =>
    L.circleMarker([lat, lon], { radius: Math.min(8, 1 + Math.sqrt((lt + mt) / 2000)), stroke: false, fillColor: lt > mt ? "#c2185b" : "#8d6e63", fillOpacity: 0.55 })
      .bindTooltip(`~10 km cell: litter ${fmt(lt)} t, manure ${fmt(mt)} t dry/y (modelled)`)));
}

async function drawPlants() {
  if (S.plantLayer) map.removeLayer(S.plantLayer);
  let plants = [];
  try { plants = await j(`data/national/plants_central_${S.size}kt.json`); } catch (e) {}
  S.plants = plants;
  S.plantLayer = L.layerGroup(plants.map(p => L.circleMarker([p.lat, p.lon], {
    radius: 4 + Math.sqrt(S.size) / 1.5, color: "#fff", weight: 2, fillColor: p.best_outlet === "cement" ? "#5b2c83" : "#0f6e6a", fillOpacity: 0.95 })
    .bindTooltip(`Plant ${p.plant}: ${S.size} kt/y · net ${fmt(p.net_removal_tco2)} t CO₂/y via ${p.best_outlet}${p.best_outlet === "cement" ? " (" + p.cement_name + ", " + fmt(p.cement_km) + " km)" : ""}<br>
      feed: straw ${fmt(p.feed_straw)} · fronds ${fmt(p.feed_fronds)} · litter ${fmt(p.feed_litter)} · manure ${fmt(p.feed_manure)} t`)));
  if ($("showplants").checked) S.plantLayer.addTo(map);
}

function kpi(n, v, u, r, d = 0) { return `<div class="kpi"><div class="u">${n}</div><div class="v">${fmt(v, d)}</div><div class="u">${u}</div><div class="r">${r ? "range " + r : ""}</div></div>`; }

function renderOverview() {
  const s = S.data.summary, L_ = S.level, a = s.area_ha_by_class || {};
  const farmed = s.farmed_ha != null ? s.farmed_ha : FARMED.reduce((t, k) => t + (a[k] || 0), 0);
  const v = S.data.validation || {}, act = s.active_ha || {}, nob = s.season_not_observed_ha || {};
  const R = S.data.regions, n = (st) => R.filter(r => r.status === st).length, tried = R.length - n("not run");
  const withRadar = R.filter(r => r.status === "ok" && (r.seasons_classified || ["winter", "summer"]).length).length;
  const rejected = n("ok") - withRadar;
  const other = Object.keys(STATUS).filter(k => k !== "not run" && n(k)).map(k => `${n(k)} ${STATUS[k]}`)
    .concat(rejected ? [`${rejected} where the radar failed the quality check`] : []).join(", ");
  $("ov").innerHTML = `<p class="lead">Of the <b>${tried}</b> largest of ${R.length} farming boxes (${withRadar} with radar results${other ? "; " + other : ""}), radar finds <b>${fmt(farmed)} ha</b> farmed in 2025/26 (winter ${fmt(act.winter)} ha, summer ${fmt(act.summer)} ha) out of ${fmt(s.field_ha)} ha of fields mapped from Sentinel-2.</p>
    <div class="kpis">
      ${kpi("Irrigation water pumped", s.water_m3[L_] / 1e9, "billion m³ / year", rng(s.water_m3, 1e9, 2), 2)}
      ${kpi("Pumping electricity", s.elec_kwh[L_] / 1e9, "TWh / year", rng(s.elec_kwh, 1e9, 2), 2)}
      ${kpi("Summer pumping load", s.summer_pumping_avg_mw[L_], "MW average, Jun–Sep", `${fmt(s.summer_pumping_avg_mw.low)}–${fmt(s.summer_pumping_avg_mw.high)}`)}
      ${kpi("Pumping CO₂ (grid)", s.co2_t_grid[L_] / 1e6, "Mt CO₂e / year", rng(s.co2_t_grid, 1e6, 2), 2)}
      ${kpi("Wheat straw (radar)", s.straw_t_dry[L_] / 1e3, "kt dry / year", rng(s.straw_t_dry, 1e3))}
      ${kpi("Palm fronds (radar + WorldCover)", s.fronds_t_dry[L_] / 1e3, "kt dry / year", rng(s.fronds_t_dry, 1e3))}
    </div>
    <h3>Field classes (radar)</h3>
    ${Object.keys(CODE).filter(k => a[k]).map(k => {
      const mx = Math.max(...Object.values(a)), c = CODE[k];
      return `<div class="bar"><span><span class="swatch" style="background:${COL[c]}"></span>${NAME[k]}</span><div class="track"><div class="fill" style="width:${100 * a[k] / mx}%;background:${COL[c]}"></div></div><span class="num">${fmt(a[k])} ha</span></div>`; }).join("")}
    <p class="note">"Not detected by radar": green in Sentinel-2 at some point in 2025/26 but below the radar threshold in every season observed. Most are fields the radar missed (winter dates come before the canopy; the threshold is conservative), not idle land; in the southwest the threshold fails on rocky ground, and some mapped patches there are rain-greened natural vegetation. "One season observed": the radar had no usable look at the field in the other season (no pass then, the pass missed the field, or that season failed the quality check); winter is unknown on ${fmt(nob.winter)} ha and summer on ${fmt(nob.summer)} ha of these fields.${s.quality_check ? ` "Radar not usable": the quality check rejected every season the radar had in the region (${s.quality_check_rule}).` : ""}</p>
    <h3>Radar vs Sentinel-2 (pooled over regions)</h3>
    ${["winter", "summer"].some(k => v[k] && v[k].agreement != null) ? "" : "<p>No pooled validation in this export.</p>"}
    ${["winter", "summer"].filter(k => v[k] && v[k].agreement != null).map(k => `<p><b>${k[0].toUpperCase() + k.slice(1)}</b> (${v[k].regions} regions, ${fmt(v[k].validated_ha)} ha): agreement ${pct(v[k].agreement)} against ${pct(v[k].chance_agreement)} by chance, kappa <b>${fmt(v[k].kappa, 2)}</b>. Of the area Sentinel-2 saw green, radar found <b>${pct(v[k].recall)}</b>; of the area radar called farmed, <b>${pct(v[k].precision)}</b> was green in Sentinel-2.</p>`).join("")}
    <p class="note">Winter is checked against Sentinel-2 over the radar's own winter dates (late November to January); summer against Sentinel-2 for June–October.${s.quality_check ? ` Quality check applied: ${s.quality_check_rule}.` : ""} The radar threshold needs no training labels: each region's comes from its own bare desert on the same dates. Field outlines, the wheat/fodder split (spring check) and palm groves use Sentinel-2 and ESA WorldCover. Water, energy and straw are likely underestimates: fields the radar did not detect, and seasons it did not observe, get none (radar false alarms and the derived summer-crop depth push the other way). Pumping energy uses regional depth to water (no drawdown) and is not estimated for the Arabian Shield regions (Makkah, Madinah, Asir, Jazan, Najran, Al-Baha).</p>`;
}

function renderOfficial() {
  const o = S.data.official, s = S.data.summary.vs_official || {};
  const rows = o.filter(r => r.fields > 0).map(r => `<tr><td>${r.region}</td>
    <td class="num">${fmt(r.radar_wheat_ha)}</td><td class="num">${fmt(r.gastat_wheat_ha)}</td>
    <td class="num">${fmt(r.radar_year_round_ha)}</td><td class="num">${fmt(r.gastat_fodder_ha)}</td>
    <td class="num">${fmt(r.palms_est_low / 1e6, 1)}–${fmt(r.palms_est_high / 1e6, 1)}</td><td class="num">${fmt(r.gastat_palms / 1e6, 1)}</td>
    <td class="num">${fmt(r.water_m3_central / 1e9, 2)}</td><td class="num">${fmt(r.mewa_agri_groundwater_m3 / 1e9, 2)}</td><td class="num">${fmt(r.radar_partly_seen_ha)}</td><td class="num">${fmt(r.radar_unusable_ha)}</td></tr>`).join("");
  const part = o.reduce((t, r) => t + (r.radar_partly_seen_ha || 0), 0), unus = o.reduce((t, r) => t + (r.radar_unusable_ha || 0), 0);
  $("off").innerHTML = `<p class="lead">How do the radar estimates compare with official 2024 statistics, region by region?</p>
    <table><tr><th>Region</th><th class="num">Radar wheat ha</th><th class="num">GASTAT wheat ha</th><th class="num">Radar year-round ha</th><th class="num">GASTAT fodder ha</th>
    <th class="num">Palms est. (M)</th><th class="num">GASTAT palms (M)</th><th class="num">Water est. (bn m³)</th><th class="num">MEWA farm groundwater (bn m³)</th><th class="num">One season observed ha</th><th class="num">Radar not usable ha</th></tr>${rows}
    <tr><th>National</th><th class="num">${fmt(s.radar_wheat_ha)}</th><th class="num">${fmt(s.gastat_wheat_ha)}</th><th class="num">${fmt(s.radar_year_round_ha)}</th><th class="num">${fmt(s.gastat_fodder_ha)}</th>
    <th class="num">${s.palms_est ? fmt(s.palms_est[0] / 1e6, 1) + "–" + fmt(s.palms_est[1] / 1e6, 1) : "–"}</th><th class="num">${fmt((s.gastat_palms || 0) / 1e6, 1)}</th>
    <th class="num">${s.water_m3 ? fmt(s.water_m3[1] / 1e9, 2) : "–"}</th><th class="num">${fmt((s.mewa_agri_groundwater_m3 || 0) / 1e9, 2)}</th><th class="num">${fmt(part)}</th><th class="num">${fmt(unus)}</th></tr></table>
    <p class="note">Sources: GASTAT Agricultural Statistics 2024 (wheat, fodder, date palms by region); MEWA Statistical Book 2024 pp.62–63 (agricultural groundwater use by region). Radar covers only the mapped fields in the boxes processed, while official figures are whole-region totals. Radar classes are not crop types: "wheat" = farmed in winter only, or in winter and summer but brown in late spring (harvest, from Sentinel-2); "year-round" (green through spring) approximates perennial fodder. Radar's winter dates end in December or January, before the wheat peak, so winter area is a lower bound; where a region had no winter pass ("one season observed"), radar cannot split wheat from fodder at all. Palm count = radar palm-grove area × 100–270 palms/ha; nationally the radar groves capture only part of the Kingdom's palms, but in some regions they include other orchards (olives in Al-Jouf, fruit orchards in Jazan), where the estimate can exceed the official count.</p>`;
}

function renderBiochar() {
  const sz = `central_${S.size}kt`, x = (S.data.siting || {})[sz], sup = x ? x.supply_by_feed_t : {};
  const xr = (S.data.siting || {})[`central_radar_${S.size}kt`], fu = x && x.feed_used_by_feed_t;
  const radarShare = fu && x.feed_used_t ? ((fu.straw || 0) + (fu.fronds || 0)) / x.feed_used_t : null;  // only when the run recorded it
  const share = radarShare == null ? "" : radarShare < 0.01 ? fmt(100 * radarShare, 1) + "%" : pct(radarShare);
  const plants = S.plants || [];
  $("bio").innerHTML = !x ? "<p>Siting not run yet.</p>" : `<p class="lead"><span class="big">${x.plants}</span> plants of ${S.size} kt/y could be filled within ${x.radius_km} km, using <b>${fmt(x.feed_used_t / 1e6, 2)} Mt</b> of ${fmt(x.supply_t / 1e6, 2)} Mt dry residue, removing <b>${fmt(x.net_removal_tco2 / 1e6, 2)} Mt CO₂ a year</b> net of transport${x.capped ? " (the run stopped at its plant cap)" : ""}. This is a technical potential: stored char carbon × the Puro.earth 2025 soil persistence model (used for cement too, rule 6.2.4), minus truck emissions only; production and embodied emissions and leakage are not subtracted, and farmland's capacity to absorb char is not limited.</p>
    <p>${share ? `<b>${share}</b> of that feed is radar-measured (wheat straw, palm fronds); the rest is modelled manure and litter. ` : ""}${xr ? `From radar-measured residues alone: <b>${xr.plants}</b> plants, ${fmt(xr.net_removal_tco2 / 1e6, 2)} Mt CO₂ a year.` : ""}</p>
    <h3>Residue supply (central, dry)</h3>
    <table><tr><th>Stream</th><th class="num">kt / year</th><th>How measured</th></tr>
      <tr><td>Wheat straw</td><td class="num">${fmt((sup.straw || 0) / 1e3)}</td><td>Radar wheat fields (winter only, and wheat-then-summer rotations) × baled straw per ha</td></tr>
      <tr><td>Palm fronds</td><td class="num">${fmt((sup.fronds || 0) / 1e3)}</td><td>Radar-active palm groves (WorldCover trees) × palms/ha × fronds/palm; radar groves cover only part of the Kingdom's palms</td></tr>
      <tr><td>Poultry litter</td><td class="num">${fmt((sup.litter || 0) / 1e3)}</td><td>Modelled: GASTAT 2024 broilers produced (1.32 bn) × bedded litter per bird, plus laying hens × manure per hen, spread by the FAO GLW4 chicken pattern</td></tr>
      <tr><td>Cattle, sheep, goat manure</td><td class="num">${fmt((sup.manure || 0) / 1e3)}</td><td>Modelled: FAO GLW4 pattern × GASTAT 2024 herds × total solids per head × collectable share</td></tr></table>
    ${auditTable()}
    <h3>Plants</h3>
    <p>Char in cement is credited like char in soil (Puro rule 6.2.4), so a plant sends its char to a cement plant only when that is the shorter haul: ${x.cement_outlet_plants} of ${x.plants} do.${x.cement_retained_tco2 ? ` Their char would hold ${fmt(x.cement_retained_tco2 / 1e6, 2)} Mt CO₂ a year in concrete over 60–80 years (at 0.90 retention, within a 0.85–1.0 envelope; reported, not credited).` : ""} Median transport cost ${fmt(100 * (x.median_transport_share || 0), 1)}% of the removal.</p>
    <table><tr><th>#</th><th>Where</th><th class="num">Net t CO₂/y</th><th>Outlet</th><th>Main feed</th></tr>
    ${plants.slice(0, 40).map(p => { const f = { straw: p.feed_straw, fronds: p.feed_fronds, litter: p.feed_litter, manure: p.feed_manure }; const main = Object.entries(f).sort((a, b) => b[1] - a[1])[0][0];
      return `<tr><td>${p.plant}</td><td>${p.lat.toFixed(2)}°N ${p.lon.toFixed(2)}°E ${p.kind === "cement" ? "(" + p.name + ")" : ""}</td><td class="num">${fmt(p.net_removal_tco2)}</td><td>${p.best_outlet}${p.best_outlet === "cement" ? " · " + fmt(p.cement_km) + " km" : ""}</td><td>${main}</td></tr>`; }).join("")}</table>
    <p class="note">Persistence follows Puro's soil model (PF = M − a·H/C<sub>org</sub>, 200 years, 30 °C soil): straw ${fmt((x.persistence || {}).straw, 2)}, fronds ${fmt((x.persistence || {}).fronds, 2)}, litter ${fmt((x.persistence || {}).litter, 2)}, manure ${fmt((x.persistence || {}).manure, 2)}. Litter char's H/C is 0.69 on total carbon; on the organic-carbon basis Puro's 0.70 eligibility gate uses it is about 0.70–0.73, and manure char's H/C (0.56, an assumed class value) also varies widely across measured chars, so their eligibility is uncertain${x.credited_by_feed_tco2 ? ` (litter carries ${fmt(x.credited_by_feed_tco2.litter / 1e6, 2)} Mt and manure ${fmt(x.credited_by_feed_tco2.manure / 1e6, 2)} Mt of the credited removal before haulage)` : ""}. Camels are not included (no gridded data). Plant sizes are scenarios; the ${x.radius_km} km haul limit is an assumption. Constrained cases (how much char farmland and cement can absorb, which chars cement may take, cement dosage) are on the <a href="scenarios.html">scenarios page</a>.</p>`;
}

function auditTable() {
  const a = S.data.residue_audit, m = S.data.mwan;
  if (!a || !m) return "";
  const kt = (t) => fmt(t / 1e3), mt = (v) => fmt(v, 2);
  return `<h3>Against the national waste inventory</h3>
    <table><tr><th>Stream</th><th class="num">This app, kt dry</th><th class="num">Same factors, national statistics, kt dry</th><th class="num">MWAN-based estimate 2024, Mt</th><th>Why they differ</th></tr>
      <tr><td>Wheat straw</td><td class="num">${kt(a.straw_app_t)}</td><td class="num">${kt(a.straw_national_t)}</td><td class="num">${mt(m.streams_2024_mt.grain_residue)} (all grain residue)</td><td>Radar maps ${fmt(a.radar_wheat_ha)} of GASTAT's ${fmt(a.official_wheat_ha)} ha of wheat; the app counts baled wheat straw only, MWAN all cereal residue</td></tr>
      <tr><td>Palm fronds</td><td class="num">${kt(a.fronds_app_t)}</td><td class="num">${kt(a.fronds_national_t)}</td><td class="num">${mt(m.streams_2024_mt.date_palm)}</td><td>Radar groves hold a small part of GASTAT's ${fmt(a.palms_official / 1e6, 1)} M palms; MWAN counts all palm residue</td></tr>
      <tr><td>Poultry litter</td><td class="num">${kt(a.litter_app_t)}</td><td class="num">${kt(a.litter_app_t)}</td><td class="num">${mt(m.streams_2024_mt.broiler)} (broilers)</td><td>MWAN's tonnage is of the order of the birds' fresh (wet) droppings, about 4–5 kg per bird; the app counts dry bedded litter and layer manure</td></tr>
      <tr><td>Manure</td><td class="num">${kt(a.manure_app_t)}</td><td class="num">${kt(a.manure_excreted_t)} excreted</td><td class="num">${mt(m.streams_2024_mt.manure)}</td><td>The app keeps the collectable part (about half; grazing animals' manure is not collected); MWAN's basis is not stated</td></tr></table>
    <p class="note">Source: ${m.source}. MWAN puts agricultural waste at ${fmt(m.agri_total_kt / 1e3, 2)} Mt (${m.agri_total_year}), graded "${m.confidence}" (${m.confidence_legend}). Stream values: ${m.streams_basis}.</p>`;
}

function renderLenses() {
  const s = S.data.summary, L_ = S.level, a = s.area_ha_by_class || {}, o = s.vs_official || {};
  const items = [
    ["Groundwater accounting", `${fmt(s.water_m3[L_] / 1e9, 2)} bn m³/y pumped for the mapped fields the radar saw farmed, likely an underestimate (MEWA's official estimate for all farms: ${fmt((o.mewa_agri_groundwater_m3 || 0) / 1e9, 2)} bn m³). Field by field from the radar dates of each season; NISAR revisits every 12 days, so the record can be updated as passes arrive.`],
    ["Grid planning", `Irrigation pumping averages ~${fmt(s.summer_pumping_avg_mw[L_])} MW through June–September, on top of the air-conditioning peak; ${fmt(s.elec_kwh[L_] / 1e9, 2)} TWh a year in total.`],
    ["Food security", `${fmt((a.winter_only || 0) + (a.wheat_rotation || 0))} ha of wheat-pattern fields, against GASTAT's 180,455 ha of wheat in 2024: an independent end-of-season check (the wheat classes use summer radar and the late-spring Sentinel-2 brown-down).`],
    ["Fields to check", `${fmt(a.idle || 0)} ha of mapped fields were green in Sentinel-2 this year but not detected by radar in either season. Most are radar misses rather than idle land, so this is a list for ground checks, not yet for land restoration; they get no water in the totals.`],
    ...(S.data.fodder_halt ? [["Fodder policy", `MEWA halts perennial fodder cultivation from ${new Date(S.data.fodder_halt.effective + "T00:00:00Z").toLocaleDateString("en-GB", { timeZone: "UTC", day: "numeric", month: "long", year: "numeric" })} in ${S.data.fodder_halt.regions.map(r => r === "Eastern" ? "the Eastern Province" : r).join(", ")} (<a href="${S.data.fodder_halt.url}">MEWA announcement</a>). In those regions the radar's 2025/26 record holds ${fmt(S.data.official.filter(r => S.data.fodder_halt.regions.includes(r.region)).reduce((t, r) => t + (r.radar_year_round_ha || 0), 0))} ha of year-round fields, a field-level baseline before the rule (plus ${fmt(S.data.official.filter(r => S.data.fodder_halt.regions.includes(r.region)).reduce((t, r) => t + (r.radar_partly_seen_ha || 0), 0))} ha the radar saw in one season only, which it cannot split). NISAR passes from summer 2027 can show which of them switch to seasonal crops.`]] : []),
    ["Waste inventory audit", `MWAN's national waste inventory puts agricultural waste at ${fmt(((S.data.mwan || {}).agri_total_kt || 0) / 1e3, 2)} Mt a year (${(S.data.mwan || {}).agri_total_year}), graded low confidence because it rests on international benchmark factors. The radar gives a partial, field-level check: ${fmt(s.straw_t_dry[L_] / 1e3)} kt of baled wheat straw and ${fmt(s.fronds_t_dry[L_] / 1e3)} kt of palm fronds a year (dry) on the fields it maps, against MWAN's ${fmt(((S.data.mwan || {}).streams_2024_mt || {}).grain_residue, 2)} Mt of grain residue and ${fmt(((S.data.mwan || {}).streams_2024_mt || {}).date_palm, 2)} Mt of date palm residue (stream by stream in the Biochar tab).`],
    ["Carbon removal deployment", `Where biochar plants can be filled, how big, which outlet, and how much CO₂ they remove after transport (Biochar tab).`],
    ["Next", "Loan and insurance checks that a field was planted; carbon-credit feedstock verification; ground sinking from radar interferometry; alerts when a circle switches on or off."],
  ];
  $("lens").innerHTML = `<p class="lead">One radar record, many decisions:</p>` + items.map(([h, t]) => `<div class="plant"><b>${h}</b><br>${t}</div>`).join("");
}

function renderMethod() {
  const P = S.data.params;
  const rows = Object.entries(P).filter(([k, v]) => !k.startsWith("_") && v && v.source && !v.values).map(([k, v]) => {
    const show = (x) => Array.isArray(x) ? x.map(y => fmt(y / 1000)).join("/") + " kt" : fmt(x, 3);
    return `<tr><td>${k.replaceAll("_", " ")}</td><td class="num">${show(v.low)}</td><td class="num">${show(v.central)}</td><td class="num">${show(v.high)}</td><td>${v.source}</td></tr>`; }).join("");
  const lift = Object.entries(S.data.lift).filter(([k, v]) => typeof v === "object").map(([k, v]) => `<tr><td>${k}</td><td class="num">${v.low}</td><td class="num">${v.central}</td><td class="num">${v.high}</td><td>${v.source}</td></tr>`).join("");
  $("meth").innerHTML = `<ol class="steps">
    <li><b>Regions</b>: clusters of at least 1,500 ha of cropland and tree cover in ESA WorldCover 2021, cut into ${S.data.regions.length} boxes; the 60 largest, processed here, hold ~88% of the cropland and tree cover in those boxes.</li>
    <li><b>Fields</b> from ESA Sentinel-2: NDVI above ${fmt((S.data.field_mask || {}).green ?? 0.4, 2)} (surface reflectance, offset-corrected) in a seasonal maximum of up to 8 scenes per tile and orbit, patches of 3 ha or more on a 40 m grid${(S.data.field_mask || {}).lc_filter && S.data.field_mask.lc_filter !== "none" ? `; patches whose ESA WorldCover majority is shrubland or grassland are dropped${S.data.field_mask.lc_filter === "natural_nonpivot" ? " unless they are centre pivots of 10 ha or more" : ""}` : ""} (the 20 m Qassim deep dive predates the offset correction).</li>
    <li><b>NISAR</b> L-band HV backscatter on the best-covering track: up to 3 winter and 4 summer dates; some regions have summer passes only. A field is farmed in a season when its peak, measured above the same scene's bare-desert median, beats a desert-patch tail threshold: median + 3 × (median − 16th percentile) of field-sized desert patches' seasonal peaks, which about 13–14% of bare-desert patches still exceed. A benchmark on these data shows the skill comes from normalising each scene to its own desert: pooled over quality-checked regions and at the same desert false-alarm rate, it beats one national raw-backscatter threshold (benchmark-set kappa 0.24 vs 0.17 in winter, 0.44 vs 0.27 in summer; the winter advantage holds at every threshold, the summer one at this operating point), and it beats NISAR-style temporal variability at every cut.</li>
    <li><b>Palm groves</b>: fields with at least 30% WorldCover tree cover, radar-active in every season observed.</li>
    <li><b>Manure and litter</b>: GASTAT 2024 poultry production and herd counts × per-animal factors, spread by the FAO GLW4 livestock pattern (modelled, not radar).</li>
    <li><b>Water, energy</b>: area × irrigation depth ÷ pivot efficiency; lift by region.</li>
    <li><b>Siting</b>: greedy placement of plants that remove the most CO₂ net of transport. Removal is credited with the Puro.earth 2025 soil persistence model for farmland and for cement alike (H/C<sub>org</sub> below 0.70 required); char goes to farmland or to the nearest operating cement plant, whichever is the shorter haul.</li></ol>
    <h3>Depth to groundwater (m)</h3><table><tr><th>Area</th><th class="num">Low</th><th class="num">Central</th><th class="num">High</th><th>Source</th></tr>${lift}</table>
    <h3>Factors</h3><table><tr><th>Factor</th><th class="num">Low</th><th class="num">Central</th><th class="num">High</th><th>Source</th></tr>${rows}</table>
    <p class="note">Data: NASA-ISRO NISAR (ASF DAAC), ESA Sentinel-2 and WorldCover (Microsoft Planetary Computer), FAO GLW4 2020, SFI cement database with OpenStreetMap and Climate TRACE corrections, GASTAT and MEWA 2024 statistics, geoBoundaries. AI tools (Claude) assisted with code and text.</p>`;
}

init().catch(e => document.body.insertAdjacentHTML("beforeend", `<p style="padding:16px">Could not load data: ${e.message}</p>`));
