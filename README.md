# SkyMeter

**An open, field-by-field record of what Saudi farms grow each season and an estimate of the water they use, from NASA and ESA satellites.**

NASA Space Apps Challenge 2026, challenge *Dancing with the SARs*.

## Version 2 (this branch, `skymeter-v2`)

The live site (https://khalidmelo.github.io/circle-to-char/) shows the version submitted to the challenge and stays unchanged during judging. This branch reworks the method. Satellites already see every field, but meters cover under 2% of farm wells and no public per-field water record exists, so v2 puts its effort where the gap is:

- **Crop type per field** (60,132 fields, 738,163 ha in 60 farming boxes): crop cycles from the Landsat 8/9 NDVI time series at 40 m (Aug 2025 to Nov 2026), with NISAR L-band radar as independent evidence of canopy in winter and summer where its quality check passed (42 boxes).
- **Perennial-fodder baseline** for MEWA's halt of perennial green fodder in six sedimentary-shelf regions from 16 November 2026: which fields grew it in 2025/26 and the water they used.
- **Water use from heat**: Landsat surface temperature, corrected for emissivity, elevation and desert blending at field edges, in a two-anchor energy-balance index checked against SSEBop's physics, scaled by FAO-56 reference ET from NASA POWER. Reported as groundwater on the sedimentary shelf, irrigation water on the Arabian Shield (source not determined) and net consumptive use, each with a low/high range; the v1 area x benchmark-depth method stays as a cross-check, with MEWA's figures for context.
- **Aquifer outlook**: a NISAR InSAR pilot over Qassim measures the noise floor and how long a record must run before pumping-driven ground sinking (5-12 mm a year in published studies) becomes detectable. It is not detectable yet, and irrigated fields show false movement from soil moisture.
- **Residues and biochar scenarios**: straw from winter-cereal cycles and fronds from GASTAT's palm count; biochar as a technical-potential range by collected share. No plant siting.
- **Checks**: Landsat 8 vs Landsat 9 split halves, bootstrap stability, Sentinel-2's spring flag, NISAR agreement, GASTAT 2024 regional areas, and a blind visual check of a stratified test sample: 226 fields read from their raw Landsat NDVI looks and six Sentinel-2 images by AI vision models working from a written guide and never shown the mapped labels (a random 20% read twice). Overall agreement 76% (95% interval 68-83%), 84% on broad groups; it is visual interpretation, not field visits, and the interpreters saw the same Landsat record as the map, so it is an upper bound. The crop rules were tuned on a separate 224-field calibration sample before the test sample was drawn.

Run order: `scripts/run_v2.sh`. New code: `model/eto_power.py`, `scripts/landsat_c2.py`, `scripts/landsat_fields.py`, `model/crop_types.py`, `model/et_fields.py`, `model/residues_v2.py`, `scripts/gunw_fetch.py`, `scripts/insar_qassim.py`, `scripts/v2_check_cards.py`, `scripts/v2_check_score.py`, `scripts/export_v2.py`. The v1 modules are not changed; v2 reads their published field table (`data/national/fields_national.csv`). Pages: `index.html`, `national.html`, `aquifer.html` (new) read `docs/data/v2/`; `qassim.html` keeps the v1 radar deep dive. Additional data for v2: Landsat 8/9 Collection 2 Level-2 (USGS/NASA, via Microsoft Planetary Computer), NASA POWER, Copernicus DEM GLO-90.

## Version 1 (submitted)

The sections below describe the submitted version.

**NISAR radar reads Saudi Arabia's farm fields, field by field: which are farmed each season, what they cost in water and pumping energy, what residue they leave, and where biochar plants could turn it into stored carbon.**

## What it does

Saudi farms pump groundwater from deep aquifers that do not refill, and much of that pumping is unmetered. The national waste inventory estimates agricultural residues from crop area × benchmark factors and grades the result *low confidence*. NASA-ISRO **NISAR** L-band radar passes every 12 days through cloud and dust, so it can check which fields are actually farmed.

The site has a landing page and three pages:

- **Landing** (`index.html`): the headline results with their ranges and caveats, and links to the three pages.
- **National results** (`national.html`, the main result): the 60 largest of 114 farming-region boxes found in ESA WorldCover, which hold ~88% of the WorldCover cropland and tree cover in all 114 boxes. The radar passed its quality check in 42 of the 60, and the 42 with radar results hold ~64% of that farmland; the other 18 give no radar result. For the mapped fields: farmed area by season, irrigation water, pumping electricity and summer load, wheat straw and palm fronds, modelled manure and poultry litter, and biochar plant sites. Checked against Sentinel-2 and 2024 official statistics (GASTAT, MEWA, MWAN).
- **What-if scenarios** (`scenarios.html`): what-ifs on the national record: the radar-verified floor and data-rule uncertainty, a field-level baseline for MEWA's perennial-fodder halt, pivot retrofits, and biochar when farmland and cement take only limited char.
- **Qassim deep dive** (`qassim.html`): one pivot cluster at 20 m with more radar dates, run separately, so its figures for the same fields differ from the national page. Every field's radar record, and three radar signals tested.

Water, energy, residue and biochar figures carry a low/central/high factor range; farmed area, water and energy also carry a classification range (radar threshold ±1 dB) and a radar + Sentinel-2 figure. Each factor lists its source or is labelled as an assumption.

## How it works

| Step | Data | Method |
|---|---|---|
| Regions | ESA WorldCover 2021 | Cropland and tree-cover clusters cut into boxes of at most 0.6°; the 60 largest are processed |
| Fields | ESA Sentinel-2 L2A (Microsoft Planetary Computer) | Seasonal max NDVI > 0.4; patches of about 3 ha+ on a 40 m grid (20 m in the deep dive), touching fields split; non-pivot shrub or grass patches, mangrove, wetland and water dropped |
| Is the field farmed? | NISAR L2 GCOV HV backscatter | Seasonal peak HV above the same date's desert median must beat a per-region desert-patch threshold, median + 3 × (median − p16), which ~13–14% of desert patches still exceed (15–20% in the deep dive); no Sentinel-2 input; a too-bright desert or too-high threshold fails that season's quality check |
| Wheat or fodder, palms | Sentinel-2, WorldCover | Farmed in winter and summer and brown in late spring: wheat rotation; still green: year-round (perennial fodder). Palms: WorldCover tree cover, radar-active in every season observed |
| Tested, not used | NISAR L2 GUNW 12-day coherence (20 m wrapped-interferogram layer), L3 SME2 soil moisture (200 m) | Tested against Sentinel-2 in the deep dive: coherence does not separate fields in sand desert; soil moisture adds false alarms |
| Checks | Sentinel-2; neighbouring boxes | Kappa, recall and precision against Sentinel-2 greenness (consistency checks, not ground truth: Sentinel-2 also outlines the fields); fields mapped by two boxes test reproducibility |
| Water, energy, CO₂ | `model/params.json`, `data/national/official_2024.json` | Area × irrigation depth ÷ pivot efficiency (summer-crop depth derived: half the perennial); electricity = ρ × g × head × volume ÷ pump efficiency, head = depth to water + drawdown + pivot pressure (pivots only); Arabian Shield regions get water but no energy |
| Residues | Radar fields; GASTAT 2024, FAO GLW4 | Straw and fronds from the mapped fields only; manure and poultry litter modelled for the whole Kingdom from herd and poultry statistics |
| Biochar siting | `model/national_siting.py`, `model/siting.py` | Greedy facility location: each plant draws the nearest feed (within 100 km nationally); nationally the plant with the largest net removal after truck emissions is placed first, in the deep dive the one with the least transport emissions per tonne removed. Char to farmland or cement, both credited with the Puro.earth 2025 v2 soil persistence model (rule 6.2.4); poultry-litter char fails H/C_org < 0.70 on the organic-carbon basis, so litter is not credited (an upside only); a technical potential: only truck emissions are subtracted |
| Scenarios | `model/national_scenarios.py` | Re-runs the national engine with changed data rules, policies and outlet limits |

## Run it

```bash
# National
.venv/bin/python scripts/national_regions.py               # farming regions from WorldCover
scripts/run_national.sh 60 4                               # fields, radar and spring check per region (needs ~/.netrc with NASA Earthdata login)
.venv/bin/python model/national_supply.py                  # national field table, totals, ranges, radar + Sentinel-2 tier
.venv/bin/python scripts/osm_places.py                     # one-off: OpenStreetMap settlements (committed CSV)
.venv/bin/python model/manure.py                           # collectable manure and litter, placed where animals are housed
.venv/bin/python scripts/overlap_agreement.py              # reproducibility between neighbouring boxes
.venv/bin/python model/national_siting.py                  # biochar siting, all levels
.venv/bin/python model/national_scenarios.py               # scenarios
.venv/bin/python scripts/export_scenarios.py               # data for scenarios.html

# Qassim deep dive
.venv/bin/python scripts/s2_fields.py                      # fields from Sentinel-2
.venv/bin/python scripts/s2_check.py                       # Sentinel-2 over the radar's own dates (the check)
.venv/bin/python scripts/nisar_fetch.py GCOV --track 42 --frame 15   # also GUNW and SME2 for the tested signals
.venv/bin/python scripts/radar_fields.py                   # per-field radar series + validation
.venv/bin/python scripts/transfer_national_flags.py        # spring check and tree cover from the national run
.venv/bin/python model/supply.py --source radar            # water, energy, straw, fronds
.venv/bin/python model/siting.py central                   # also: low, high
.venv/bin/python scripts/export_web.py --skip-overlays     # data for qassim.html (drop the flag to rebuild the map overlays)

# Last: its checks compare the siting with the national summary
.venv/bin/python scripts/export_national.py                # data for national.html and the landing page

python3 -m http.server 8765 --directory docs              # docs/ is served by GitHub Pages
```

Cement plants come from `gee/01_export_saudi_cement.js` (Google Earth Engine).

## Data, sources and licences

- **NASA-ISRO NISAR**: L2 GCOV, L2 GUNW, L3 SME2 (provisional and beta releases), via the Alaska Satellite Facility DAAC; NASA open data, no restrictions on use.
- **ESA Sentinel-2** L2A (Copernicus free and open data licence) and **ESA WorldCover** 2021 (CC BY 4.0), via Microsoft Planetary Computer.
- **Statistics**: GASTAT Agricultural and Livestock Statistics 2024, MEWA Statistical Book 2024, MWAN national waste inventory, KAPSARC Discussion Paper DP64 (public publications, cited).
- **Livestock**: GASTAT 2024 regional herds; FAO Gridded Livestock of the World GLW4 2020 (CC BY 4.0) for the pattern within a region; settlements from OpenStreetMap (© OpenStreetMap contributors, ODbL).
- **Cement plants**: Spatial Finance Initiative, Global Database of Cement Production Assets (CC BY 4.0), with OpenStreetMap (ODbL) and Climate TRACE (CC BY 4.0) corrections.
- **Model factors**: `model/params.json` and `data/national/official_2024.json`; each value lists its source (FAO, IPCC, USDA NRCS, López Valencia et al. 2020, Multsch et al. 2013, ESCWA-BGR 2013, UGA Extension, Ember, DESNZ 2026, Woolf et al. 2021, Puro.earth 2025 and others).
- **Boundaries and basemap**: geoBoundaries (CC BY 4.0) and Natural Earth (public domain); Esri World Imagery basemap tiles (Esri terms of use).
- **Libraries**: Leaflet (BSD-2-Clause), Chart.js (MIT); Python: numpy, pandas, rasterio, shapely, scikit-image and others under their own open licences.
- **Demo video music**: "Sleeping Alone" by Matthew C. Wright (https://www.matthewcwright.com/), CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/), via chosic.com.
- **This project's code and original content**: Apache License 2.0, see `LICENSE`.

## Limits (stated openly)

- Radar results cover 42 of the 60 processed regions; small farming clusters are not boxed. NISAR has no Saudi scenes from February to mid-June 2026, so winter area is a lower bound.
- Water is estimated from crop needs, not metered, and is likely an underestimate: undetected fields and unobserved seasons get none. The summer-crop irrigation depth is derived, not published.
- Pumping energy is likely a lower bound: a well-run pump, older depth-to-water measurements, and no energy for the Arabian Shield regions.
- Manure and litter are modelled, not measured: regional herds are placed where animals are housed (cattle on each region's fodder fields, other animals near farms and settlements), not at known barns; camels are excluded. Biochar removal is a technical potential, and distances are straight lines scaled by a road factor.
- The deep dive and the national page classify the same Qassim fields separately, so their figures differ.

## Acknowledgements

Built with AI-assisted coding and writing tools; the team checked the data, sources and results.

## Team

Khalid Alhindi, plus team members.
