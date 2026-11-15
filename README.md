# Circle to Char

**NISAR radar reads Saudi Arabia's farm fields, field by field: which are farmed each season, what they cost in water and pumping energy, what residue they leave, and where biochar plants could turn it into stored carbon.**

**Live site:** https://khalidmelo.github.io/circle-to-char/ (start here)

NASA Space Apps Challenge 2026 · Challenge: *Dancing with the SARs*

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
| Water, energy, CO₂ | `model/params.json`, `data/national/official_2024.json` | Area × irrigation depth ÷ pivot efficiency (summer-crop depth derived: half the perennial); electricity = ρ·g·head·volume ÷ pump efficiency, head = depth to water + drawdown + pivot pressure (pivots only); Arabian Shield regions get water but no energy |
| Residues | Radar fields; GASTAT 2024, FAO GLW4 | Straw and fronds from the mapped fields only; manure and poultry litter modelled for the whole Kingdom from herd and poultry statistics |
| Biochar siting | `model/national_siting.py`, `model/siting.py` | Greedy facility location: each plant draws the nearest feed (within 100 km nationally); nationally the plant with the largest net removal after truck emissions is placed first, in the deep dive the one with the least transport emissions per tonne removed. Char to farmland or cement, both credited with the Puro.earth 2025 v2 soil persistence model (rule 6.2.4); poultry-litter char fails H/C_org < 0.70 on the organic-carbon basis, so litter is not credited (an upside only); a technical potential: only truck emissions are subtracted |
| Scenarios | `model/national_scenarios.py` | Re-runs the national engine with changed data rules, policies and outlet limits |

## Run it

```bash
# National
.venv/bin/python scripts/national_regions.py               # farming regions from WorldCover
scripts/run_national.sh 60 4                               # fields, radar and spring check per region (needs ~/.netrc with NASA Earthdata login)
.venv/bin/python model/manure.py                           # modelled manure and litter (FAO GLW4 + GASTAT)
.venv/bin/python model/national_supply.py                  # national field table, totals, ranges, radar + Sentinel-2 tier
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

## Data and sources

- **NASA-ISRO NISAR**: L2 GCOV, L2 GUNW, L3 SME2 (provisional and beta releases), via the Alaska Satellite Facility DAAC.
- **ESA Sentinel-2** L2A and **ESA WorldCover** 2021, via Microsoft Planetary Computer.
- **Statistics**: GASTAT Agricultural and Livestock Statistics 2024, MEWA Statistical Book 2024, MWAN national waste inventory.
- **Livestock pattern**: FAO Gridded Livestock of the World GLW4 2020 (CC BY 4.0).
- **Cement plants**: Spatial Finance Initiative, Global Database of Cement Production Assets (CC BY 4.0), with OpenStreetMap and Climate TRACE corrections.
- **Model factors**: `model/params.json` and `data/national/official_2024.json`; each value lists its source (FAO, IPCC, USDA NRCS, López Valencia et al. 2020, Multsch et al. 2013, ESCWA-BGR 2013, UGA Extension, Ember, DESNZ 2026, Woolf et al. 2021, Puro.earth 2025 and others).
- **Boundaries and basemap**: geoBoundaries; Esri World Imagery.

## Limits (stated openly)

- Radar results cover 42 of the 60 processed regions; small farming clusters are not boxed. NISAR has no Saudi scenes from February to mid-June 2026, so winter area is a lower bound.
- Water is estimated from crop needs, not metered, and is likely an underestimate: undetected fields and unobserved seasons get none. The summer-crop irrigation depth is derived, not published.
- Pumping energy is likely a lower bound: a well-run pump, older depth-to-water measurements, and no energy for the Arabian Shield regions.
- Manure and litter are modelled, not measured; camels are excluded. Biochar removal is a technical potential, and distances are straight lines scaled by a road factor.
- The deep dive and the national page classify the same Qassim fields separately, so their figures differ.

## Use of AI

AI tools (Anthropic Claude) assisted in writing code, data processing scripts and text. All data, sources and results were reviewed by the team.

## Team

Khalid Alhindi, plus team members.
