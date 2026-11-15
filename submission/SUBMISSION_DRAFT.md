# Space Apps 2026 submission draft — Circle to Char

Placeholders in [brackets] are filled once the national run finishes.

## Project name
Circle to Char

## High-level project summary (form field)
Circle to Char is an open web app that uses NASA-ISRO NISAR L-band radar to read the fields of Saudi Arabia's 60 largest farming regions, field by field (they hold ~88% of the WorldCover cropland and tree cover in all 114 region boxes; the radar passed its quality check in 42 of them, and the 42 with radar results hold ~64% of it); NISAR passes every 12 days, so the record can be refreshed as passes arrive. It answers three questions that are estimated today, not measured: which fields are actually farmed, how much groundwater and pumping energy they use, and how much organic residue they leave, and where biochar plants could be built to turn residue into durable carbon removal (fed mostly by modelled manure; poultry litter is not credited, and radar-measured straw and fronds are a small share, stated in the app). The radar rule calibrates itself against the bare desert in every scene, so it scales nationally with no training labels; field outlines come from ESA Sentinel-2, and we check the radar against Sentinel-2 (a consistency check, since Sentinel-2 also outlines the fields) and against official 2024 statistics. It matters because Saudi farming draws on non-renewable aquifers, much pumping is unmetered, and the national waste inventory grades agricultural residue figures as low confidence.

## Link to project demo
[YouTube / Google Slides link: 30-second video or 7 slides]

## Link to final project
https://khalidmelo.github.io/circle-to-char/ (start here: headline results, with links to every page); national results: https://khalidmelo.github.io/circle-to-char/national.html; what-if scenarios: https://khalidmelo.github.io/circle-to-char/scenarios.html; Qassim deep dive: https://khalidmelo.github.io/circle-to-char/qassim.html; code: https://github.com/khalidmelo/circle-to-char

## Detailed project description (form field)

**What it does.** For each farming region (found from ESA WorldCover), the app maps fields from Sentinel-2 and reads NISAR backscatter on each one. A field counts as farmed in a season when its HV backscatter (L-band crop canopy) stands above a threshold set from the bare desert on the same dates. From that record it estimates:
- Farmed area by season: [N] ha in winter, [N] ha in summer, across the [N] regions with radar results (~64% of the WorldCover cropland and tree cover in the region boxes; the 60 processed hold ~88%). Moving the radar threshold ±1 dB in every region gives a classification range, shown in the app next to the factor range. A further [N] ha of mapped fields (green in Sentinel-2) were not detected by radar, mostly radar misses rather than idle land, and on [N] ha the radar had a usable look in one season only.
- Irrigation water pumped: [N] billion m³/yr (range [lo–hi]), likely an underestimate (undetected fields get no water), against MEWA's official 11.56 billion m³ for all farms (2024).
- Pumping electricity [N] TWh/yr, an average [N] MW added to the June–September grid peak, and [N] Mt CO₂/yr; the pumping head includes drawdown and centre-pivot pressure on top of the static depth to water, and the estimate is likely a lower bound.
- Organic residues: wheat straw [N] kt (radar), palm fronds [N] kt (radar + WorldCover), and modelled poultry litter [N] kt and manure [N] kt (GASTAT 2024 poultry production and herds, spread by FAO GLW4); MWAN's national inventory, graded low confidence, is compared stream by stream in the app.
- Biochar siting: [N] plants of 50 kt/yr can be filled within 100 km, removing [N] Mt CO₂/yr net of transport (a technical potential: production and embodied emissions and leakage are not subtracted); poultry litter is not credited, because its char fails Puro's H/C_org eligibility gate on the organic-carbon basis (the app shows it only as an uncredited upside), and much of the manure comes from livestock outside the 60 processed regions (the app also shows the inside-only case); removal is credited with the Puro.earth 2025 soil model for farmland and cement alike (rule 6.2.4), so [N] send char to one of the 20 operating cement plants only where that is the shorter haul; soil absorption is not limited (gross figure), with constrained cases on a scenarios page. [N]% of that feed is radar-measured (straw, fronds); radar residues alone would fill [N] plants.

**How it works.**
1. Regions: clusters of cropland and tree cover in ESA WorldCover 2021.
2. Fields: Sentinel-2 seasonal maximum NDVI above 0.4 (offset-corrected surface reflectance, up to 8 scenes per tile and orbit), green patches of about 3 ha or more on a 40 m grid (touching fields are split apart, so some pieces are smaller), dropping non-pivot patches that ESA WorldCover classes as shrubland or grassland (rain-greened natural vegetation in the southwest) (20 m in the Qassim deep dive); a spring check (wheat harvested in April–May) separates wheat rotations from perennial fodder.
3. Radar: NISAR L2 GCOV HV backscatter, up to 3 winter and 4 summer dates per region on the best-covering track (some regions have summer passes only). Threshold: a desert-patch tail threshold per region and season, median + 3 × (median − 16th percentile) of field-sized desert patches' peaks above each scene's own desert median (about 13–14% of bare-desert patches exceed it). Normalising each scene to its own desert is what gives the skill: pooled over quality-checked regions at the same desert false-alarm rate, it beats one national raw-backscatter threshold (kappa 0.24 vs 0.17 in winter, 0.44 vs 0.27 in summer; the summer advantage holds at this operating point, the winter one at every threshold) and NISAR-style temporal variability at every cut (also cancels the beta/provisional calibration step).
4. Check: against Sentinel-2 (winter over the radar's own dates, summer June–October), pooled over regions: kappa [N] winter / [N] summer; radar finds [N]% (winter) / [N]% (summer) of the area Sentinel-2 sees green, and [N]% / [N]% of what radar calls farmed is green in Sentinel-2. In the 20 m Qassim deep dive (4,029 fields, Sentinel-2 over the radar's own dates in both seasons): kappa 0.39 winter / 0.56 summer; radar finds 66% / 87% of the area Sentinel-2 sees green, and 95% / 92% of what radar calls farmed is green in Sentinel-2. We also tested 12-day coherence and NISAR soil moisture: coherence does not separate fields in sand deserts (sand itself decorrelates), and soil moisture adds area but false alarms. That is a useful finding for NISAR users in arid regions.
5. Water and energy: area × irrigation depth (published depths for winter and year-round fields; a derived depth, half the perennial, for summer crops) ÷ pivot efficiency; pumping head = regional static depth to groundwater + drawdown + pivot pressure (centre pivots only); grid and diesel emission factors. The Arabian Shield regions get water but no pumping energy.
6. Biochar: feedstock-specific char yield, organic carbon and H/C_org; persistence from the Puro.earth 2025 v2 soil model at 30 °C (33 °C and 25 °C in the all-low and all-high corners), with the H/C_org < 0.70 eligibility gate (poultry litter fails it on the organic-carbon basis, so it is not credited); greedy plant siting maximising net CO₂ removed after truck emissions, char going to farmland or the nearest operating cement plant, credited alike. The result is a technical potential.
Every factor has a low/central/high range and either a published source or a labelled assumption, shown in the app; a factor range moves every factor to its bound at once and is not a probability interval. Farmed area, water and energy also have a classification range (radar threshold ±1 dB in every region).

**Benefits.** One radar record, many decisions: groundwater accounting for the agriculture and water ministry, including a field-level baseline for MEWA's halt on perennial fodder from 16 November 2026; summer peak planning for the grid; an independent end-of-season check of wheat area for food security; a list of fields to check on the ground; a field-level check of crop residues in the national waste inventory; and a map of where biochar plants could be filled (most of that feed is modelled manure, stated in the app). The radar rule needs no training labels.

**What we hope to achieve.** An operational, every-12-days national service with official partners (MEWA, MWAN, GASTAT), extended to subsidence (radar interferometry), loan and insurance verification, and carbon-credit feedstock verification.

**Tools.** Python (h5py, rasterio, numpy, scipy, scikit-image, pandas, shapely, earthaccess, pystac-client), Leaflet and Chart.js, GitHub Pages.

**Limits, stated openly.** NISAR has no Saudi scenes from February to mid-June 2026, so winter area is a lower bound; fields the radar did not detect, and seasons it did not observe, get no water, so water and energy are likely underestimates; the summer-crop irrigation depth is a derived assumption (half the perennial depth); water is estimated from crop needs, not metered; pumping energy uses older depth-to-water measurements, and water levels have fallen since, so it is likely a lower bound (the head does include drawdown and pivot pressure); the Arabian Shield regions get no pumping energy; manure and litter are modelled, not measured (GASTAT 2024 production and herds with US and IPCC per-animal factors); camels are excluded; distances are straight lines times a road-circuity factor; poultry-litter char is not credited: its H/C is 0.69 on total carbon but 0.71–0.73 on the organic-carbon basis Puro requires, against a strict < 0.70 gate (rule 3.5.1); manure char's H/C_org (0.56 central) is assumed from measured cattle-manure chars, since sheep and goat manure chars are unmeasured; in 18 of the 60 processed boxes (~24% of the WorldCover cropland and tree cover in the region boxes, mostly the southwest and Riyadh) the radar failed its quality check, so their mapped fields are unclassified; 54 smaller boxes (~12%) are not processed, and farming clusters too small to box are not counted.

## Use of Super Intelligence (form field)
Yes. We used Anthropic's Claude (an AI assistant) to brainstorm and refine ideas, write and debug the Python and JavaScript code, search for and summarise published factors (each checked against the cited source), and draft text. All data processing runs on public NASA, ESA and FAO data; results, sources and claims were reviewed by the team. AI-assisted code and text are acknowledged in the README and app.

## NASA data (form field)
- NISAR L2 GCOV (geocoded backscatter, HH/HV, 20 m) — NASA ASF DAAC, beta and provisional releases, Oct 2025 – Oct 2026
- NISAR L2 GUNW (12-day coherence) and L3 SME2 (soil moisture, 200 m) — NASA ASF DAAC (tested witnesses)
- NASA Earthdata Search / ASF Vertex and the NISAR Data User Guide

## Space agency partner data and other references (form field)
- ESA (partner): Sentinel-2 L2A and ESA WorldCover 2021 (via Microsoft Planetary Computer)
- ISRO (partner): co-builder of NISAR (S-band not used)
- FAO Gridded Livestock of the World GLW4 2020 (CC BY 4.0)
- Spatial Finance Initiative, Global Database of Cement Production Assets (CC BY 4.0)
- GASTAT Agricultural and Livestock Statistics 2024; MEWA Statistical Book 2024; geoBoundaries (Saudi ADM1)
- Factor sources: see model/params.json and data/national/official_2024.json (IPCC 2019, FAO, USDA NRCS, DESNZ 2026, Ember, Puro.earth 2025, Woolf et al. 2021, Usman et al. 2015, Song & Guo 2012, Tsai & Chang 2021, Cantrell et al. 2012, Sedmihradská et al. 2020, López Valencia et al. 2020, ESCWA-BGR 2013 and others)
- Basemap: Esri World Imagery

## 7-slide demo outline
1. **Title**: Circle to Char — team names, challenge "Dancing with the SARs".
2. **The problem**: Saudi farming pumps non-renewable groundwater, much of it unmetered; residues are estimated from benchmarks (MWAN: low confidence). Visual: NISAR image of Qassim circles.
3. **The idea**: one radar record of the fields in the 60 largest farming regions (NISAR L-band, revisiting every 12 days); radar results in 42 of them (those 42 hold ~64% of the farmland). Visual: bright vs dark circles, HV time series.
4. **How well it works**: desert-calibrated rule; kappa, recall and precision against Sentinel-2 per season, and the gaps to official statistics with their causes (winter dates before the canopy, partial coverage, radar classes are not crop types).
5. **What it reveals nationally**: farmed area, water, pumping energy and summer peak, residues (map + 4 numbers).
6. **Where biochar plants go**: national plant map with cement outlets; net CO₂ removed, a technical potential (poultry litter not credited).
7. **What's next**: operational service for MEWA/MWAN, loan/insurance and carbon-credit verification, subsidence; to be tested on other L-band SAR.
