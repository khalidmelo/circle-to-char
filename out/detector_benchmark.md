# Audit note (read first)

The audit was run on the previous field mask (V0). Rerun on field mask V2 (this report), the pooled QC results
move by at most 0.002 kappa (D0 0.239 / 0.444 vs D1 0.166 / 0.265; year D0 0.305 vs CV at matched false alarms 0.184),
so its conclusions stand.

An independent audit re-ran this benchmark and recomputed every headline value from the pipeline's own data without the
benchmark's functions; all numbers reproduce exactly. Its corrected verdict, which supersedes the wording further down:

1. **D0 (desert-anchored rule) beats the raw-dB national threshold D1** in the pooled quality-checked set, at D0's operating
   point: kappa 0.24 vs 0.17 (winter) and 0.44 vs 0.27 (summer), matched on desert false-alarm rate; region-bootstrap 95%
   intervals for the difference 0.01-0.14 and 0.08-0.26. The winter edge holds at every operating point; the summer edge does
   not (threshold-free area AUC ties at 0.828, and D1 scores higher above about 40% desert false alarms).
2. **D0 beats NISAR-style temporal CV (D2) at every cut**: year-level AUC 0.77 vs 0.71; kappa 0.31 (0.34 at its best offset)
   vs 0.25 for the best CV cut. The "best possible CV cut gets 0.17" statement below is wrong: 0.17 is the Youden cut between
   green fields and desert patches, not the kappa-optimal cut.
3. **What beats D1 is calibration to each scene's own desert level, not the per-region p50 + 3(p50 - p16) threshold.** A single
   national threshold on HV-above-desert (not tested below) ties D0 at D0's field specificity (kappa 0.239 / 0.445 vs
   0.239 / 0.444), nearly ties it at matched desert false alarms in winter (0.234 vs 0.240), and has the best AUC of any
   detector (0.678 / 0.874 vs 0.665 / 0.828). The per-region threshold adds skill only under desert-false-alarm matching in
   summer (0.444 vs 0.336); otherwise it mainly evens out desert false alarms across regions. The statement below that "the
   gain comes from fitting the threshold per region, not per-date normalisation" is therefore wrong.
4. "Wherever the radar passes QC" should read "in the pooled QC set": D1 is at least 0.02 kappa better in 18 of 77
   QC-passing region-seasons, D0 in 41.
5. Without the quality check (all 115 region-seasons), matched on desert false-alarm rate, a single raw national threshold
   collapses: on field mask V2 (this report) D1 kappa 0.01 vs D0 0.19 in winter and 0.03 vs 0.30 in summer. The audit (on V0)
   found the winter collapse robust, but the summer comparison depends on the matching rule: matched instead on D0's
   Sentinel-2 field specificity, D1 reached kappa 0.37 vs D0's 0.22 on V0. That alternative matching was not recomputed for V2.
6. D0's own desert false-alarm rate is about 13-14.5% in quality-checked regions, so "3 sigma" is a misleading name for its
   threshold: the desert patch peaks are right-skewed and p50 + 3(p50 - p16) sits inside the bright tail.

---

# Detector benchmark: does the pipeline's radar rule beat simpler ones?

Built by `scripts/detector_benchmark.py` from stored data only (60 regions; runtime 68 s with 6 worker processes, 64 s of it reading and reprojecting 405 HV rasters). Reference: Sentinel-2 field greenness per season (winter over the radar's own late-November to January dates, summer June-October). False alarms: share of the pipeline's own 10 ha far-from-field desert patches that a detector calls 'active'.

## Key findings

- At matched desert false-alarm rates D0 beats D1 in both seasons where the radar passes QC: area κ 0.24 vs 0.17 in winter (+0.07) and 0.44 vs 0.27 in summer (+0.17). With 13.0% / 14.5% of desert patches flagged by both, D0 finds 47.7% vs 36.0% (winter) and 67.8% vs 46.2% (summer) of the area Sentinel-2 sees green, at the same precision (74.3/73.1% and 93.2/93.6%). Count-based κ tells the same story (0.29/0.22 winter, 0.47/0.31 summer).
- The gain comes from fitting the threshold per region, not from per-date normalisation: D1r (raw HV, per-region threshold) scores κ 0.24 / 0.41, close to D0's 0.24 / 0.44. Desert medians span 5.2 dB across QC-passing regions in winter and 5.4 dB in summer, so one raw threshold must sit above the brightest desert and misses fields on dark sand. The winter-to-summer step in desert medians (median +0.93 dB over 35 regions; the two seasons come from different NISAR processing versions) is absorbed by any per-season threshold, D1's included; within a season desert medians move by a median 0.52 dB between dates.
- Without the QC filter a national threshold breaks down: matched to D0's false-alarm rate over all region-seasons it rises to -10.9 dB (winter) and -13.5 dB (summer), and D1 falls to κ 0.01 / 0.03 (D0 0.19 / 0.30; recall D0 38.3% / 54.9% vs D1 5.1% / 6.0%). Its desert false alarms sit almost entirely in region-seasons that fail QC (98% in winter, 91% in summer; largest shares R56 17%, R45 15%, R29 12%, R55 8% in winter, R54 16%, R56 10%, R45 8%, R28 8% in summer): bright Shield and limestone desert, and 13 scenes in R10, R15, R29, R55, R56 whose desert median is 4-12 dB above the region's other dates. D0 absorbs both, because it normalises by each scene's own desert.
- D2 (CV) is weaker than D0 at every operating point. CV > 0.5 almost never fires on field-averaged HV (median CV 0.205 on farmed fields, 0.14 on desert): recall 16.1% (QC pool), 8.8% on fields green in both seasons. At D0's year-level false-alarm rate (16.2%) D2 reaches κ 0.18 vs D0 0.31 (recall 56.1% vs 68.5%; fields green in both seasons 52.7% vs 72.2%); even the oracle cut gives κ 0.17. Normalising by the desert median shrinks desert CV (median 0.14 → 0.057) but field CV too (0.205 → 0.157): at matched FAR D2n scores κ 0.19, and its best cut κ 0.22 at a 23.9% false-alarm rate. With 4-7 dates and one canopy per season, the seasonal peak carries the signal and the year's spread does not.
- Where D0 does not win: per region the national cuts are not matched to D0's false-alarm rate. With the QC-fitted cut, D1 has the higher κ in 29 region-seasons, but in 23 of them it also flags more of that region's desert (it trades false alarms for recall where the national cut falls below D0's regional one), and in 13 of the 29 neither detector reaches κ 0.2. At an equal or lower regional false-alarm rate D1 wins only in R12 S (QC fail), R13 W (QC pass), R16 W (QC pass SW), R16 S (QC pass SW), R34 W (QC pass), R50 W (QC pass). Per year, D1 or D2m beats D0 at no extra desert false alarms in R13 D2m, R16 D1 (SW), R34 D1; with more false alarms in R01 D1 (SW), R03 D1 (SW), R06 D1, R08 D1 (DUNE), R17 D1, R18 D1, R24 D2m, R25 tie D2m=D1, R29 D1, R31 D2m, R36 D2m, R41 D1, R43 D1, R46 tie D2m=D1, R50 D2m.
- Dune regions (all pass QC except R59): D0 keeps its lead over D1 (winter κ 0.27 vs 0.23, summer 0.49 vs 0.29), but flags more desert than in other QC-passing regions (14.9% / 17.3% vs 11.6% / 12.8%), probably bright dune faces above a threshold set by the darker sand. Southwest: no detector works. D0 reaches κ 0.14 in winter and 0.00 in summer; the QC-fitted D1 calls 81.4% / 78.5% of the bright rocky desert active (κ 0.05 / 0.23), and Sentinel-2's summer green there is largely rain-fed or natural vegetation.
- D0's own desert false-alarm rate is far above what '3 sigma' suggests: 13.0% (winter) and 14.5% (summer) of far-from-field desert patches pass the threshold in the QC pool. This is not an artefact of fitting on the same patches (held-out half 13.1% / 14.6%; 1.6 km spatial blocks 13.2% / 14.7%) nor of towns or water (WorldCover-bare patches 12.4% / 13.9%): the desert patch peaks are right-skewed (median p50 − p16 = 0.73 / 0.59 dB, p84 − p50 = 1.52 / 1.59 dB), so p50 + 3 × (p50 − p16) sits inside the bright tail. D0+1dB cuts the rate to 8.4% / 9.7% for 8.6 / 17.7 points of recall; D0−1dB raises κ to 0.26 / 0.50 but doubles the rate.

## The detectors

- **D0**: the pipeline rule: seasonal peak of HV minus the same-date desert median, above a threshold fitted per region and season on desert patches (p50 + 3 × (p50 − p16)). **D0±1dB**: same with the threshold moved 1 dB.
- **D1**: seasonal peak of raw HV (no desert normalisation) above one national threshold per season, set so that D1's pooled desert false-alarm rate equals D0's (fitted separately for each pool). **D1r** (diagnostic): raw HV with the pipeline's formula per region and season, which separates 'regional threshold' from 'per-date normalisation'.
- **D2**: temporal coefficient of variation (std/mean) of linear HV over all of a field's dates (≥ 4), crop if CV > 0.5 (NISAR crop-area rule); also at the best possible CV cut (oracle, Youden) and at the cut that matches D0's year-level false-alarm rate. **D2n** (diagnostic): the same on desert-normalised HV. CV is a per-year statistic, so D2 is scored per field against 'green in at least one season', next to D0/D1 'active in at least one season'.

## Region-seasons that pass the radar quality check (77 region-seasons in 42 regions)

D1 national thresholds: winter -20.98 dB raw HV, summer -20.11 dB raw HV.

| Season | Detector | Recall (area) | Precision (area) | Specificity (area) | κ (area) | Recall (count) | Precision (count) | κ (count) | Desert FAR % | Held-out FAR % |
|---|---|---|---|---|---|---|---|---|---|---|
| winter | D0 | 47.7 | 74.3 | 77.6 | 0.24 | 53.2 | 75.8 | 0.29 | 13.03 | 13.13 |
| winter | D0-1dB | 65.1 | 69.3 | 60.9 | 0.26 | 68.8 | 70.4 | 0.30 | 26.44 |  |
| winter | D0+1dB | 39.1 | 78.2 | 85.2 | 0.22 | 45.6 | 79.6 | 0.28 | 8.41 |  |
| winter | D1 | 36.0 | 73.1 | 82.0 | 0.17 | 43.2 | 75.4 | 0.22 | 13.03 | 13.07 |
| winter | D1r | 47.2 | 74.4 | 77.9 | 0.24 | 52.7 | 75.9 | 0.29 | 12.67 |  |
| summer | D0 | 67.8 | 93.2 | 86.8 | 0.44 | 70.5 | 93.0 | 0.47 | 14.53 | 14.62 |
| summer | D0-1dB | 84.2 | 87.2 | 66.9 | 0.50 | 85.0 | 87.2 | 0.51 | 28.62 |  |
| summer | D0+1dB | 50.1 | 94.6 | 92.3 | 0.30 | 54.7 | 94.1 | 0.34 | 9.75 |  |
| summer | D1 | 46.2 | 93.6 | 91.6 | 0.27 | 51.6 | 93.6 | 0.31 | 14.53 | 14.67 |
| summer | D1r | 63.5 | 93.6 | 88.4 | 0.41 | 67.1 | 93.4 | 0.44 | 13.53 |  |

- Winter: 42,423 field-seasons (543,517 ha; 57.6% of the area green in Sentinel-2), 583,394 desert patches. Held-out D0 FAR (threshold fitted on the other half): random half 13.13%, halves swapped 12.95%, 1.6 km spatial blocks 13.20%; on WorldCover-bare patches only, in-sample 12.37%.
- Summer: 49,061 field-seasons (631,447 ha; 72.8% of the area green in Sentinel-2), 639,663 desert patches. Held-out D0 FAR (threshold fitted on the other half): random half 14.62%, halves swapped 14.45%, 1.6 km spatial blocks 14.74%; on WorldCover-bare patches only, in-sample 13.87%.

**Per year** (44,608 fields with ≥ 4 radar dates in 38 regions; 2,276 fields with fewer dates left out). Median CV: farmed fields 0.205, of which green in both seasons 0.189; not-green fields 0.135; desert patches 0.14 (normalised: farmed 0.157, desert 0.057). CV cuts: oracle 0.204, matched 0.197; D2n oracle 0.089, matched 0.107.

| Detector | Recall (area) | Precision (area) | Specificity (area) | κ (area) | Recall (count) | κ (count) | Recall: green both seasons | Recall: green one season | Desert FAR % |
|---|---|---|---|---|---|---|---|---|---|
| D0 any season | 68.5 | 93.7 | 77.8 | 0.31 | 71.3 | 0.34 | 72.2 | 61.4 | 16.22 |
| D1 any season | 53.1 | 93.8 | 82.8 | 0.20 | 58.1 | 0.24 | 53.1 | 51.5 | 15.82 |
| D2 CV>0.5 | 16.1 | 92.3 | 93.5 | 0.04 | 16.1 | 0.04 | 8.8 | 26.8 | 1.11 |
| D2 oracle | 53.8 | 92.0 | 77.4 | 0.17 | 50.4 | 0.15 | 50.0 | 61.9 | 13.85 |
| D2 matched FAR | 56.1 | 91.9 | 76.1 | 0.18 | 52.5 | 0.16 | 52.7 | 63.7 | 16.22 |
| D2n CV>0.5 | 15.1 | 91.9 | 93.6 | 0.03 | 15.3 | 0.04 | 8.6 | 25.0 | 0.80 |
| D2n oracle | 80.4 | 87.5 | 44.7 | 0.22 | 79.0 | 0.20 | 80.4 | 82.9 | 23.86 |
| D2n matched FAR | 71.5 | 88.2 | 53.8 | 0.19 | 69.7 | 0.17 | 69.8 | 76.2 | 16.22 |

## All region-seasons (115 region-seasons in 60 regions)

D1 national thresholds: winter -10.89 dB raw HV, summer -13.53 dB raw HV.

| Season | Detector | Recall (area) | Precision (area) | Specificity (area) | κ (area) | Recall (count) | Precision (count) | κ (count) | Desert FAR % | Held-out FAR % |
|---|---|---|---|---|---|---|---|---|---|---|
| winter | D0 | 38.3 | 74.4 | 82.6 | 0.19 | 41.6 | 75.8 | 0.24 | 8.75 | 8.82 |
| winter | D0-1dB | 52.5 | 69.5 | 69.6 | 0.21 | 54.0 | 70.4 | 0.25 | 17.24 |  |
| winter | D0+1dB | 31.1 | 78.1 | 88.5 | 0.18 | 35.4 | 79.5 | 0.22 | 5.62 |  |
| winter | D1 | 5.1 | 63.6 | 96.1 | 0.01 | 5.4 | 64.6 | 0.01 | 8.75 | 8.73 |
| winter | D1r | 37.9 | 74.5 | 82.8 | 0.19 | 41.2 | 75.9 | 0.23 | 8.55 |  |
| summer | D0 | 54.9 | 93.3 | 87.8 | 0.30 | 53.2 | 93.1 | 0.27 | 9.87 | 9.94 |
| summer | D0-1dB | 68.6 | 87.4 | 69.4 | 0.31 | 64.7 | 87.5 | 0.27 | 19.11 |  |
| summer | D0+1dB | 40.3 | 94.6 | 92.9 | 0.21 | 41.0 | 94.2 | 0.20 | 6.55 |  |
| summer | D1 | 6.0 | 99.2 | 99.8 | 0.03 | 7.4 | 98.9 | 0.04 | 9.87 | 9.87 |
| summer | D1r | 51.3 | 93.7 | 89.3 | 0.28 | 50.5 | 93.5 | 0.26 | 9.17 |  |

- Winter: 56,779 field-seasons (693,607 ha; 56.9% of the area green in Sentinel-2), 997,436 desert patches. Held-out D0 FAR (threshold fitted on the other half): random half 8.82%, halves swapped 8.70%, 1.6 km spatial blocks 8.85%; on WorldCover-bare patches only, in-sample 8.56%.
- Summer: 63,042 field-seasons (761,736 ha; 75.6% of the area green in Sentinel-2), 1,050,957 desert patches. Held-out D0 FAR (threshold fitted on the other half): random half 9.94%, halves swapped 9.79%, 1.6 km spatial blocks 10.06%; on WorldCover-bare patches only, in-sample 10.01%.

**Per year** (62,311 fields with ≥ 4 radar dates in 60 regions; 2,471 fields with fewer dates left out). Median CV: farmed fields 0.217, of which green in both seasons 0.197; not-green fields 0.14; desert patches 0.147 (normalised: farmed 0.172, desert 0.071). CV cuts: oracle 0.201, matched 0.348; D2n oracle 0.095, matched 0.319.

| Detector | Recall (area) | Precision (area) | Specificity (area) | κ (area) | Recall (count) | κ (count) | Recall: green both seasons | Recall: green one season | Desert FAR % |
|---|---|---|---|---|---|---|---|---|---|
| D0 any season | 55.4 | 94.1 | 79.7 | 0.18 | 53.9 | 0.17 | 63.8 | 46.9 | 11.83 |
| D1 any season | 9.2 | 95.2 | 97.3 | 0.02 | 10.2 | 0.02 | 8.9 | 9.3 | 14.75 |
| D2 CV>0.5 | 20.1 | 91.9 | 89.7 | 0.03 | 19.4 | 0.03 | 15.1 | 28.2 | 8.58 |
| D2 oracle | 57.2 | 92.4 | 72.5 | 0.15 | 54.5 | 0.13 | 54.3 | 64.2 | 24.31 |
| D2 matched FAR | 29.7 | 92.1 | 85.0 | 0.06 | 28.7 | 0.05 | 23.3 | 39.2 | 11.83 |
| D2n CV>0.5 | 18.0 | 91.5 | 90.1 | 0.03 | 17.0 | 0.02 | 13.7 | 25.4 | 6.83 |
| D2n oracle | 78.2 | 89.3 | 45.1 | 0.18 | 77.0 | 0.16 | 78.6 | 80.7 | 36.34 |
| D2n matched FAR | 29.2 | 91.2 | 83.4 | 0.05 | 28.2 | 0.04 | 24.1 | 37.1 | 11.83 |

## Where each detector wins

Area-weighted κ against Sentinel-2, with the share of the region's desert patches each detector calls active in brackets (FAR %). D1 and D2m use the national cuts fitted on the QC-passing pool, applied to every region (the cuts fitted on all region-seasons are in the JSON); per region they are not matched to D0's false-alarm rate. Flags: SW = southwest (Jazan, Asir, Najran, Al Bahah; majority of field area), DUNE = dune texture in the desert background, SEA = at least 5% of desert patches are water. QC: ✓ pass, ✗ fail, · season not observed. Thr = D0 threshold. Year FAR = desert patches called active in at least one season. Winner by κ (tie if within 0.02; n/a when Sentinel-2 has fewer than 20 fields in one class); * = the winner flags more than 1 point more of this region's desert than D0 does.

| Region | Admin | Flags | QC W/S | Thr W/S dB | Fields | Winter κ D0/D1 (FAR %) | Summer κ D0/D1 (FAR %) | Year κ D0/D2/D2m (FAR % D0/D2m) | Winner W / S | Winner year |
|---|---|---|---|---|---|---|---|---|---|---|
| R01 | Jazan | SW | ✗/✗ | 11.9/16.2 | 3,483 | 0.00/0.03 (0/86) | 0.00/0.24 (0/82) | 0.00/0.00/0.00 (0/17) | D1* / D1* | D1* |
| R02 | Al Jawf |  | ✓/✓ | 2.9/1.8 | 3,571 | 0.57/0.57 (4/4) | 0.66/0.57 (8/6) | 0.63/0.16/0.53 (8/7) | tie D1=D0 / D0 | D0 |
| R03 | Jazan | SW SEA | ✗/✗ | 14.3/13.2 | 1,445 | 0.00/0.06 (0/56) | 0.00/0.17 (0/50) | 0.00/-0.01/-0.03 (0/42) | D1* / D1* | D1* |
| R04 | Riyadh |  | ✓/✓ | 1.6/2.2 | 2,639 | 0.31/0.06 (16/5) | 0.55/0.02 (13/3) | 0.04/-0.01/0.00 (22/19) | D0 / D0 | D0 |
| R05 | Riyadh | DUNE | ✓/✓ | 2.2/1.1 | 2,036 | 0.37/0.30 (23/15) | 0.69/0.29 (30/15) | 0.54/0.06/0.22 (30/2) | D0 / D0 | D0 |
| R06 | Al-Qassim |  | ✓/✓ | 3.5/2.6 | 2,007 | 0.31/0.34 (4/7) | 0.44/0.54 (8/12) | 0.24/0.04/0.15 (8/25) | D1* / D1* | D1* |
| R07 | Al Jawf |  | ✓/✓ | 3.4/1.5 | 1,367 | 0.21/0.19 (19/47) | 0.31/0.30 (22/23) | 0.24/0.08/0.20 (32/22) | D0 / tie D0=D1 | tie D0=D1 |
| R08 | Al-Qassim | DUNE | ✓/✓ | 5.2/4.8 | 2,335 | 0.42/0.42 (18/30) | 0.30/0.41 (19/31) | 0.23/0.00/0.03 (19/11) | tie D1=D0 / D1* | D1* |
| R09 | Hayel |  | ✓/✓ | 2.8/2.7 | 2,178 | 0.02/-0.09 (9/3) | 0.41/0.15 (10/3) | 0.37/0.05/0.22 (12/18) | D0 / D0 | D0 |
| R10 | Al Jawf |  | ✗/✓ | 40.2/1.4 | 1,544 | 0.00/-0.06 (0/66) | 0.50/0.15 (14/8) | 0.27/-0.07/-0.02 (14/74) | D0 / D0 | D0 |
| R11 | Al-Qassim |  | ✓/✓ | 1.2/1.7 | 1,989 | 0.39/0.33 (18/11) | 0.56/0.45 (15/11) | 0.40/0.08/0.27 (19/5) | D0 / D0 | D0 |
| R12 | Riyadh |  | ✗/✗ | 34.2/18.3 | 1,350 | 0.00/0.00 (0/38) | 0.00/0.11 (0/1) | 0.00/-0.01/-0.02 (0/57) | tie D1=D0 / D1 | tie D0=D2=D2m |
| R13 | Hayel |  | ✓/✓ | 3.2/3.1 | 1,544 | -0.06/-0.04 (8/7) | 0.11/0.07 (9/7) | 0.03/0.02/0.05 (10/4) | D1 / D0 | D2m |
| R14 | Eastern |  | ·/✓ | ·/1.3 | 1,829 | · | 0.72/0.51 (6/3) | 0.78/0.01/0.20 (7/0) | · / D0 | D0 |
| R15 | Riyadh |  | ✗/✓ | 34.1/1.4 | 1,464 | 0.00/0.29 (0/70) | 0.49/0.10 (28/20) | 0.19/0.06/-0.03 (28/67) | D1* / D0 | D0 |
| R16 | Jazan | SW SEA | ✓/✓ | 1.2/0.9 | 1,349 | 0.00/0.13 (22/10) | 0.19/0.33 (24/9) | 0.00/0.00/0.00 (26/2) | D1 / D1 | D1 |
| R17 | Riyadh |  | ·/✗ | ·/8.1 | 1,866 | · | 0.01/0.29 (4/46) | 0.01/0.01/0.07 (4/0) | · / D1* | D1* |
| R18 | Tabuk |  | ✓/✓ | 1.9/1.7 | 910 | -0.04/-0.03 (20/19) | 0.22/0.47 (21/41) | 0.14/0.03/0.25 (22/94) | tie D1=D0 / D1* | D1* |
| R19 | Al Jawf |  | ✓/✓ | 3.2/0.8 | 1,562 | -0.01/0.00 (2/3) | 0.77/0.17 (7/2) | 0.56/0.06/0.13 (8/8) | tie D1=D0 / D0 | D0 |
| R20 | Al Jawf |  | ✓/✓ | 4.4/1.6 | 1,288 | -0.15/-0.15 (18/32) | 0.17/0.07 (22/19) | 0.01/-0.08/-0.10 (35/50) | tie D0=D1 / D0 | D0 |
| R21 | Jazan | SW SEA | ✗/✗ | 8.4/8.6 | 463 | 0.16/0.18 (5/38) | 0.03/0.34 (4/41) | 0.02/0.00/0.00 (5/7) | tie D1=D0 / D1* | n/a |
| R22 | Riyadh | DUNE | ✓/✓ | 2.4/2.0 | 1,033 | 0.10/0.03 (14/5) | 0.66/0.13 (18/6) | 0.16/0.01/0.08 (19/4) | D0 / D0 | D0 |
| R23 | Al Jawf |  | ✓/✓ | 1.5/1.6 | 2,583 | -0.06/-0.08 (6/1) | 0.34/0.19 (2/1) | 0.24/0.04/0.23 (7/8) | tie D0=D1 / D0 | tie D0=D2m |
| R24 | Al Jawf |  | ✓/✓ | 3.8/4.0 | 1,680 | -0.02/-0.10 (7/35) | 0.04/0.10 (14/40) | 0.02/0.03/0.09 (14/26) | D0 / D1* | D2m* |
| R25 | Tabuk |  | ✓/✓ | 3.7/4.4 | 714 | 0.02/0.04 (20/34) | 0.05/0.19 (18/47) | 0.02/0.02/0.13 (20/31) | D1* / D1* | tie D2m=D1* |
| R26 | Hayel |  | ✓/✓ | 1.0/1.5 | 1,076 | 0.10/0.03 (11/3) | 0.35/0.24 (8/4) | 0.16/0.03/0.10 (12/3) | D0 / D0 | D0 |
| R27 | Hayel | DUNE | ✓/✓ | 2.6/2.2 | 1,183 | 0.05/0.05 (20/16) | 0.28/0.13 (21/13) | 0.17/0.05/0.14 (20/4) | tie D0=D1 / D0 | D0 |
| R28 | 'Asir | SW | ✗/✗ | 8.8/6.8 | 551 | 0.02/0.00 (3/100) | 0.00/0.11 (1/99) | 0.00/0.00/0.00 (3/28) | D0 / n/a | n/a |
| R29 | Riyadh |  | ✗/✓ | 32.7/3.7 | 716 | 0.00/0.25 (0/84) | 0.09/0.13 (23/31) | 0.01/0.01/0.00 (23/79) | D1* / D1* | D1* |
| R30 | Eastern |  | ✓/✓ | 2.1/2.1 | 955 | 0.09/0.11 (4/7) | 0.28/0.30 (6/14) | 0.05/0.00/0.02 (7/6) | D1* / D1* | tie D1=D0 |
| R31 | Al-Qassim |  | ✓/✓ | 1.3/1.6 | 512 | 0.15/0.14 (12/1) | 0.57/0.29 (11/1) | 0.23/0.07/0.32 (14/17) | tie D0=D1 / D0 | D2m* |
| R32 | 'Asir | SW | ✗/✗ | 8.0/6.3 | 405 | -0.02/0.00 (4/99) | 0.00/0.00 (1/99) | 0.00/0.00/0.00 (4/23) | tie D1=D0 / n/a | n/a |
| R33 | Al-Qassim | DUNE | ✓/✓ | 2.9/3.4 | 804 | 0.25/0.23 (14/11) | 0.36/0.32 (14/12) | 0.28/0.01/0.12 (15/2) | tie D0=D1 / D0 | tie D0=D1 |
| R34 | Al-Qassim |  | ✓/✓ | 2.5/3.8 | 725 | 0.60/0.62 (19/13) | 0.54/0.54 (11/15) | 0.32/0.00/-0.06 (19/20) | D1 / tie D1=D0 | D1 |
| R35 | Hayel |  | ✓/✓ | 2.1/1.5 | 822 | 0.18/0.19 (10/9) | 0.50/0.36 (15/11) | 0.32/0.03/0.30 (15/12) | tie D1=D0 / D0 | D0 |
| R36 | Al-Qassim |  | ✓/✓ | 2.5/2.2 | 718 | 0.11/0.11 (4/4) | 0.24/0.30 (8/10) | 0.14/0.03/0.42 (8/16) | tie D0=D1 / D1* | D2m* |
| R37 | Riyadh | DUNE | ✓/✓ | 3.1/2.3 | 583 | 0.21/0.13 (8/4) | 0.66/0.21 (12/5) | 0.31/0.06/0.17 (12/12) | D0 / D0 | D0 |
| R38 | Eastern |  | ·/✓ | ·/1.6 | 1,142 | · | 0.59/0.19 (2/1) | 0.69/0.02/0.30 (2/0) | · / D0 | D0 |
| R39 | Al-Qassim | DUNE | ✓/✓ | 2.7/2.5 | 894 | 0.31/0.32 (12/10) | 0.40/0.33 (12/11) | 0.29/0.01/0.09 (13/4) | tie D1=D0 / D0 | D0 |
| R40 | Al-Qassim |  | ✓/✓ | 1.3/1.6 | 533 | 0.43/0.35 (12/2) | 0.71/0.39 (8/3) | 0.56/0.09/0.34 (13/46) | D0 / D0 | D0 |
| R41 | Eastern |  | ·/✓ | ·/4.5 | 988 | · | 0.34/0.61 (21/33) | 0.34/0.00/0.00 (21/0) | · / D1* | D1* |
| R42 | 'Asir | SW | ✗/✗ | 5.8/5.6 | 1,151 | 0.11/0.00 (6/100) | 0.00/0.00 (1/100) | 0.00/0.00/0.02 (6/13) | D0 / tie D0=D1 | tie D2m=D0=D2 |
| R43 | Al Jawf |  | ✓/✗ | 3.8/4.3 | 764 | 0.05/-0.05 (10/38) | 0.04/0.41 (8/65) | 0.03/0.02/0.22 (10/63) | D0 / D1* | D1* |
| R44 | Makkah |  | ✗/✗ | 11.3/12.6 | 342 | 0.00/0.00 (0/70) | 0.00/0.21 (0/74) | 0.00/0.00/0.00 (0/3) | tie D0=D1 / n/a | n/a |
| R45 | Al Bahah | SW | ✗/✗ | 13.2/4.9 | 168 | 0.08/0.00 (3/100) | 0.05/0.00 (4/100) | 0.00/0.00/0.02 (5/58) | D0 / n/a | n/a |
| R46 | Al Jawf |  | ✓/✓ | 3.6/4.3 | 337 | 0.13/0.19 (9/30) | 0.07/0.22 (9/34) | 0.04/0.02/0.17 (9/14) | D1* / D1* | tie D2m=D1* |
| R47 | 'Asir | SW | ✗/✗ | 6.2/4.1 | 153 | 0.09/0.02 (9/100) | 0.01/0.00 (2/100) | -0.01/-0.01/-0.01 (9/26) | D0 / n/a | n/a |
| R48 | Al-Qassim |  | ✓/✓ | 1.2/1.9 | 472 | 0.17/0.15 (15/9) | 0.33/0.27 (13/11) | 0.21/0.03/0.15 (16/5) | tie D0=D1 / D0 | D0 |
| R49 | Tabuk |  | ✓/✓ | 1.3/1.2 | 415 | 0.20/0.10 (9/3) | 0.31/0.09 (11/7) | 0.16/0.00/0.07 (11/16) | D0 / D0 | D0 |
| R50 | Hayel |  | ✓/✓ | 2.3/1.7 | 504 | 0.01/0.03 (3/2) | 0.51/0.36 (5/3) | 0.26/0.13/0.36 (5/8) | D1 / D0 | D2m* |
| R51 | Riyadh | DUNE | ✓/✓ | 2.5/3.2 | 726 | 0.22/0.16 (13/5) | 0.44/0.32 (15/8) | 0.11/0.00/0.03 (17/48) | D0 / D0 | D0 |
| R52 | 'Asir | SW | ✗/✗ | 11.2/6.7 | 220 | 0.00/0.00 (1/99) | 0.00/– (2/99) | 0.00/0.00/0.00 (2/50) | tie D0=D1 / n/a | n/a |
| R53 | Al Madinah |  | ·/✗ | ·/16.7 | 705 | · | 0.00/0.15 (0/77) | 0.00/0.00/0.06 (0/60) | · / n/a | n/a |
| R54 | Makkah |  | ✗/✗ | 5.9/4.7 | 69 | 0.04/0.00 (5/100) | -0.06/0.00 (2/100) | 0.00/0.00/0.01 (5/36) | n/a / n/a | n/a |
| R55 | Al Bahah | SW | ✗/✗ | 15.1/4.8 | 132 | 0.00/0.00 (0/100) | 0.26/0.08 (18/59) | 0.03/-0.01/-0.02 (18/93) | tie D0=D1 / D0 | n/a |
| R56 | Riyadh |  | ✗/✗ | 13.8/12.7 | 423 | 0.00/0.00 (0/100) | 0.00/0.86 (0/95) | 0.00/0.04/-0.02 (0/86) | n/a / n/a | n/a |
| R57 | 'Asir | SW | ✗/✗ | 4.4/3.3 | 91 | 0.05/0.00 (8/100) | 0.02/0.00 (3/100) | -0.01/0.00/-0.01 (8/10) | n/a / n/a | n/a |
| R58 | Riyadh |  | ✓/✓ | 2.5/2.6 | 361 | 0.17/0.15 (14/12) | 0.37/0.27 (17/14) | 0.12/0.00/0.03 (17/5) | D0 / D0 | D0 |
| R59 | Najran | SW DUNE | ✗/✗ | 16.5/19.6 | 394 | 0.00/0.02 (0/72) | 0.00/0.12 (0/73) | 0.00/0.00/0.00 (0/19) | tie D1=D0 / n/a | n/a |
| R60 | Riyadh | DUNE | ✓/✓ | 3.6/4.1 | 520 | 0.32/0.32 (16/15) | 0.35/0.34 (16/16) | 0.22/0.00/0.00 (17/23) | tie D0=D1 / tie D0=D1 | D0 |

**By group** (pooled within the group; area κ; D1 with the QC-fitted / all-fitted national thresholds; 'QC pass' rows keep only region-seasons that pass the quality check):

| Group | Regions | Winter κ D0 / D1qc / D1all | Summer κ D0 / D1qc / D1all | Year κ D0 / D2 / D2m | Desert FAR % D0 / D1qc, winter; summer |
|---|---|---|---|---|---|
| Southwest | 13 | 0.14 / 0.05 / 0.05 | 0.00 / 0.23 / 0.01 | 0.00 / 0.00 / 0.00 | 5.1 / 81.4; 4.8 / 78.5 |
| Dune | 10 | 0.26 / 0.23 / 0.00 | 0.47 / 0.30 / 0.02 | 0.26 / 0.03 / 0.10 | 13.8 / 15.9; 16.1 / 16.6 |
| Other | 38 | 0.16 / 0.19 / 0.01 | 0.37 / 0.26 / 0.02 | 0.23 / 0.05 / 0.22 | 8.7 / 32.6; 10.2 / 30.2 |
| Dune, QC pass | 9 | 0.27 / 0.23 / 0.00 | 0.49 / 0.29 / 0.02 | 0.27 / 0.03 / 0.11 | 14.9 / 11.7; 17.3 / 12.3 |
| Other, QC pass | 32 | 0.23 / 0.14 / 0.00 | 0.43 / 0.25 / 0.02 | 0.31 / 0.04 / 0.22 | 11.6 / 13.9; 12.8 / 15.8 |

## Context

- Desert median HV, QC-passing winters: median -23.82 dB (range -27.09 to -21.84, IQR -24.61 to -23.24; n = 36).
- Desert median HV, QC-passing summers: median -22.94 dB (range -26.42 to -20.98, IQR -23.84 to -22.22; n = 41).
- Desert median HV, all winters: median -23.2 dB (range -27.09 to -11.43, IQR -24.32 to -18.52; n = 55).
- Desert median HV, all summers: median -22.39 dB (range -26.42 to -14.04, IQR -23.37 to -20.79; n = 60).
- Summer minus winter desert median (regions passing QC in both seasons): median 0.93 dB (range 0.06 to 2.04, IQR 0.59 to 1.22; n = 35).
- Within a season, desert medians move by 0.52 dB between dates (median; max 1.68 dB) in QC-passing region-seasons.

## Caveats

- Sentinel-2 greenness (field median of the seasonal maximum NDVI > 0.40) is a reference, not ground truth: winter crops that green after the late-November to January radar dates, weedy fallow, rain-greened natural vegetation in the southwest and palms/orchards all blur it. Summer is lopsided (most mapped fields are green), so summer κ moves a lot with small changes in specificity.
- Desert patches are the pipeline's own 320 m blocks at least 400 m from any mapped field. They are mostly bare (WorldCover), but include rock outcrops, dunes, roads, some built-up land, unmapped small plots and, on the Jazan coast, sea (R03, R16, R21 have ≥ 5% water patches). D0's false-alarm rate on WorldCover-bare patches only is 12.4% vs 13.0% on all (QC winter).
- Patches are 10.24 ha; fields range from 3 ha to several hundred. A small field's mean is noisier than a patch mean, so the false-alarm rate for small fields is likely above the patch rate, and below it for large pivots.
- D1's thresholds are matched to D0's pooled rate in-sample by construction; on the held-out half the two rates stay within 0.07 / 0.05 points (winter / summer). Pooled rates weight regions by their desert area, so per-region rates differ a lot (table above): a national raw threshold concentrates its false alarms in bright-desert regions and has almost none on dark sand.
- CV uses only 4-7 dates (3 between late November and January, 4 in June-October; summer-only regions have 4), far sparser than the 12-day series the NISAR crop-area rule (CV > 0.5) was designed for, and is computed on field means (not pixels) with the population standard deviation (a sample std would raise CV by 8-15%, not enough to change the ranking). Between-season calibration steps inflate desert CV, which D2n removes.
- The QC rule is the project's (a date's desert median ≤ −21 dB and threshold ≤ 6 dB), applied to the values in meta.json. Outside the southwest (where only R16 W, R16 S pass) it rejects region-seasons whose desert is brighter than −21 dB on every date (R10 W, R15 W, R29 W, R43 S, R44 W, R44 S, R53 S, R54 W, R54 S, R56 W, R56 S: Shield and limestone ground, or anomalously bright scenes) or whose threshold exceeds 6 dB (R10 W, R12 W, R12 S, R15 W, R17 S, R29 W, R44 W, R44 S, R53 S, R56 W, R56 S; in R12 a dark swath-edge strip inside the desert mask inflates it).
- Dune flags come from visual inspection of the HV images (dune texture in the desert background), R05 and R22 being the least certain; 'southwest' is the majority admin region of the field centres (the project's own list).
- Fields mapped by two overlapping regions are scored in each region, as the pipeline validates per region: 4,250 of 64,783 fields (6.6%) belong to another region under the national table's de-duplication rule. Dropping them barely moves the result (QC summer area κ D0 0.45, D1 0.26).
- Per-region κ is unstable where Sentinel-2 is one-sided (e.g. southwest summers where nearly every mapped field is green); the winner is then marked n/a. Ties use a 0.02 κ margin.
- All numbers come from the stored region outputs at run time. Another session may re-run parts of the pipeline; the reproduction check (thresholds, desert medians, field values, D0 calls) is recomputed on every run and would show any region that changed mid-run.

## Reproduction check

Desert medians, thresholds and field values were recomputed from the stored HV rasters on the pipeline's grid with its reprojection: grids match for 60/60 regions, thresholds for 115/115 region-seasons (to 0.01 dB), desert medians to 0.0e+00 dB, field HV to 0.0e+00 dB, and D0 reproduces the stored field calls for 100.000% of 119,835 field-seasons. Deterministic: fixed seed 20261115 for the patch splits, no other randomness.

