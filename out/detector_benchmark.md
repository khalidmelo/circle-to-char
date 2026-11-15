# Audit note (read first)

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
5. Without the quality check, the collapse of a national threshold is real in winter; in summer it reflects the desert-false-
   alarm matching (at D0's field specificity D1 gets kappa 0.37 vs D0's 0.22).
6. D0's own desert false-alarm rate is about 13-14.5% in quality-checked regions, so "3 sigma" is a misleading name for its
   threshold: the desert patch peaks are right-skewed and p50 + 3(p50 - p16) sits inside the bright tail.

---

# Detector benchmark: does the pipeline's radar rule beat simpler ones?

Built by `scripts/detector_benchmark.py` from stored data only (60 regions; runtime 59 s with 6 worker processes, 53 s of it reading and reprojecting 405 HV rasters). Reference: Sentinel-2 field greenness per season (winter over the radar's own late-November to January dates, summer June-October). False alarms: share of the pipeline's own 10 ha far-from-field desert patches that a detector calls 'active'.

## Key findings

- At matched desert false-alarm rates D0 beats D1 in both seasons where the radar passes QC: area κ 0.24 vs 0.17 in winter (+0.07) and 0.44 vs 0.27 in summer (+0.17). With 13.0% / 14.5% of desert patches flagged by both, D0 finds 47.8% vs 36.3% (winter) and 67.8% vs 46.4% (summer) of the area Sentinel-2 sees green, at the same precision (74.3/73.2% and 93.3/93.7%). Count-based κ tells the same story (0.29/0.23 winter, 0.47/0.31 summer).
- The gain comes from fitting the threshold per region, not from per-date normalisation: D1r (raw HV, per-region threshold) scores κ 0.24 / 0.41, close to D0's 0.24 / 0.44. Desert medians span 5.2 dB across QC-passing regions in winter and 5.4 dB in summer, so one raw threshold must sit above the brightest desert and misses fields on dark sand. The winter-to-summer step in desert medians (median +0.93 dB over 35 regions; the two seasons come from different NISAR processing versions) is absorbed by any per-season threshold, D1's included; within a season desert medians move by a median 0.52 dB between dates.
- Without the QC filter a national threshold breaks down: matched to D0's false-alarm rate over all region-seasons it rises to -11.4 dB (winter) and -13.9 dB (summer), and D1 falls to κ 0.00 / 0.09 (D0 0.18 / 0.22; recall D0 39.8% / 49.1% vs D1 8.6% / 21.4%). Its desert false alarms sit almost entirely in region-seasons that fail QC (97% in winter, 90% in summer; largest shares R56 18%, R45 14%, R29 12%, R55 9% in winter, R54 18%, R56 10%, R45 9%, R47 8% in summer): bright Shield and limestone desert, and 13 scenes in R10, R15, R29, R55, R56 whose desert median is 4-12 dB above the region's other dates. D0 absorbs both, because it normalises by each scene's own desert.
- D2 (CV) is weaker than D0 at every operating point. CV > 0.5 almost never fires on field-averaged HV (median CV 0.205 on farmed fields, 0.14 on desert): recall 16.1% (QC pool), 8.8% on fields green in both seasons. At D0's year-level false-alarm rate (16.2%) D2 reaches κ 0.18 vs D0 0.31 (recall 55.9% vs 68.6%; fields green in both seasons 52.5% vs 72.3%); even the oracle cut gives κ 0.17. Normalising by the desert median shrinks desert CV (median 0.14 → 0.057) but field CV too (0.205 → 0.156): at matched FAR D2n scores κ 0.18, and its best cut κ 0.21 at a 23.7% false-alarm rate. With 4-7 dates and one canopy per season, the seasonal peak carries the signal and the year's spread does not.
- Where D0 does not win: per region the national cuts are not matched to D0's false-alarm rate. With the QC-fitted cut, D1 has the higher κ in 30 region-seasons, but in 24 of them it also flags more of that region's desert (it trades false alarms for recall where the national cut falls below D0's regional one), and in 14 of the 30 neither detector reaches κ 0.2. At an equal or lower regional false-alarm rate D1 wins only in R12 S (QC fail), R13 W (QC pass), R16 W (QC pass SW), R16 S (QC pass SW), R34 W (QC pass), R50 W (QC pass). Per year, D1 or D2m beats D0 at no extra desert false alarms in R13 D2m, R16 D1 (SW), R34 D1; with more false alarms in R01 D1 (SW), R03 D1 (SW), R06 D1, R08 D1 (DUNE), R17 D1, R18 D1, R21 D1 (SW), R24 D2m, R25 tie D2m=D1, R29 D1, R31 D2m, R36 D2m, R41 D1, R43 D1, R46 tie D2m=D1, R50 D2m, R53 D1.
- Dune regions (all pass QC except R59): D0 keeps its lead over D1 (winter κ 0.27 vs 0.23, summer 0.49 vs 0.29), but flags more desert than in other QC-passing regions (14.9% / 17.3% vs 11.5% / 12.8%), probably bright dune faces above a threshold set by the darker sand. Southwest: no detector works. D0 reaches κ 0.17 in winter and 0.00 in summer; the QC-fitted D1 calls 78.9% / 75.7% of the bright rocky desert active (κ 0.01 / 0.18), and Sentinel-2's summer green there is largely rain-fed or natural vegetation.
- D0's own desert false-alarm rate is far above what '3 sigma' suggests: 13.0% (winter) and 14.5% (summer) of far-from-field desert patches pass the threshold in the QC pool. This is not an artefact of fitting on the same patches (held-out half 13.1% / 14.6%; 1.6 km spatial blocks 13.0% / 14.6%) nor of towns or water (WorldCover-bare patches 12.3% / 13.8%): the desert patch peaks are right-skewed (median p50 − p16 = 0.73 / 0.59 dB, p84 − p50 = 1.51 / 1.59 dB), so p50 + 3 × (p50 − p16) sits inside the bright tail. D0+1dB cuts the rate to 8.4% / 9.7% for 8.6 / 17.7 points of recall; D0−1dB raises κ to 0.26 / 0.50 but doubles the rate.

## The detectors

- **D0**: the pipeline rule: seasonal peak of HV minus the same-date desert median, above a threshold fitted per region and season on desert patches (p50 + 3 × (p50 − p16)). **D0±1dB**: same with the threshold moved 1 dB.
- **D1**: seasonal peak of raw HV (no desert normalisation) above one national threshold per season, set so that D1's pooled desert false-alarm rate equals D0's (fitted separately for each pool). **D1r** (diagnostic): raw HV with the pipeline's formula per region and season, which separates 'regional threshold' from 'per-date normalisation'.
- **D2**: temporal coefficient of variation (std/mean) of linear HV over all of a field's dates (≥ 4), crop if CV > 0.5 (NISAR crop-area rule); also at the best possible CV cut (oracle, Youden) and at the cut that matches D0's year-level false-alarm rate. **D2n** (diagnostic): the same on desert-normalised HV. CV is a per-year statistic, so D2 is scored per field against 'green in at least one season', next to D0/D1 'active in at least one season'.

## Region-seasons that pass the radar quality check (77 region-seasons in 42 regions)

D1 national thresholds: winter -20.99 dB raw HV, summer -20.11 dB raw HV.

| Season | Detector | Recall (area) | Precision (area) | Specificity (area) | κ (area) | Recall (count) | Precision (count) | κ (count) | Desert FAR % | Held-out FAR % |
|---|---|---|---|---|---|---|---|---|---|---|
| winter | D0 | 47.8 | 74.3 | 77.7 | 0.24 | 53.3 | 75.8 | 0.29 | 12.97 | 13.11 |
| winter | D0-1dB | 65.1 | 69.2 | 60.8 | 0.26 | 68.8 | 70.3 | 0.29 | 26.50 |  |
| winter | D0+1dB | 39.2 | 78.2 | 85.2 | 0.22 | 45.8 | 79.7 | 0.28 | 8.35 |  |
| winter | D1 | 36.3 | 73.2 | 82.0 | 0.17 | 43.5 | 75.4 | 0.23 | 12.97 | 13.12 |
| winter | D1r | 47.3 | 74.4 | 77.9 | 0.24 | 52.8 | 75.9 | 0.29 | 12.62 |  |
| summer | D0 | 67.8 | 93.3 | 86.8 | 0.44 | 70.4 | 93.0 | 0.47 | 14.47 | 14.65 |
| summer | D0-1dB | 84.2 | 87.2 | 66.8 | 0.50 | 85.0 | 87.2 | 0.51 | 28.69 |  |
| summer | D0+1dB | 50.1 | 94.6 | 92.3 | 0.30 | 54.7 | 94.2 | 0.34 | 9.68 |  |
| summer | D1 | 46.4 | 93.7 | 91.6 | 0.27 | 51.8 | 93.6 | 0.31 | 14.47 | 14.70 |
| summer | D1r | 63.6 | 93.7 | 88.4 | 0.41 | 67.0 | 93.4 | 0.44 | 13.47 |  |

- Winter: 43,438 field-seasons (551,148 ha; 57.5% of the area green in Sentinel-2), 581,811 desert patches. Held-out D0 FAR (threshold fitted on the other half): random half 13.11%, halves swapped 12.85%, 1.6 km spatial blocks 13.01%; on WorldCover-bare patches only, in-sample 12.32%.
- Summer: 50,219 field-seasons (640,069 ha; 72.9% of the area green in Sentinel-2), 637,893 desert patches. Held-out D0 FAR (threshold fitted on the other half): random half 14.65%, halves swapped 14.29%, 1.6 km spatial blocks 14.58%; on WorldCover-bare patches only, in-sample 13.83%.

**Per year** (45,661 fields with ≥ 4 radar dates in 38 regions; 2,311 fields with fewer dates left out). Median CV: farmed fields 0.205, of which green in both seasons 0.189; not-green fields 0.135; desert patches 0.14 (normalised: farmed 0.156, desert 0.057). CV cuts: oracle 0.204, matched 0.197; D2n oracle 0.089, matched 0.108.

| Detector | Recall (area) | Precision (area) | Specificity (area) | κ (area) | Recall (count) | κ (count) | Recall: green both seasons | Recall: green one season | Desert FAR % |
|---|---|---|---|---|---|---|---|---|---|
| D0 any season | 68.6 | 93.8 | 77.8 | 0.31 | 71.3 | 0.34 | 72.3 | 61.5 | 16.16 |
| D1 any season | 53.3 | 93.8 | 82.9 | 0.20 | 58.2 | 0.24 | 53.4 | 51.6 | 15.76 |
| D2 CV>0.5 | 16.1 | 92.4 | 93.5 | 0.04 | 16.1 | 0.04 | 8.8 | 26.9 | 1.11 |
| D2 oracle | 53.7 | 92.0 | 77.5 | 0.17 | 50.3 | 0.15 | 49.8 | 61.8 | 13.85 |
| D2 matched FAR | 55.9 | 92.0 | 76.2 | 0.18 | 52.4 | 0.16 | 52.5 | 63.6 | 16.16 |
| D2n CV>0.5 | 15.2 | 92.0 | 93.6 | 0.03 | 15.3 | 0.04 | 8.6 | 25.1 | 0.80 |
| D2n oracle | 80.1 | 87.6 | 44.9 | 0.21 | 78.7 | 0.20 | 80.1 | 82.8 | 23.70 |
| D2n matched FAR | 71.3 | 88.3 | 54.0 | 0.18 | 69.5 | 0.17 | 69.4 | 76.2 | 16.16 |

## All region-seasons (115 region-seasons in 60 regions)

D1 national thresholds: winter -11.45 dB raw HV, summer -13.85 dB raw HV.

| Season | Detector | Recall (area) | Precision (area) | Specificity (area) | κ (area) | Recall (count) | Precision (count) | κ (count) | Desert FAR % | Held-out FAR % |
|---|---|---|---|---|---|---|---|---|---|---|
| winter | D0 | 39.8 | 66.9 | 78.9 | 0.18 | 41.2 | 69.0 | 0.23 | 9.20 | 9.31 |
| winter | D0-1dB | 54.4 | 62.4 | 64.9 | 0.19 | 53.3 | 64.0 | 0.24 | 18.09 |  |
| winter | D0+1dB | 31.9 | 70.5 | 85.7 | 0.17 | 34.6 | 72.7 | 0.22 | 5.91 |  |
| winter | D1 | 8.6 | 53.2 | 91.9 | 0.00 | 9.2 | 50.9 | 0.00 | 9.20 | 9.23 |
| winter | D1r | 38.9 | 68.5 | 80.8 | 0.19 | 40.6 | 69.9 | 0.23 | 8.95 |  |
| summer | D0 | 49.1 | 93.8 | 87.4 | 0.22 | 45.7 | 93.2 | 0.18 | 10.43 | 10.55 |
| summer | D0-1dB | 62.1 | 88.6 | 69.0 | 0.22 | 56.1 | 88.1 | 0.17 | 20.10 |  |
| summer | D0+1dB | 36.5 | 95.0 | 92.5 | 0.15 | 35.3 | 94.1 | 0.14 | 6.94 |  |
| summer | D1 | 21.4 | 98.1 | 98.4 | 0.09 | 21.9 | 96.0 | 0.08 | 10.43 | 10.49 |
| summer | D1r | 45.6 | 94.1 | 88.9 | 0.20 | 43.0 | 93.5 | 0.17 | 9.66 |  |

- Winter: 73,577 field-seasons (862,691 ha; 51.7% of the area green in Sentinel-2), 957,598 desert patches. Held-out D0 FAR (threshold fitted on the other half): random half 9.31%, halves swapped 9.09%, 1.6 km spatial blocks 9.19%; on WorldCover-bare patches only, in-sample 8.84%.
- Summer: 79,945 field-seasons (931,446 ha; 79.5% of the area green in Sentinel-2), 1,011,065 desert patches. Held-out D0 FAR (threshold fitted on the other half): random half 10.55%, halves swapped 10.30%, 1.6 km spatial blocks 10.49%; on WorldCover-bare patches only, in-sample 10.31%.

**Per year** (79,203 fields with ≥ 4 radar dates in 60 regions; 2,599 fields with fewer dates left out). Median CV: farmed fields 0.205, of which green in both seasons 0.194; not-green fields 0.14; desert patches 0.146 (normalised: farmed 0.17, desert 0.069). CV cuts: oracle 0.198, matched 0.312; D2n oracle 0.095, matched 0.280.

| Detector | Recall (area) | Precision (area) | Specificity (area) | κ (area) | Recall (count) | κ (count) | Recall: green both seasons | Recall: green one season | Desert FAR % |
|---|---|---|---|---|---|---|---|---|---|
| D0 any season | 52.4 | 94.9 | 79.6 | 0.13 | 48.5 | 0.11 | 63.1 | 42.9 | 12.40 |
| D1 any season | 23.4 | 98.3 | 97.1 | 0.06 | 24.1 | 0.06 | 19.5 | 28.2 | 15.52 |
| D2 CV>0.5 | 17.5 | 92.5 | 89.7 | 0.02 | 16.9 | 0.02 | 14.6 | 21.7 | 8.32 |
| D2 oracle | 54.0 | 93.4 | 72.1 | 0.11 | 52.2 | 0.10 | 53.4 | 56.7 | 24.53 |
| D2 matched FAR | 31.1 | 93.2 | 83.5 | 0.05 | 30.0 | 0.04 | 27.5 | 35.7 | 12.40 |
| D2n CV>0.5 | 15.7 | 92.0 | 90.1 | 0.02 | 14.9 | 0.01 | 13.3 | 19.3 | 6.71 |
| D2n oracle | 80.0 | 91.4 | 45.4 | 0.18 | 78.1 | 0.15 | 78.5 | 83.5 | 35.03 |
| D2n matched FAR | 29.9 | 92.1 | 81.4 | 0.04 | 29.4 | 0.03 | 27.2 | 33.5 | 12.40 |

## Where each detector wins

Area-weighted κ against Sentinel-2, with the share of the region's desert patches each detector calls active in brackets (FAR %). D1 and D2m use the national cuts fitted on the QC-passing pool, applied to every region (the cuts fitted on all region-seasons are in the JSON); per region they are not matched to D0's false-alarm rate. Flags: SW = southwest (Jazan, Asir, Najran, Al Bahah; majority of field area), DUNE = dune texture in the desert background, SEA = at least 5% of desert patches are water. QC: ✓ pass, ✗ fail, · season not observed. Thr = D0 threshold. Year FAR = desert patches called active in at least one season. Winner by κ (tie if within 0.02; n/a when Sentinel-2 has fewer than 20 fields in one class); * = the winner flags more than 1 point more of this region's desert than D0 does.

| Region | Admin | Flags | QC W/S | Thr W/S dB | Fields | Winter κ D0/D1 (FAR %) | Summer κ D0/D1 (FAR %) | Year κ D0/D2/D2m (FAR % D0/D2m) | Winner W / S | Winner year |
|---|---|---|---|---|---|---|---|---|---|---|
| R01 | Jazan | SW | ✗/✗ | 8.0/10.1 | 9,060 | 0.13/0.01 (2/63) | 0.00/0.25 (1/54) | 0.00/0.00/0.00 (2/12) | D0 / D1* | D1* |
| R02 | Al Jawf |  | ✓/✓ | 2.9/1.8 | 3,603 | 0.57/0.57 (4/4) | 0.67/0.57 (8/6) | 0.63/0.17/0.54 (9/7) | tie D1=D0 / D0 | D0 |
| R03 | Jazan | SW SEA | ✗/✗ | 8.0/7.8 | 3,716 | -0.08/0.01 (13/43) | 0.12/0.13 (14/35) | 0.06/0.00/-0.01 (16/30) | D1* / tie D1=D0 | D1* |
| R04 | Riyadh |  | ✓/✓ | 1.6/2.2 | 2,646 | 0.31/0.06 (16/5) | 0.55/0.02 (13/3) | 0.05/-0.01/0.00 (22/19) | D0 / D0 | D0 |
| R05 | Riyadh | DUNE | ✓/✓ | 2.1/1.1 | 2,059 | 0.38/0.30 (23/15) | 0.69/0.29 (30/15) | 0.54/0.06/0.22 (30/2) | D0 / D0 | D0 |
| R06 | Al-Qassim |  | ✓/✓ | 3.5/2.6 | 2,050 | 0.31/0.34 (4/7) | 0.44/0.54 (8/12) | 0.24/0.04/0.15 (8/25) | D1* / D1* | D1* |
| R07 | Al Jawf |  | ✓/✓ | 3.4/1.5 | 1,389 | 0.21/0.18 (19/47) | 0.31/0.30 (22/23) | 0.24/0.08/0.20 (32/22) | D0 / tie D0=D1 | tie D0=D1 |
| R08 | Al-Qassim | DUNE | ✓/✓ | 5.1/4.8 | 2,398 | 0.41/0.42 (18/30) | 0.30/0.41 (19/31) | 0.22/0.00/0.03 (20/10) | tie D1=D0 / D1* | D1* |
| R09 | Hayel |  | ✓/✓ | 2.8/2.7 | 2,203 | 0.01/-0.09 (9/3) | 0.40/0.15 (10/3) | 0.37/0.05/0.22 (12/18) | D0 / D0 | D0 |
| R10 | Al Jawf |  | ✗/✓ | 41.4/1.4 | 1,636 | 0.00/-0.07 (0/66) | 0.50/0.14 (14/8) | 0.28/-0.07/-0.01 (14/74) | D0 / D0 | D0 |
| R11 | Al-Qassim |  | ✓/✓ | 1.2/1.7 | 2,097 | 0.39/0.34 (18/11) | 0.57/0.46 (15/11) | 0.40/0.08/0.27 (19/5) | D0 / D0 | D0 |
| R12 | Riyadh |  | ✗/✗ | 34.3/18.3 | 1,353 | 0.00/0.00 (0/38) | 0.00/0.11 (0/1) | 0.00/-0.01/-0.02 (0/56) | tie D1=D0 / D1 | tie D0=D2=D2m |
| R13 | Hayel |  | ✓/✓ | 3.2/3.1 | 1,556 | -0.06/-0.04 (8/7) | 0.11/0.07 (9/7) | 0.03/0.02/0.05 (10/4) | D1 / D0 | D2m |
| R14 | Eastern |  | ·/✓ | ·/1.3 | 1,873 | · | 0.72/0.52 (6/3) | 0.78/0.01/0.20 (7/0) | · / D0 | D0 |
| R15 | Riyadh |  | ✗/✓ | 34.1/1.4 | 1,464 | 0.00/0.29 (0/70) | 0.49/0.10 (28/20) | 0.19/0.06/-0.03 (28/67) | D1* / D0 | D0 |
| R16 | Jazan | SW SEA | ✓/✓ | 1.2/0.8 | 1,513 | 0.00/0.15 (21/9) | 0.20/0.33 (23/9) | 0.00/0.00/0.00 (25/2) | D1 / D1 | D1 |
| R17 | Riyadh |  | ·/✗ | ·/8.1 | 1,876 | · | 0.01/0.29 (4/46) | 0.01/0.01/0.07 (4/0) | · / D1* | D1* |
| R18 | Tabuk |  | ✓/✓ | 1.8/1.7 | 951 | -0.04/-0.04 (20/19) | 0.22/0.47 (21/41) | 0.14/0.03/0.24 (21/94) | tie D1=D0 / D1* | D1* |
| R19 | Al Jawf |  | ✓/✓ | 3.2/0.8 | 1,618 | 0.00/0.01 (2/3) | 0.76/0.16 (7/2) | 0.56/0.05/0.12 (8/8) | tie D1=D0 / D0 | D0 |
| R20 | Al Jawf |  | ✓/✓ | 4.4/1.6 | 1,348 | -0.14/-0.15 (19/32) | 0.17/0.07 (22/19) | 0.01/-0.08/-0.10 (35/50) | tie D0=D1 / D0 | D0 |
| R21 | Jazan | SW SEA | ✗/✗ | 8.0/8.1 | 778 | 0.24/0.12 (7/36) | 0.06/0.32 (6/39) | 0.03/0.00/0.00 (7/6) | D0 / D1* | D1* |
| R22 | Riyadh | DUNE | ✓/✓ | 2.4/2.0 | 1,036 | 0.10/0.03 (14/5) | 0.66/0.13 (18/6) | 0.16/0.01/0.07 (19/3) | D0 / D0 | D0 |
| R23 | Al Jawf |  | ✓/✓ | 1.5/1.6 | 2,642 | -0.06/-0.08 (6/1) | 0.34/0.19 (2/1) | 0.24/0.04/0.23 (7/8) | tie D0=D1 / D0 | tie D0=D2m |
| R24 | Al Jawf |  | ✓/✓ | 3.8/4.0 | 1,765 | -0.02/-0.11 (6/35) | 0.04/0.10 (14/40) | 0.02/0.03/0.09 (14/26) | D0 / D1* | D2m* |
| R25 | Tabuk |  | ✓/✓ | 3.7/4.4 | 744 | 0.02/0.05 (20/34) | 0.05/0.19 (18/47) | 0.02/0.02/0.12 (20/31) | D1* / D1* | tie D2m=D1* |
| R26 | Hayel |  | ✓/✓ | 1.0/1.5 | 1,081 | 0.10/0.03 (11/3) | 0.35/0.24 (8/4) | 0.16/0.03/0.10 (12/3) | D0 / D0 | D0 |
| R27 | Hayel | DUNE | ✓/✓ | 2.6/2.2 | 1,197 | 0.05/0.05 (20/16) | 0.28/0.13 (21/14) | 0.17/0.05/0.13 (20/4) | tie D0=D1 / D0 | D0 |
| R28 | 'Asir | SW | ✗/✗ | 8.8/6.7 | 2,106 | 0.21/0.00 (2/99) | 0.00/0.01 (1/99) | 0.00/0.00/0.00 (3/25) | D0 / tie D1=D0 | n/a |
| R29 | Riyadh |  | ✗/✓ | 32.7/3.7 | 718 | 0.00/0.25 (0/84) | 0.09/0.13 (23/31) | 0.01/0.01/-0.01 (23/79) | D1* / D1* | D1* |
| R30 | Eastern |  | ✓/✓ | 2.1/2.1 | 983 | 0.09/0.11 (4/7) | 0.28/0.30 (6/14) | 0.05/0.00/0.03 (7/5) | D1* / tie D1=D0 | tie D1=D0 |
| R31 | Al-Qassim |  | ✓/✓ | 1.3/1.6 | 534 | 0.15/0.14 (12/1) | 0.57/0.30 (11/1) | 0.23/0.08/0.32 (14/17) | tie D0=D1 / D0 | D2m* |
| R32 | 'Asir | SW | ✗/✗ | 7.7/6.2 | 1,469 | 0.06/0.00 (4/99) | 0.00/0.00 (1/99) | 0.00/0.00/0.00 (4/21) | D0 / tie D0=D1 | n/a |
| R33 | Al-Qassim | DUNE | ✓/✓ | 2.9/3.4 | 828 | 0.25/0.23 (14/11) | 0.36/0.32 (14/12) | 0.28/0.01/0.12 (15/2) | tie D0=D1 / D0 | tie D0=D1 |
| R34 | Al-Qassim |  | ✓/✓ | 2.5/3.8 | 736 | 0.59/0.61 (19/13) | 0.54/0.54 (11/15) | 0.31/0.00/-0.06 (19/20) | D1 / tie D1=D0 | D1 |
| R35 | Hayel |  | ✓/✓ | 2.1/1.5 | 825 | 0.18/0.19 (10/9) | 0.50/0.36 (15/11) | 0.32/0.03/0.30 (15/12) | tie D1=D0 / D0 | D0 |
| R36 | Al-Qassim |  | ✓/✓ | 2.5/2.2 | 723 | 0.11/0.11 (4/4) | 0.24/0.30 (8/10) | 0.14/0.03/0.42 (8/16) | tie D0=D1 / D1* | D2m* |
| R37 | Riyadh | DUNE | ✓/✓ | 3.1/2.3 | 593 | 0.21/0.13 (8/4) | 0.67/0.21 (12/5) | 0.31/0.06/0.17 (12/12) | D0 / D0 | D0 |
| R38 | Eastern |  | ·/✓ | ·/1.6 | 1,154 | · | 0.59/0.19 (2/1) | 0.70/0.02/0.30 (2/0) | · / D0 | D0 |
| R39 | Al-Qassim | DUNE | ✓/✓ | 2.7/2.5 | 912 | 0.30/0.32 (12/10) | 0.40/0.33 (12/10) | 0.29/0.01/0.10 (13/4) | tie D1=D0 / D0 | D0 |
| R40 | Al-Qassim |  | ✓/✓ | 1.3/1.6 | 536 | 0.43/0.35 (12/2) | 0.71/0.39 (8/3) | 0.56/0.09/0.34 (13/46) | D0 / D0 | D0 |
| R41 | Eastern |  | ·/✓ | ·/4.5 | 990 | · | 0.34/0.60 (21/33) | 0.34/0.00/0.00 (21/0) | · / D1* | D1* |
| R42 | 'Asir | SW | ✗/✗ | 5.8/5.6 | 4,242 | 0.21/0.00 (5/100) | 0.00/0.00 (1/99) | 0.00/0.00/0.00 (5/11) | D0 / tie D0=D1 | tie D2m=D0=D1=D2 |
| R43 | Al Jawf |  | ✓/✗ | 3.8/4.3 | 769 | 0.05/-0.06 (10/38) | 0.04/0.40 (8/65) | 0.03/0.02/0.22 (10/63) | D0 / D1* | D1* |
| R44 | Makkah |  | ✗/✗ | 11.2/12.6 | 363 | 0.00/0.00 (0/70) | 0.00/0.21 (0/74) | 0.00/0.00/0.00 (0/3) | tie D0=D1 / n/a | n/a |
| R45 | Al Bahah | SW | ✗/✗ | 12.2/4.8 | 715 | -0.03/0.00 (3/100) | 0.02/0.00 (4/100) | 0.00/0.00/0.00 (5/56) | D1* / D0 | n/a |
| R46 | Al Jawf |  | ✓/✓ | 3.6/4.3 | 337 | 0.13/0.19 (9/30) | 0.07/0.22 (9/34) | 0.04/0.02/0.17 (9/14) | D1* / D1* | tie D2m=D1* |
| R47 | 'Asir | SW | ✗/✗ | 5.9/4.0 | 639 | 0.18/0.00 (9/100) | 0.01/0.00 (2/100) | 0.00/0.00/0.00 (10/23) | D0 / tie D0=D1 | n/a |
| R48 | Al-Qassim |  | ✓/✓ | 1.2/1.9 | 484 | 0.17/0.15 (15/9) | 0.33/0.27 (13/11) | 0.21/0.02/0.15 (16/5) | tie D0=D1 / D0 | D0 |
| R49 | Tabuk |  | ✓/✓ | 1.3/1.2 | 428 | 0.19/0.10 (9/3) | 0.32/0.09 (11/7) | 0.16/0.00/0.07 (11/16) | D0 / D0 | D0 |
| R50 | Hayel |  | ✓/✓ | 2.3/1.7 | 507 | 0.01/0.03 (3/2) | 0.51/0.36 (5/3) | 0.26/0.13/0.36 (5/8) | D1 / D0 | D2m* |
| R51 | Riyadh | DUNE | ✓/✓ | 2.5/3.2 | 743 | 0.23/0.16 (13/5) | 0.44/0.32 (15/8) | 0.11/0.00/0.03 (17/48) | D0 / D0 | D0 |
| R52 | 'Asir | SW | ✗/✗ | 11.3/6.6 | 601 | 0.02/0.00 (1/99) | 0.00/0.00 (2/99) | 0.00/0.00/0.00 (2/50) | D0 / n/a | n/a |
| R53 | Al Madinah |  | ·/✗ | ·/16.7 | 729 | · | 0.00/0.27 (0/77) | 0.00/0.00/0.16 (0/60) | · / D1* | D1* |
| R54 | Makkah |  | ✗/✗ | 5.8/4.7 | 204 | -0.06/0.00 (5/100) | -0.01/0.00 (2/100) | 0.00/0.00/-0.02 (5/36) | D1* / tie D1=D0 | n/a |
| R55 | Al Bahah | SW | ✗/✗ | 15.1/4.6 | 205 | -0.01/0.00 (0/100) | 0.23/0.06 (19/59) | 0.03/0.00/-0.01 (19/93) | tie D1=D0 / D0 | n/a |
| R56 | Riyadh |  | ✗/✗ | 13.8/12.7 | 424 | 0.00/0.00 (0/100) | 0.00/0.86 (0/95) | 0.00/0.04/-0.02 (0/86) | n/a / n/a | n/a |
| R57 | 'Asir | SW | ✗/✗ | 4.2/3.2 | 368 | -0.27/0.00 (7/100) | 0.01/0.00 (3/100) | 0.00/0.00/-0.01 (7/8) | D1* / tie D0=D1 | n/a |
| R58 | Riyadh |  | ✓/✓ | 2.5/2.6 | 366 | 0.18/0.15 (14/12) | 0.38/0.28 (17/14) | 0.12/0.00/0.03 (17/5) | D0 / D0 | D0 |
| R59 | Najran | SW DUNE | ✗/✗ | 16.5/19.6 | 396 | 0.00/0.02 (0/72) | 0.00/0.12 (0/73) | 0.00/0.00/0.00 (0/19) | tie D1=D0 / n/a | n/a |
| R60 | Riyadh | DUNE | ✓/✓ | 3.6/4.1 | 524 | 0.32/0.32 (16/15) | 0.35/0.34 (16/16) | 0.22/0.00/0.00 (17/23) | tie D0=D1 / tie D0=D1 | D0 |

**By group** (pooled within the group; area κ; D1 with the QC-fitted / all-fitted national thresholds; 'QC pass' rows keep only region-seasons that pass the quality check):

| Group | Regions | Winter κ D0 / D1qc / D1all | Summer κ D0 / D1qc / D1all | Year κ D0 / D2 / D2m | Desert FAR % D0 / D1qc, winter; summer |
|---|---|---|---|---|---|
| Southwest | 13 | 0.17 / 0.01 / 0.11 | 0.00 / 0.18 / 0.01 | 0.00 / 0.00 / 0.00 | 6.2 / 78.9; 6.3 / 75.7 |
| Dune | 10 | 0.26 / 0.23 / 0.00 | 0.47 / 0.30 / 0.03 | 0.25 / 0.03 / 0.11 | 13.8 / 15.9; 16.1 / 16.5 |
| Other | 38 | 0.16 / 0.19 / 0.02 | 0.37 / 0.26 / 0.03 | 0.23 / 0.05 / 0.22 | 8.7 / 32.5; 10.2 / 30.1 |
| Dune, QC pass | 9 | 0.27 / 0.23 / 0.00 | 0.49 / 0.29 / 0.03 | 0.27 / 0.03 / 0.11 | 14.9 / 11.7; 17.3 / 12.2 |
| Other, QC pass | 32 | 0.23 / 0.14 / 0.00 | 0.43 / 0.25 / 0.03 | 0.31 / 0.04 / 0.22 | 11.5 / 13.9; 12.8 / 15.7 |

## Context

- Desert median HV, QC-passing winters: median -23.82 dB (range -27.09 to -21.84, IQR -24.61 to -23.24; n = 36).
- Desert median HV, QC-passing summers: median -22.94 dB (range -26.43 to -20.99, IQR -23.84 to -22.22; n = 41).
- Desert median HV, all winters: median -23.25 dB (range -27.09 to -11.43, IQR -24.32 to -19.15; n = 55).
- Desert median HV, all summers: median -22.44 dB (range -26.43 to -14.04, IQR -23.38 to -21.14; n = 60).
- Summer minus winter desert median (regions passing QC in both seasons): median 0.93 dB (range 0.06 to 2.04, IQR 0.59 to 1.22; n = 35).
- Within a season, desert medians move by 0.52 dB between dates (median; max 1.67 dB) in QC-passing region-seasons.

## Caveats

- Sentinel-2 greenness (field median of the seasonal maximum NDVI > 0.40) is a reference, not ground truth: winter crops that green after the late-November to January radar dates, weedy fallow, rain-greened natural vegetation in the southwest and palms/orchards all blur it. Summer is lopsided (most mapped fields are green), so summer κ moves a lot with small changes in specificity.
- Desert patches are the pipeline's own 320 m blocks at least 400 m from any mapped field. They are mostly bare (WorldCover), but include rock outcrops, dunes, roads, some built-up land, unmapped small plots and, on the Jazan coast, sea (R03, R16, R21 have ≥ 5% water patches). D0's false-alarm rate on WorldCover-bare patches only is 12.3% vs 13.0% on all (QC winter).
- Patches are 10.24 ha; fields range from 3 ha to several hundred. A small field's mean is noisier than a patch mean, so the false-alarm rate for small fields is likely above the patch rate, and below it for large pivots.
- D1's thresholds are matched to D0's pooled rate in-sample by construction; on the held-out half the two rates stay within 0.01 / 0.05 points (winter / summer). Pooled rates weight regions by their desert area, so per-region rates differ a lot (table above): a national raw threshold concentrates its false alarms in bright-desert regions and has almost none on dark sand.
- CV uses only 4-7 dates (3 between late November and January, 4 in June-October; summer-only regions have 4), far sparser than the 12-day series the NISAR crop-area rule (CV > 0.5) was designed for, and is computed on field means (not pixels) with the population standard deviation (a sample std would raise CV by 8-15%, not enough to change the ranking). Between-season calibration steps inflate desert CV, which D2n removes.
- The QC rule is the project's (a date's desert median ≤ −21 dB and threshold ≤ 6 dB), applied to the values in meta.json. Outside the southwest (where only R16 W, R16 S pass) it rejects region-seasons whose desert is brighter than −21 dB on every date (R10 W, R15 W, R29 W, R43 S, R44 W, R44 S, R53 S, R54 W, R54 S, R56 W, R56 S: Shield and limestone ground, or anomalously bright scenes) or whose threshold exceeds 6 dB (R10 W, R12 W, R12 S, R15 W, R17 S, R29 W, R44 W, R44 S, R53 S, R56 W, R56 S; in R12 a dark swath-edge strip inside the desert mask inflates it).
- Dune flags come from visual inspection of the HV images (dune texture in the desert background), R05 and R22 being the least certain; 'southwest' is the majority admin region of the field centres (the project's own list).
- Fields mapped by two overlapping regions are scored in each region, as the pipeline validates per region: 6,274 of 81,803 fields (7.7%) belong to another region under the national table's de-duplication rule. Dropping them barely moves the result (QC summer area κ D0 0.45, D1 0.26).
- Per-region κ is unstable where Sentinel-2 is one-sided (e.g. southwest summers where nearly every mapped field is green); the winner is then marked n/a. Ties use a 0.02 κ margin.
- All numbers come from the stored region outputs at run time. Another session may re-run parts of the pipeline; the reproduction check (thresholds, desert medians, field values, D0 calls) is recomputed on every run and would show any region that changed mid-run.

## Reproduction check

Desert medians, thresholds and field values were recomputed from the stored HV rasters on the pipeline's grid with its reprojection: grids match for 60/60 regions, thresholds for 115/115 region-seasons (to 0.01 dB), desert medians to 0.0e+00 dB, field HV to 0.0e+00 dB, and D0 reproduces the stored field calls for 100.000% of 153,553 field-seasons. Deterministic: fixed seed 20261115 for the patch splits, no other randomness.

