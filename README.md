# Circle to Char

**NISAR radar reads Qassim's farm circles: which are farmed, what they cost in water and energy, and where their straw should become biochar.**

NASA Space Apps Challenge 2026 · Challenge: *Dancing with the SARs*

## What it does

Saudi Arabia's national waste inventory estimates agricultural residues from crop area × benchmark factors and grades the result *low confidence*. Irrigated farming here also draws on deep, non-renewable aquifers, and much of that pumping is unmetered.

Circle to Char uses NASA-ISRO **NISAR** L-band radar to measure, field by field and every 12 days, which farm fields in the Qassim pivot cluster are actually farmed, and turns that into:

1. **Water and energy**: water pumped, pumping electricity, and CO₂ for grid or diesel pumps.
2. **Biomass**: collectable wheat straw from fields farmed in winter.
3. **Biochar siting**: where a pyrolysis plant should go, how big it can be (5 to 100 kt dry per year), and how much of the carbon it removes is used up by trucking straw in and char out (back to the fields, or to a cement plant).

Every number is shown as a low, central and high range, with its published source.

## How it works

| Step | Data | Method |
|---|---|---|
| Fields | ESA Sentinel-2 L2A (Microsoft Planetary Computer) | Seasonal maximum NDVI at 20 m from offset-corrected surface reflectance (up to 30 scenes per tile and orbit); fields = pixels green (NDVI > 0.4) in either season; touching circles split by watershed |
| Is the field farmed? | NISAR L2 GCOV (HH, HV backscatter, 20 m, 17 dates) | Seasonal peak HV per field, measured above the same date's bare-desert median, must beat the desert's own noise (median + 3σ of field-sized desert patches); no Sentinel-2 input |
| Is it being worked or irrigated? | NISAR L2 GUNW (12-day coherence, 80 m) | Coherence drops when the surface changes |
| Is the soil wet? | NISAR L3 SME2 (soil moisture, 200 m) | Per-field mean |
| Check | Sentinel-2 | Radar classes compared with optical greenness over the radar's own dates (area agreement, kappa); Sentinel-2 is never used to tune the radar rule. Over 4,029 fields: kappa 0.39 in winter and 0.56 in summer; radar finds 66% (winter) and 87% (summer) of the area Sentinel-2 sees green, and 95% and 92% of what radar calls farmed is green in Sentinel-2 |
| Water, energy, CO₂ | `model/params.json` | Area × irrigation depth ÷ pivot efficiency; energy = ρ·g·lift·volume ÷ pump efficiency |
| Siting | `model/siting.py` | Greedy facility location: place the plant that fills from the nearest fields with the least transport emissions per tonne of CO₂ removed, repeat. Removal is credited with the Puro.earth 2025 v2 soil persistence model (from the char's H/C_org and soil temperature) for char on fields and in cement alike (rule 6.2.4); retention in cement is reported, not credited |

## Run it

```bash
.venv/bin/python scripts/s2_fields.py                      # fields from Sentinel-2
.venv/bin/python scripts/s2_check.py                       # Sentinel-2 over the radar's own dates (the check)
.venv/bin/python scripts/nisar_fetch.py GCOV --track 42 --frame 15   # needs ~/.netrc with NASA Earthdata login
.venv/bin/python scripts/nisar_fetch.py GUNW --track 42 --frame 15
.venv/bin/python scripts/nisar_fetch.py SME2 --track 42 --frame 15
.venv/bin/python scripts/radar_fields.py                   # per-field radar series + validation
.venv/bin/python model/supply.py --source radar            # water, energy, straw
.venv/bin/python model/siting.py central                   # also: low, high
.venv/bin/python scripts/export_web.py                     # data for the web app (docs/ is served by GitHub Pages)
python3 -m http.server 8765 --directory docs
```

Cement plants come from `gee/01_export_saudi_cement.js` (Google Earth Engine).

## Data and sources

- **NASA-ISRO NISAR**: L2 GCOV, L2 GUNW, L3 SME2 (provisional and beta releases), via the Alaska Satellite Facility DAAC.
- **ESA Sentinel-2** L2A, via Microsoft Planetary Computer.
- **Cement plants**: Spatial Finance Initiative, Global Database of Cement Production Assets (CC BY 4.0), via the awesome-gee-community-catalog.
- **Model factors**: see `model/params.json`. Each value lists its source: FAO, IPCC 2006, López Valencia et al. 2020 (HESS), Multsch et al. 2013 (GMD), Al-Salamah & Nassar 2009, UGA Extension, Ember, DESNZ 2026, Sedmihradská et al. 2020, Woolf et al. 2021, Puro.earth 2025.
- **Basemap**: Esri World Imagery.

## Limits (stated openly)

- Water use is estimated from crop needs, not measured at the well. The summer-crop irrigation depth is derived (half the perennial depth), not published.
- Pumping energy is a lower bound: a well-run pump, at the 2006 water level.
- Distances are straight lines.
- Straw yield uses non-Saudi straw-to-grain ratios.
- NISAR has no scenes over Qassim from February to mid-June 2026, and the two seasons come from different processing versions (beta and provisional).

## Use of AI

AI tools (Anthropic Claude) assisted in writing code, data processing scripts and text. All data, sources and results were reviewed by the team.

## Team

Khalid Alhindi, plus team members.
