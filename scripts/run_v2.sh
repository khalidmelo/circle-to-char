#!/bin/sh
# SkyMeter v2 pipeline, in order. Run from the repository root (the main checkout holds .venv and the large data;
# in a worktree, link data/regions, data/glw, data/landsat and data/nisar from it first).
# v1 modules (national_supply, siting, scenarios, export_national, ...) are not run or changed: v2 reads their
# published field table, data/national/fields_national.csv, and writes its own outputs.
set -e
PY=.venv/bin/python

$PY model/eto_power.py all                 # NASA POWER daily weather -> FAO-56 reference ET per box
$PY scripts/landsat_c2.py all --threads 8  # Landsat 8/9 C2 L2 per overpass, cached on 40 m and 120 m grids (~11 GB)
$PY scripts/landsat_fields.py all          # per-field NDVI series, corrected surface temperature, hot/cold anchors
$PY model/crop_types.py all                # crop type per field (Landsat NDVI cycles; NISAR radar as evidence)
$PY model/et_fields.py all                 # heat-based water use per field, net and gross, with low/high
$PY model/residues_v2.py                   # straw and fronds; biochar as technical-potential scenarios

# NISAR InSAR pilot over Qassim (needs ~/.netrc with an Earthdata login)
$PY scripts/gunw_fetch.py                  # extra GUNW layers for the 14 pairs on track 42 / frame 15
$PY scripts/insar_qassim.py                # noise floor, false movement on irrigated fields, detectability

# Blind check of the crop types (optional; interpretation is done by people or agents reading the cards blind)
#   $PY scripts/v2_check_cards.py <dir> 25 2027 <calibration_sample.csv>
#   ... write <dir>/labels.csv (and labels2.csv for a second interpreter), then:
#   $PY scripts/v2_check_score.py <dir>

$PY scripts/export_v2.py                   # docs/data/v2/ for the site
