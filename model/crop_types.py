"""Per-field crop-type record (v2) from the Landsat 8/9 NDVI time series, with NISAR radar as side evidence.

Input per region (data/regions/<R>/): landsat_ndvi.csv.gz (scripts/landsat_fields.py: one row per field and clear
look, Aug 2025 - Nov 2026, 40 m interior-pixel median NDVI), landsat_fieldinfo.csv (pixel counts), fields_radar.csv
(centroids, v1 flags), hv_timeseries.csv + meta.json (NISAR HV per field and date, quality-check inputs), and the 40 m
optical cache data/landsat/<R>/*_o.tif (only for the split-pivot check). The method follows the crop-types critique
of the v2 plan (cycle timing on 15 months of data, not monthly thresholds).

1. Clean the looks (despiked raw series)
   haze    Landsat's qa_pixel misses dust and thin cloud: on some dates every green field in part of the box reads
           15-50% low (R04: 14 Aug 2025, 21 May 2026). For each date, 'stable green' fields (previous and next looks
           within 24 d, both >= 0.5 and within 0.10 of each other) give a ratio look / interpolated expectation. A
           look is dropped when the median ratio of the 12 nearest stable-green fields within 5 km (>= 8 of them,
           else the box median) is below 0.88 and the look itself is below 0.95 of its own expectation. On clean
           R04 dates the box median ratio stays within 0.92-1.16 (atmospheric-correction noise), so 0.88 sits
           below that band; a cut is one field's own dip and cannot move its neighbours' median.
   spike   the critique's rule: drop a look >= 0.20 below both neighbours when both are within 6 days (NDVI cannot
           fall and recover 0.2 in 6 days). It only acts where two WRS paths overlap; at the 8-day single-path
           cadence a one-look dip is a plausible cut and is kept.
2. Smooth: kept looks are binned to a 5-day grid (1 Aug 2025 - 15 Nov 2026) and fitted with a weighted Whittaker
   smoother (2nd differences, lambda 15: half-power period ~60 d, so crop cycles of 70+ d keep their shape and
   the ~25-30 d cut rhythm is smoothed away), refitted 3 times against the upper envelope (Chen et al. 2004:
   looks below the fit are replaced by the fit), because residual cloud, dust and cuts only ever lower NDVI.
3. Cycles on the smoothed series: green-up = upward crossing of 0.40; end = downward crossing of 0.30 (the
   hysteresis keeps noise around one threshold from splitting a cycle). A cycle that never falls below 0.30 is
   split at a valley <= 0.40 lying >= 0.20 below both flanking peaks (harvest then quick re-sowing; the 0.40 cap
   keeps the summer slump of perennial alfalfa, whose envelope valleys sit at 0.40-0.50, in one cycle). After such
   a valley the new cycle's green-up is the first regrowth 0.10 above the valley. Cycles separated by < 20 d whose
   gap never went below 0.25 and whose dip is shallower than 0.20 are merged (the critique's 'at least 20 days
   below 0.25 or a local minimum' green-up condition). A cycle must peak >= 0.45 and last >= 40 d unless cut off
   by the window edge. Crossing dates are interpolated between grid nodes. A cycle belongs to the 2025/26 season
   year if its green-up is 1 Sep 2025 - 31 Aug 2026, or it began earlier (or before the record) and lasted past
   1 Dec 2025; later cycles (autumn 2026 sowings) are kept in the plot but not in the label.
4. Cuts on the despiked raw looks: a local minimum >= 0.15 below the highest look of the previous 17 d (one or two
   8-day looks; the critique's 10 d assumes HLS cadence) that itself was >= 0.45 (an established canopy), followed
   by a recovery >= 0.15 within 25 d. Landsat alone sees about a third to a half of the cuts (a cut's dip lasts
   10-15 d), so counts are lower bounds and cut_interval_d is an upper bound.
5. Per-field features over the season year 1 Nov 2025 - 31 Oct 2026: n_looks, max gap, days_green (smoothed
   >= 0.40), longest_bare_d (longest run of smoothed < 0.25), amplitude (p95 - p5 of looks), p5, mean,
   frac_ge035 (share of looks >= 0.35), summer_green (share of Jun-Sep looks >= 0.40), low2 (the lowest level two
   consecutive looks <= 17 d apart both stay at or below: a cut is one low look, a harvest break several), cuts.
6. Rule ladder (first match wins; rule = 'strict' when the critique's tests or windows hold, 'loose' for fallbacks)
   insufficient_data  < 12 looks in the season year or a gap > 64 d (8 missed overpasses) between looks
   tree_crop          no bare run > 30 d, p5 >= 0.18, amplitude < 0.25, mean 0.22-0.60 (palms, olives, orchards:
                      open evergreen canopy that is never bare and never dense); deciduous = Dec-Feb median >= 0.15
                      below Jun-Aug; windbreak = minor axis < 3 px (120 m) or eccentricity > 0.95
   perennial_forage   strict: longest bare run <= 40 d, >= 80% of looks >= 0.35, >= 60% of Jun-Sep looks >= 0.40
                      (critique 70%: at the 8-day cadence a third or more of summer looks of a heavily cut alfalfa
                      field fall in a post-cut dip), and >= 3 cuts or amplitude >= 0.30. stand = established.
                      loose (a) green 9+ months: bare run <= 60 d, days_green >= 270, mean > 0.45, low2 >= 0.30;
                      stand = established. (b) a 'long' season cycle covering summer (green-up by 15 Jun, end from
                      1 Sep) or a lone 'long' cycle: stand = new (green-up after 30 Nov 2025), ended (end before
                      1 Oct 2026), within (both) or established. new = a stand sown in the season (often after a
                      winter crop), ended = a stand ploughed out in the season; both matter for the MEWA halt baseline
                      (perennial in summer 2026 = stand established or new). One season cannot separate a new
                      perennial stand from a long summer fodder; stand age needs the 2024/25 or 2026/27 season.
   then each in-season cycle is typed by its dates. Zones shift the winter peak / end windows: south (< 24 N, R04:
   winter cycles end Feb-Apr) -14 d, centre (24-28 N) 0, north (> 28 N: frost, harvest 2-4 weeks later) +21 d.
     winter_fodder    green-up Oct-Dec, >= 2 cuts, ends by 30 Jun (berseem, ryegrass, green barley)
     winter_cereal    green-up 15 Oct - 15 Jan, peak 15 Jan - 31 Mar at >= 0.60, end 15 Mar - 15 Jun, 80-180 d
                      (critique: end from 10 Apr, 110-180 d; here 'end' is the 0.30 crossing at senescence, 2-4
                      weeks before harvest, so the green cycle of wheat is 80-120 d)
     autumn_crop      green-up Aug-Oct, end Dec-Feb (autumn potato, vegetables)
     spring_crop      green-up Jan-Mar, end May-Jul
     summer_crop      green-up May-Aug, 70-140 d
     long             >= 200 d long, or green since before Aug 2025 and still green after 31 Jan, and >= 0.40 for
                      >= 60% of its length (a forage stand)
     loose fallbacks by green-up date: before 15 Oct and ending by 15 Mar = autumn; 1 Oct - 15 Jan = winter
     (fodder with >= 2 cuts, else cereal); 15 Jan - 30 Apr = spring; May-Aug = summer; anything left (weak or
     censored cycles) by its peak date: before Dec = autumn, Dec-Mar = winter, Apr = spring, later = summer
   field label: no in-season cycle = fallow (a mapped field with no cycle this year; land never green is not in
   the field mask, so this is not a fallow-land census); one cycle = its type; exactly two cycles, one winter and
   one summer-side (summer_crop, or a spring_crop peaking from May: summer crops sown in Mar-Apr after an early
   wheat harvest) = double_crop; any other 2+ cycles = multi_cycle. cycle_seq keeps the full sequence.
7. Size tiers (critique): reliable = >= 5 ha or >= 20 interior 40 m pixels; provisional = >= 3 ha or >= 5;
   edge_mixed = smaller (NDVI from all pixels, mixed with the field edge; confidence capped at low).
8. Radar (NISAR HV), only as two physical flags and only where national_supply.season_ok(meta, se, qc=True):
   a date is 'on' when hv_norm exceeds a per-region, per-season threshold recalibrated against optical green
   (look >= 0.5) versus bare (< 0.25) within 6 days (Youden's J on even field ids, AUC on odd ids; the v1 desert
   threshold when either class has < 30 samples). A season whose test AUC is below 0.65 is not used at all
   (HV then cannot tell green from bare, so its flags would be noise).
     radar_winter_canopy   on for >= 2 of the Dec-Jan dates (False when >= 2 are off; else unknown)
     radar_summer_persist  on for >= 3 of the summer dates (False when >= 2 are off; else unknown)
   radar_agree tests only what the radar can see: tree_crop expects both on; perennial_forage expects winter on
   for established / ended stands and summer on for established / new stands (off for a stand ended before 1 Aug
   with no later cycle); fallow expects both off; winter_cereal, winter_fodder,
   autumn_crop and spring_crop expect summer off; summer_crop expects winter off; double_crop and multi_cycle are
   not tested (NaN), nor is any field without radar. It is evidence, not a confidence input: radar coverage is
   not accuracy (18 boxes have no usable radar season).
9. Stability: label again with Landsat 8 looks only and Landsat 9 looks only (disjoint dates, 16 days apart each;
   label_l8, label_l9, split_half_agree) and in 20 temporal bootstrap runs dropping a random 40% of dates
   (stability = share of runs giving the full-series label). confidence: high = stability >= 0.9, strict rule,
   >= 30 looks and reliable tier; medium = stability >= 0.7 and not edge_mixed; else low.
10. Split pivots: fields with >= 4 angular sectors (60 deg around the centroid) of >= 8 interior pixels are
   relabelled per sector from the 40 m cache (mean NDVI of clear interior pixels, the parent field's dropped looks
   dropped too, same rules). split_share = interior-pixel share of the majority sector label; sector_spread =
   median over season dates of the range of sector NDVI; split_flag = split_share < 0.7 and spread >= 0.10 (a
   label disagreement between sectors with near-identical series is a rule-boundary effect, not a split);
   perennial_share = share of interior pixels in perennial_forage sectors (the halt baseline for split pivots);
   sector_classes lists the sector label shares. The field's own label still comes from its whole-field series.
11. Cross-check: ndvi_spring_ls = median look 20 Apr - 5 Jun (scripts/s2_spring.py window); < 0.30 is compared
   with the Sentinel-2 spring_brown flag in the summary line.

Outputs  data/regions/<R>/crop_types.csv (all fields of the label raster) and, with 'all', the national table
         data/national/v2/crop_types.csv: regions with a Landsat table, joined to data/national/fields_national.csv on
         (region, id), so only published (de-duplicated) fields are kept.
Usage    .venv/bin/python model/crop_types.py R04 [R05 ...] [--plot out.png] [--summary stats.json]
         .venv/bin/python model/crop_types.py all [--force] [--summary stats.json]
         ('all' reuses a region's csv when it is newer than its Landsat table and this file, unless --force or
         --summary; --plot draws example profiles per class for a single region; --summary writes per-region
         radar calibration, L8/L9 kappa, stability, areas and dropped looks per date)
"""
import os

for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_k, "2")  # small 95 x 95 algebra; keep CPU moderate next to the Landsat fetch

import json  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
import warnings  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import rasterio  # noqa: E402
from scipy import ndimage as ndi  # noqa: E402
from scipy.spatial import cKDTree  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "model"))
import national_supply as NS  # noqa: E402  (season_ok only)

warnings.filterwarnings("ignore", message="All-NaN slice")      # fields with no look in a window: NaN is the answer
warnings.filterwarnings("ignore", message="Mean of empty slice")

D = np.datetime64
T0, T1 = D("2025-08-01"), D("2026-11-15")          # data window = scripts/landsat_c2.py SEASON
SY0, SY1 = D("2025-11-01"), D("2026-10-31")        # season year (the NISAR record)
STEP = 5                                           # grid spacing (days)
GRID = np.arange(0, int((T1 - T0).astype(int)) + 1, STEP)
LAM, ENV_ITERS = 15.0, 3                           # Whittaker lambda on the 5-day grid; upper-envelope refits
GREEN, BARE, END = 0.40, 0.25, 0.30                # green-up / bare / end-of-cycle NDVI
MIN_PEAK, MIN_CYCLE_D = 0.45, 40                   # a real cycle: clearly green, longer than a weed flush
VALLEY_MAX, VALLEY_DEPTH = 0.40, 0.20              # split a cycle at a deep valley (harvest + re-sowing)
REGROW = 0.10                                      # green-up after a valley = first regrowth 0.10 above it
LONG_D, LONG_GREEN = 200, 0.6                      # a cycle this long (and green) is a forage stand, not an annual
MERGE_GAP_D = 20                                   # cycles closer than this with no bare gap are one cycle
SPIKE, SPIKE_WIN = 0.20, 6                         # critique despike rule
HAZE_RATIO, HAZE_SELF, HAZE_KM, HAZE_K, HAZE_MIN = 0.88, 0.95, 5.0, 12, 8
NEIGH_D = 24                                       # neighbour looks used for expectations (<= 2 missed looks)
CUT_DROP, CUT_PRE_D, CUT_CANOPY, CUT_REC, CUT_REC_D = 0.15, 17, 0.45, 0.15, 25
MIN_LOOKS, MAX_GAP_D = 12, 64
SUMMER_GREEN = 0.60                                # critique 0.70; see docstring (8-day looks catch cut dips)
BOOT_RUNS, BOOT_DROP, SEED = 20, 0.40, 2026
RADAR_MIN_AUC = 0.65                               # below this HV cannot tell green from bare: radar flags not used
N_SECT, SECT_MIN_PX, SECT_MIN_N, SPLIT_MAJ = 6, 8, 4, 0.70
SPLIT_SPREAD = 0.10                                # sectors of a uniform field differ by ~0.03-0.05 NDVI
SPRING = ("2026-04-20", "2026-06-05")              # scripts/s2_spring.py WINDOW (spring_brown cross-check)
ZONE_SHIFT = {"south": -14, "centre": 0, "north": 21}  # days added to winter peak / end windows (see zone())
PX_HA = 0.16
WINTER = ("winter_cereal", "winter_fodder")
CLASSES = ("tree_crop", "perennial_forage", "winter_cereal", "winter_fodder", "autumn_crop", "spring_crop",
           "summer_crop", "double_crop", "multi_cycle", "fallow", "insufficient_data")


def day(s):
    """Days since T0 for a date string or datetime64."""
    return (np.datetime64(s, "D") - T0).astype(int)


def iso(d):
    """Day offset(s) -> 'YYYY-MM-DD' strings ('' for NaN)."""
    d = np.asarray(d, float)
    out = np.full(d.shape, "", object)
    ok = np.isfinite(d)
    out[ok] = (T0 + np.round(d[ok]).astype(int).astype("timedelta64[D]")).astype(str)
    return out


# ------------------------------------------------------------------ inputs
def load_looks(rid):
    """Field x date NDVI matrix (NaN = no clear look), look days, sensor per date, field info."""
    R = ROOT / "data" / "regions" / rid
    info = pd.read_csv(R / "landsat_fieldinfo.csv")
    fr = pd.read_csv(R / "fields_radar.csv", usecols=["id", "lon", "lat"])
    info = info.merge(fr, on="id", how="left")
    d = pd.read_csv(R / "landsat_ndvi.csv.gz")
    d = d[(d.date >= str(T0)) & (d.date <= str(T1))]
    # two looks of one field on one date (overlapping paths) are averaged
    d = d.groupby(["id", "date"], as_index=False).agg(ndvi=("ndvi", "mean"), sensor=("sensor", "first"))
    dates = np.array(sorted(d.date.unique()), dtype=str)
    sensor = d.groupby("date").sensor.agg(lambda s: s.mode().iloc[0]).reindex(dates).to_numpy(dtype=str)
    ids = info.id.values
    X = np.full((len(ids), len(dates)), np.nan)
    X[np.searchsorted(ids, d.id.values), np.searchsorted(dates, d.date.to_numpy(dtype=str))] = d.ndvi.values
    t = np.array([day(x) for x in dates])
    lat0 = np.nanmedian(info.lat)
    xy = np.c_[info.lon.values * 111.32 * np.cos(np.radians(lat0)), info.lat.values * 110.57]
    xy = np.where(np.isfinite(xy), xy, np.nanmedian(xy, 0))   # a field missing from fields_radar.csv: box centre
    return info, X, t, dates, sensor, xy


def neighbours(X, t):
    """Previous and next valid look (value, day) for every cell, excluding the cell itself."""
    n, m = X.shape
    valid = np.isfinite(X)
    ar = np.broadcast_to(np.arange(m), (n, m))
    pidx = np.maximum.accumulate(np.where(valid, ar, -1), axis=1)
    pidx = np.c_[np.full(n, -1), pidx[:, :-1]]
    nidx = np.minimum.accumulate(np.where(valid, ar, m)[:, ::-1], axis=1)[:, ::-1]
    nidx = np.c_[nidx[:, 1:], np.full(n, m)]
    Xp = np.c_[X, np.full(n, np.nan)]
    tp = np.r_[t, 10 ** 6].astype(float)
    pv = np.take_along_axis(Xp, np.where(pidx < 0, m, pidx), 1)
    nv = np.take_along_axis(Xp, nidx, 1)
    pt = np.where(pidx < 0, -10 ** 6, tp[np.where(pidx < 0, m, pidx)])
    nt = tp[nidx]
    return pv, pt, nv, nt


def clean_looks(X, t, xy):
    """Despiked raw series: drop hazy looks (spatial check) and the critique's 6-day spikes.
    Returns the cleaned matrix, the dropped-look mask and the local haze ratio H (field x date)."""
    valid = np.isfinite(X)
    pv, pt, nv, nt = neighbours(X, t)
    tt = np.broadcast_to(t, X.shape)
    near = (tt - pt <= NEIGH_D) & (nt - tt <= NEIGH_D)
    with np.errstate(all="ignore"):
        w = (tt - pt) / (nt - pt)
        e = pv + w * (nv - pv)
        r = X / e
    stable = valid & near & (pv >= 0.5) & (nv >= 0.5) & (np.abs(pv - nv) < 0.10)
    H = np.ones(X.shape)
    for j in range(X.shape[1]):
        s = np.flatnonzero(stable[:, j])
        if len(s) < 20:
            continue
        k = min(HAZE_K + 1, len(s))
        dist, nb = cKDTree(xy[s]).query(xy, k=k, distance_upper_bound=HAZE_KM)
        ok = np.isfinite(dist)
        nbc = np.where(ok, nb, 0)
        vals = np.where(ok & (s[nbc] != np.arange(len(xy))[:, None]), r[s[nbc], j], np.nan)
        cnt = np.isfinite(vals).sum(1)
        with np.errstate(all="ignore"):
            loc = np.nanmedian(np.where(cnt[:, None] > 0, vals, 0), 1)
        H[:, j] = np.where(cnt >= HAZE_MIN, loc, np.nanmedian(r[s, j]))
    with np.errstate(invalid="ignore"):
        hazy = valid & (H < HAZE_RATIO) & ~(r >= HAZE_SELF)
    X1 = np.where(hazy, np.nan, X)
    pv, pt, nv, nt = neighbours(X1, t)
    spike = (np.isfinite(X1) & (pv - X1 >= SPIKE) & (nv - X1 >= SPIKE)
             & (tt - pt <= SPIKE_WIN) & (nt - tt <= SPIKE_WIN))
    X1 = np.where(spike, np.nan, X1)
    return X1, hazy | spike, H


# ------------------------------------------------------------------ smoothing and cycles
_P = None


def whittaker_envelope(X, t):
    """Bin looks to the 5-day grid; weighted Whittaker fit refitted to the upper envelope. Returns Z (n x G)."""
    global _P
    G = len(GRID)
    if _P is None:
        Dm = np.diff(np.eye(G), 2, axis=0)
        _P = LAM * Dm.T @ Dm
    node = np.clip(np.round(t / STEP).astype(int), 0, G - 1)
    S = np.zeros((X.shape[0], G))
    C = np.zeros((X.shape[0], G))
    v = np.isfinite(X)
    for j in range(X.shape[1]):
        S[:, node[j]] += np.where(v[:, j], X[:, j], 0)
        C[:, node[j]] += v[:, j]
    W = C > 0
    Y = np.where(W, S / np.maximum(C, 1), 0.0)
    Z = np.full(Y.shape, np.nan)
    pats, inv = np.unique(W, axis=0, return_inverse=True)
    inv = inv.ravel()
    order = np.argsort(inv, kind="stable")
    bounds = np.searchsorted(inv[order], np.arange(len(pats) + 1))
    for k, p in enumerate(pats):
        rows = order[bounds[k]:bounds[k + 1]]
        if p.sum() < 4:
            continue
        Ainv = np.linalg.inv(np.diag(p.astype(float)) + _P)
        Yr = Y[rows]
        z = Yr @ Ainv
        for _ in range(ENV_ITERS):
            z = np.where(p, np.maximum(Yr, z), 0.0) @ Ainv
        Z[rows] = z
    return np.clip(Z, -0.1, 1.0)


def segment(Z):
    """Crop cycles on the smoothed series. Returns a DataFrame: row, gu, pk, en (days since T0, crossing-interpolated),
    peak, cs, ce (start / end censored by the window), after merging and validity filtering."""
    n, G = Z.shape
    inc = np.zeros(n, bool)
    st = np.zeros(n)
    pk = np.zeros(n, int)
    pv = np.zeros(n)
    mn = np.zeros(n)
    mi = np.zeros(n, int)
    cs = np.zeros(n, bool)
    vs = np.zeros(n, bool)   # cycle started at a valley split
    out = []

    def close(sel, end_day, cen):
        r = np.flatnonzero(sel)
        if len(r):
            out.append(pd.DataFrame({"row": r, "gu": st[r], "pk": GRID[pk[r]],
                                     "en": end_day[r] if np.ndim(end_day) else end_day, "peak": pv[r], "cs": cs[r],
                                     "ce": cen, "vs": vs[r]}))

    zprev = np.full(n, np.nan)
    for g in range(G):
        z = Z[:, g]
        ok = np.isfinite(z)
        # crossing day (linear interpolation between nodes) for green-up / end
        with np.errstate(all="ignore"):
            x_up = GRID[g] - STEP * (z - GREEN) / (z - zprev)
            x_dn = GRID[g] - STEP * (END - z) / (zprev - z)
        x_up = np.where(np.isfinite(x_up) & (g > 0), x_up, GRID[g])
        x_dn = np.where(np.isfinite(x_dn) & (g > 0), x_dn, GRID[g])
        # end of cycle
        e = inc & ok & (z < END)
        close(e, x_dn, False)
        inc &= ~e
        # valley split (cycle never dropped below END)
        sp = inc & ok & (pv - mn >= VALLEY_DEPTH) & (z - mn >= VALLEY_DEPTH) & (mn <= VALLEY_MAX)
        close(sp, GRID[mi].astype(float), False)
        for i in np.flatnonzero(sp):   # rare: green-up = first regrowth REGROW above the valley
            st[i] = GRID[mi[i] + int(np.argmax(Z[i, mi[i]:g + 1] >= mn[i] + REGROW))]
        cs[sp] = False
        vs[sp] = True
        pk[sp], pv[sp], mn[sp], mi[sp] = g, z[sp], z[sp], g
        # running peak / valley
        up = inc & ok & ~sp & (z > pv)
        pk[up], pv[up], mn[up], mi[up] = g, z[up], z[up], g
        lo = inc & ok & ~sp & ~up & (z < mn)
        mn[lo], mi[lo] = z[lo], g
        # new cycle
        new = ~inc & ok & (z >= GREEN)
        st[new] = np.where(g == 0, 0.0, x_up[new])
        cs[new] = g == 0
        vs[new] = False
        pk[new], pv[new], mn[new], mi[new] = g, z[new], z[new], g
        inc |= new
        zprev = np.where(ok, z, zprev)
    close(inc, float(GRID[-1]), True)
    cyc = pd.concat(out, ignore_index=True) if out else pd.DataFrame(
        {k: pd.Series(dtype=t) for k, t in (("row", int), ("gu", float), ("pk", int), ("en", float), ("peak", float),
                                            ("cs", bool), ("ce", bool), ("vs", bool))})
    cyc = cyc.sort_values(["row", "gu"]).reset_index(drop=True)
    # merge cycles separated by a short gap that never went bare
    if len(cyc):
        prev_row = cyc.row.shift()
        gap = cyc.gu - cyc.en.shift()
        cand = (cyc.row == prev_row) & ~cyc.vs & (gap < MERGE_GAP_D)   # a valley split is never merged
        if cand.any():
            gmin = np.array([np.nanmin(Z[int(r), int(a // STEP):int(np.ceil(b / STEP)) + 1])
                             if c else np.nan for r, a, b, c in zip(cyc.row, cyc.en.shift().fillna(0), cyc.gu, cand)])
            shallow = np.minimum(cyc.peak.shift().values, cyc.peak.values) - gmin < VALLEY_DEPTH
            merge = cand & (gmin >= BARE) & shallow
            grp = (~merge).cumsum()
            cyc = cyc.groupby(grp).agg(row=("row", "first"), gu=("gu", "first"), en=("en", "last"), cs=("cs", "first"),
                                       ce=("ce", "last"), peak=("peak", "max"), pk=("pk", "first"),
                                       vs=("vs", "first")).reset_index(drop=True)
            # peak day of a merged cycle = its highest grid node
            cyc["pk"] = [GRID[int(a // STEP) + int(np.nanargmax(Z[int(r), int(a // STEP):int(b // STEP) + 1]))]
                         for r, a, b in zip(cyc.row, cyc.gu, cyc.en)]
    cyc["length"] = cyc.en - cyc.gu
    keep = (cyc.peak >= MIN_PEAK) & ((cyc.length >= MIN_CYCLE_D) | cyc.cs | cyc.ce)
    return cyc[keep].reset_index(drop=True)


def detect_cuts(X, t):
    """Cuts on the despiked raw looks. Returns a boolean matrix (field x date) marking the low look of each cut."""
    v = np.isfinite(X)
    pv, pt, nv, nt = neighbours(X, t)
    tt = np.broadcast_to(t, X.shape)
    pre = np.full(X.shape, -np.inf)
    post = np.full(X.shape, -np.inf)
    Xf = np.where(v, X, -np.inf)
    for j in range(X.shape[1]):
        w_pre = (t < t[j]) & (t >= t[j] - CUT_PRE_D)
        w_post = (t > t[j]) & (t <= t[j] + CUT_REC_D)
        if w_pre.any():
            pre[:, j] = Xf[:, w_pre].max(1)
        if w_post.any():
            post[:, j] = Xf[:, w_post].max(1)
    with np.errstate(invalid="ignore"):
        local_min = v & (X < pv) & ~(nv < X) & (tt - pt <= CUT_PRE_D)
        return local_min & (pre - X >= CUT_DROP) & (pre >= CUT_CANOPY) & (post - X >= CUT_REC)


# ------------------------------------------------------------------ features and labels
def season_cycles(cyc):
    """2025/26 season-year cycles (by green-up date, see docstring)."""
    gu_ok = (cyc.gu >= day("2025-09-01")) & (cyc.gu <= day("2026-08-31")) & ~cyc.cs
    early = (cyc.cs | (cyc.gu < day("2025-09-01"))) & (cyc.en >= day("2025-12-01"))
    return cyc[gu_ok | early]


def zone(lat):
    """Calendar zone by latitude: south < 24 N (R04 Wadi ad-Dawasir: winter cycles end Feb-Apr), centre 24-27 N
    (Qassim, Riyadh), north > 27 N (Hail, Al-Jouf, Tabuk: frost and slow winter growth; wheat sown Nov-Dec reaches
    NDVI 0.40 only in Jan-Feb, peaks Mar-Apr and is harvested May-Jun). The boundary was 28 N, which left Hail's farms
    (27-28 N) on the central calendar: national checks showed 48,000 ha of such northern wheat typed spring_crop and
    mapped wheat at 0.25-0.40 of GASTAT 2024 in Al-Jouf, Hail and Tabuk."""
    return "south" if lat < 24 else ("north" if lat > 27 else "centre")


def type_cycles(cyc, cuts_in, sh):
    """Cycle type by timing (strict windows first, then loose fallbacks); sh = the zone's day shift of the
    winter peak / end windows. Adds columns ctype, cstrict."""
    gu, pk, en, L, pkv = cyc.gu.values, cyc.pk.values, cyc.en.values, cyc.length.values, cyc.peak.values
    cs, ce = cyc.cs.values, cyc.ce.values
    c = cuts_in
    known = ~cs
    wf = (known & (gu >= day("2025-10-01")) & (gu <= day("2025-12-31")) & (c >= 2) & (en <= day("2026-06-30") + max(sh, 0))
          & ~ce)
    late = sh >= ZONE_SHIFT["north"]   # northern calendar: later green-up and peak (see zone())
    # wheat green-up (NDVI crossing 0.40) can come as late as mid-February in the centre and south (late sowing) and
    # end of February in the north; set from the calibration half of the blind check (224 cards), where cycles typed
    # spring_crop with green-up 15 Jan-10 Feb, peak late Feb-Mar and end Apr-May were read as wheat by 15 of 25
    # interpreters; true spring crops in that sample green up from March-April. Accuracy is reported on a separate
    # test sample drawn after this change.
    gu_end = day("2026-02-28") if late else day("2026-02-15")
    pk_end = day("2026-04-30") if late else day("2026-03-31") + sh
    wc = (known & (gu >= day("2025-10-15")) & (gu <= gu_end) & (pk >= day("2026-01-15") + sh)
          & (pk <= pk_end) & (pkv >= 0.60) & (en >= day("2026-03-15") + sh)
          & (en <= day("2026-06-15") + sh) & (L >= 80) & (L <= 180 + max(sh, 0)))
    au = known & (gu >= day("2025-08-01")) & (gu <= day("2025-10-31")) & (en >= day("2025-12-01")) & (en <= day("2026-02-28"))
    sp = known & (gu >= day("2026-01-01")) & (gu <= day("2026-03-31")) & (en >= day("2026-05-01")) & (en <= day("2026-07-31"))
    su = known & (gu >= day("2026-05-01")) & (gu <= day("2026-08-31")) & (L >= 70) & (L <= 140) & ~ce
    strict = np.select([wf, wc, au, sp, su], ["winter_fodder", "winter_cereal", "autumn_crop", "spring_crop",
                                              "summer_crop"], "")
    # a forage stand: >= LONG_D days long, or green since before the record and still green in February, and green
    # (>= 0.40) for >= 60% of it
    lng = ((strict == "") & ((L >= LONG_D) | (cs & (en > day("2026-01-31"))))
           & (cyc.green_d.values >= LONG_GREEN * np.maximum(L, STEP)))
    # loose fallbacks
    l_au = (cs | (gu < day("2025-10-15"))) & (en <= day("2026-03-15"))
    l_wi = known & (gu >= day("2025-10-01")) & (gu <= gu_end) & (en <= day("2026-07-15") + max(sh, 0))
    l_sp = known & (gu > gu_end) & (gu <= day("2026-04-30"))
    l_su = known & (gu > day("2026-04-30")) & (gu <= day("2026-08-31"))
    # last resort (weak or censored cycles that fit no green-up window): the season of the peak
    p_au = pk < day("2025-12-01")
    p_wi = pk < day("2026-04-01")
    p_sp = pk < day("2026-05-01")
    loose = np.select([l_au, l_wi & (c >= 2), l_wi, l_sp, l_su, p_au, p_wi & (c >= 2), p_wi, p_sp],
                      ["autumn_crop", "winter_fodder", "winter_cereal", "spring_crop", "summer_crop", "autumn_crop",
                       "winter_fodder", "winter_cereal", "spring_crop"], "summer_crop")
    cyc = cyc.copy()
    cyc["ctype"] = np.where(strict != "", strict, np.where(lng, "long", loose))
    cyc["cstrict"] = strict != ""
    # spring cycles peaking from May are the summer half of a winter + summer double crop (sown Mar-Apr)
    cyc["summer_side"] = (cyc.ctype == "summer_crop") | ((cyc.ctype == "spring_crop") & (pk >= day("2026-05-01")))
    cyc["summer_cover"] = (cyc.ctype == "long") & (cs | (gu <= day("2026-06-15"))) & (ce | (en >= day("2026-09-01")))
    started = ~cs & (gu > day("2025-11-30"))
    ended = ~ce & (en < day("2026-10-01"))
    cyc["stand"] = np.select([started & ended, started, ended], ["within", "new", "ended"], "established")
    return cyc


def analyse(X, t, sh):
    """Features and labels for a set of series (fields, sectors or a date subset). Returns (features, cycles)."""
    n = X.shape[0]
    v = np.isfinite(X)
    ins = (t >= day(SY0)) & (t <= day(SY1))
    Xs = X[:, ins]
    ts = t[ins]
    vs = np.isfinite(Xs)
    n_looks = vs.sum(1)
    n_looks_all = v.sum(1)
    # max gap between looks inside the season year (season edges count as looks)
    tl = np.where(vs, ts, np.nan)
    tl = np.c_[np.full(n, day(SY0)), tl, np.full(n, day(SY1))]
    tl = np.sort(tl, 1)
    max_gap = np.nanmax(np.diff(tl, axis=1), 1)
    with np.errstate(all="ignore"):
        p5 = np.nanpercentile(Xs, 5, axis=1)
        p95 = np.nanpercentile(Xs, 95, axis=1)
        mean = np.nanmean(Xs, 1)
        frac035 = np.nansum(Xs >= 0.35, 1) / np.maximum(n_looks, 1)
        summ = (ts >= day("2026-06-01")) & (ts <= day("2026-09-30"))
        summer_green = np.nansum(Xs[:, summ] >= GREEN, 1) / np.maximum(vs[:, summ].sum(1), 1)
        summer_green = np.where(vs[:, summ].sum(1) > 0, summer_green, np.nan)
        win = (ts >= day("2025-12-01")) & (ts <= day("2026-02-28"))
        jja = (ts >= day("2026-06-01")) & (ts <= day("2026-08-31"))
        decid = np.nanmedian(Xs[:, jja], 1) - np.nanmedian(Xs[:, win], 1)
    Z = whittaker_envelope(X, t)
    gs = (GRID >= day(SY0)) & (GRID <= day(SY1))
    Zs = Z[:, gs]
    days_green = (Zs >= GREEN).sum(1) * STEP
    bare = np.c_[np.zeros(n, bool), Zs < BARE, np.zeros(n, bool)].astype(np.int8)
    db = np.diff(bare, axis=1)
    longest_bare = np.zeros(n)
    rs, cs_ = np.nonzero(db == 1)
    re, ce_ = np.nonzero(db == -1)
    if len(rs):
        np.maximum.at(longest_bare, rs, (ce_ - cs_) * STEP)
    # sustained low: the lowest value two consecutive looks (<= 17 d apart) both stay at or below; a cut dip is
    # one look, a harvest / ploughing break is several
    pv_, pt_, nv_, nt_ = neighbours(Xs, ts)
    with np.errstate(invalid="ignore"):
        pair = np.where(np.isfinite(Xs) & (nt_ - ts <= CUT_PRE_D), np.fmax(Xs, nv_), np.nan)
    low2 = np.nanmin(np.where(np.isfinite(pair), pair, np.inf), 1)
    low2 = np.where(np.isfinite(low2), low2, np.nan)
    cut = detect_cuts(X, t)
    cut_s = cut[:, ins]
    cuts = cut_s.sum(1)
    cut_days = [ts[np.flatnonzero(r)] for r in cut_s]
    cut_int = np.array([np.median(np.diff(c)) if len(c) >= 2 else np.nan for c in cut_days])
    feats = pd.DataFrame({"n_looks": n_looks, "n_looks_window": n_looks_all, "max_gap_d": max_gap,
                          "days_green": days_green, "longest_bare_d": longest_bare, "amplitude": p95 - p5, "p5": p5,
                          "mean_ndvi": mean, "frac_ge035": frac035, "summer_green": summer_green, "cuts": cuts,
                          "cut_interval_d": cut_int, "decid_drop": decid, "low2": low2})
    # cycles
    cyc = segment(Z)
    if len(cyc):
        cr, cc = np.nonzero(cut)
        cut_t = t[cc]
        cyc_cuts = np.zeros(len(cyc), int)
        if len(cr):
            byrow = pd.Series(cut_t).groupby(cr).apply(np.asarray).to_dict()
            cyc_cuts = np.array([int(((byrow.get(r, np.empty(0)) >= a) & (byrow.get(r, np.empty(0)) <= b)).sum())
                                 for r, a, b in zip(cyc.row, cyc.gu, cyc.en)])
        cyc["cuts"] = cyc_cuts
        # days at or above GREEN inside each cycle (a 'long' stand must be green, not hovering at 0.30-0.40)
        cumg = np.c_[np.zeros(n), np.cumsum(Z >= GREEN, axis=1)]
        i0 = np.clip(np.ceil(cyc.gu.values / STEP), 0, len(GRID)).astype(int)
        i1 = np.clip(np.floor(cyc.en.values / STEP) + 1, 0, len(GRID)).astype(int)
        cyc["green_d"] = (cumg[cyc.row.values, i1] - cumg[cyc.row.values, i0]) * STEP
        cyc = type_cycles(cyc, cyc_cuts, sh)
        scy = season_cycles(cyc)
    else:
        cyc = cyc.assign(cuts=0, ctype="", cstrict=False, summer_side=False, summer_cover=False, stand="")
        scy = cyc
    g = scy.groupby("row")
    feats["has_winter"] = g.ctype.agg(lambda c: c.isin(WINTER).any()).reindex(range(n)).fillna(False).astype(bool).values
    feats["has_summer"] = g.summer_side.any().reindex(range(n)).fillna(False).astype(bool).values
    feats["summer_long"] = g.summer_cover.any().reindex(range(n)).fillna(False).astype(bool).values
    lc = scy[scy.ctype == "long"].sort_values(["row", "summer_cover"], ascending=[True, False]).drop_duplicates("row")
    feats["long_stand"] = lc.set_index("row").stand.reindex(range(n)).fillna("").values
    seq = g.ctype.agg("+".join).reindex(range(n)).fillna("")
    allstrict = g.cstrict.all().reindex(range(n)).fillna(True).astype(bool)
    ncyc = g.size().reindex(range(n)).fillna(0).astype(int)
    feats["n_cycles"] = ncyc.values
    feats["cycle_seq"] = seq.values
    first = scy.drop_duplicates("row").set_index("row")
    second = scy[scy.duplicated("row")].drop_duplicates("row").set_index("row")
    for k, src in (("1", first), ("2", second)):
        for col, name in (("gu", "greenup"), ("pk", "peak"), ("en", "end")):
            feats[f"{name}{k}_day"] = src[col].reindex(range(n)).values
        feats[f"peak{k}_ndvi"] = src["peak"].reindex(range(n)).values
    feats["greenup1_censored"] = first["cs"].reindex(range(n)).fillna(False).astype(bool).values
    label, strict, stand = classify(feats, seq.values, allstrict.values)
    feats["crop_type"] = label
    feats["rule"] = np.where(strict, "strict", "loose")
    feats["stand"] = stand
    return feats, cyc, Z, cut


def classify(f, seq, allstrict):
    """Rule ladder (docstring section 6). Returns labels and the strict flag."""
    insuff = (f.n_looks < MIN_LOOKS) | (f.max_gap_d > MAX_GAP_D)
    tree = (f.longest_bare_d <= 30) & (f.p5 >= 0.18) & (f.amplitude < 0.25) & f.mean_ndvi.between(0.22, 0.60)
    per = ((f.longest_bare_d <= 40) & (f.frac_ge035 >= 0.80) & (f.summer_green >= SUMMER_GREEN)
           & ((f.cuts >= 3) | (f.amplitude >= 0.30)))
    per_loose = (f.longest_bare_d <= 60) & (f.days_green >= 270) & (f.mean_ndvi > 0.45) & (f.low2 >= 0.30)
    n = f.n_cycles.values
    one = n == 1
    double = (n == 2) & f.has_winter.values & f.has_summer.values
    lone_long = one & (seq == "long")
    conds = [insuff, tree, per, per_loose, f.summer_long.values, n == 0, lone_long, one, double]
    label = np.select(conds, ["insufficient_data", "tree_crop", "perennial_forage", "perennial_forage",
                              "perennial_forage", "fallow", "perennial_forage", seq, "double_crop"], "multi_cycle")
    strict = np.select(conds, [True, True, True, False, False, True, False, allstrict, allstrict], False)
    ls = f.long_stand.values
    stand = np.select(conds[:7], ["", "", "established", "established", ls, "", ls], "")
    return label.astype(object), strict.astype(bool), stand.astype(object)


# ------------------------------------------------------------------ radar evidence
def youden(score, y):
    """Threshold maximising TPR - FPR (score > thr = positive)."""
    o = np.argsort(-score)
    s, yy = score[o], y[o]
    tp = np.cumsum(yy)
    fp = np.cumsum(~yy)
    j = tp / max(yy.sum(), 1) - fp / max((~yy).sum(), 1)
    k = int(np.argmax(j))
    return float((s[k] + s[k + 1]) / 2) if k + 1 < len(s) else float(s[k])


def auc(score, y):
    """Mann-Whitney AUC."""
    r = pd.Series(score).rank().values
    n1, n0 = y.sum(), (~y).sum()
    return float((r[y].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)) if n1 and n0 else np.nan


def radar_flags(rid, info, Xc, t):
    """Per-field radar_winter_canopy / radar_summer_persist (object True/False/NaN) and calibration stats."""
    R = ROOT / "data" / "regions" / rid
    meta = json.loads((R / "meta.json").read_text())
    n = len(info)
    flags = {se: np.full(n, np.nan, object) for se in ("winter", "summer")}
    stats = {}
    f = R / "hv_timeseries.csv"
    if not f.exists():
        return flags, stats
    hv = pd.read_csv(f)
    hv = hv[hv.field_id.isin(info.id)]
    pos = pd.Series(np.arange(n), index=info.id.values)
    thr_v1 = meta.get("validation", {}).get("thresholds_db", {})
    for se in ("winter", "summer"):
        if not NS.season_ok(meta, se, True):
            stats[se] = {"used": False, "reason": "quality check" if se in thr_v1 else "no dates"}
            continue
        h = hv[hv.season == se]
        dates = sorted(h.date.unique())
        H = np.full((n, len(dates)), np.nan)
        H[pos[h.field_id].values, np.searchsorted(dates, h.date.values)] = h.hv_norm.values
        # optical state within 6 days of each radar date (nearest kept look)
        O = np.full(H.shape, np.nan)
        for k, dd in enumerate(dates):
            dt = np.abs(t - day(dd))
            best = np.full(n, np.inf)
            for j in np.flatnonzero(dt <= 6):
                ok = np.isfinite(Xc[:, j]) & (dt[j] < best)
                O[ok, k] = Xc[ok, j]
                best[ok] = dt[j]
        lab = np.where(O >= 0.5, 1.0, np.where(O < 0.25, 0.0, np.nan))
        ok = np.isfinite(H) & np.isfinite(lab)
        calib = (info.id.values % 2 == 0)[:, None] & ok
        test = (info.id.values % 2 == 1)[:, None] & ok
        yc = lab[calib] == 1
        if yc.sum() >= 30 and (~yc).sum() >= 30:
            thr = youden(H[calib], yc)
            src = "youden"
        else:
            thr = float(thr_v1[se])
            src = "v1_desert"
        yt = lab[test] == 1
        a_test = auc(H[test], yt) if yt.any() and (~yt).any() else np.nan
        base = {"threshold_db": round(thr, 2), "source": src, "v1_threshold_db": thr_v1.get(se), "n_dates": len(dates),
                "calib_green": int(yc.sum()), "calib_bare": int((~yc).sum()),
                "test_auc": None if np.isnan(a_test) else round(a_test, 3)}
        if not a_test >= RADAR_MIN_AUC:
            stats[se] = {"used": False, "reason": f"HV does not separate optical green from bare (AUC {a_test:.2f})",
                         **base}
            continue
        on = H > thr
        nv_ = np.isfinite(H).sum(1)
        non = (on & np.isfinite(H)).sum(1)
        noff = nv_ - non
        need = 2 if se == "winter" else 3
        fl = np.full(n, np.nan, object)
        fl[noff >= 2] = False
        fl[non >= need] = True
        flags[se] = fl
        pred = H[test] > thr
        stats[se] = {"used": True, **base, "test_agreement": round(float((pred == yt).mean()), 3) if len(yt) else None}
    return flags, stats


def radar_agree(label, stand, ncyc, en1, w, s):
    """1/0 on the components the radar can see for each class (docstring section 8); NaN if untestable.
    Perennial stands are tested on the part of the year they covered: an established or ended stand was green in
    Dec-Jan; established and new stands were green all summer; a stand that ended before 1 Aug, with no later
    cycle, was not. A new stand's winter is not tested (the field may have carried a winter crop before it)."""
    exp_w = {"tree_crop": True, "fallow": False, "summer_crop": False}
    exp_s = {"tree_crop": True, "fallow": False, "winter_cereal": False, "winter_fodder": False, "autumn_crop": False,
             "spring_crop": False}
    out = np.full(len(label), np.nan)
    for i, (lb, st, nc, e, wi, si) in enumerate(zip(label, stand, ncyc, en1, w, s)):
        ew, es = exp_w.get(lb), exp_s.get(lb)
        if lb == "perennial_forage":
            ew = True if st in ("established", "ended") else None
            es = True if st in ("established", "new") else (
                False if st == "ended" and nc == 1 and e < day("2026-08-01") else None)
        tests = []
        if ew is not None and isinstance(wi, (bool, np.bool_)):
            tests.append(wi == ew)
        if es is not None and isinstance(si, (bool, np.bool_)):
            tests.append(si == es)
        if tests:
            out[i] = float(all(tests))
    return out


# ------------------------------------------------------------------ split pivots (sector relabelling)
def sector_series(rid, info, dates, dropped_dates_mask):
    """Mean NDVI of clear interior 40 m pixels per 60-degree sector of each field, per date (from the cache)."""
    R = ROOT / "data" / "regions" / rid
    L = ROOT / "data" / "landsat" / rid
    files = sorted(L.glob("*_o.tif")) if L.exists() else []
    if not files:
        return None
    with rasterio.open(R / "fields_labels.tif") as src:
        lab = src.read(1)
    ids = info.id.values
    interior = (ndi.minimum_filter(lab, 3) == ndi.maximum_filter(lab, 3)) & (lab > 0)
    rr, cc = np.indices(lab.shape)
    cy = np.asarray(ndi.mean(rr, lab, ids))
    cx = np.asarray(ndi.mean(cc, lab, ids))
    pos = np.zeros(lab.max() + 1, int)
    pos[ids] = np.arange(len(ids))
    p = pos[lab]
    ang = np.arctan2(rr - cy[p], cc - cx[p])
    sec = np.minimum(((ang + np.pi) / (2 * np.pi) * N_SECT).astype(int), N_SECT - 1)
    slab = np.where(interior, p * N_SECT + sec + 1, 0)
    nsl = len(ids) * N_SECT
    sl_ids = np.arange(1, nsl + 1)
    npx = np.bincount(slab.ravel(), minlength=nsl + 1)[1:]
    big = npx.reshape(-1, N_SECT) >= SECT_MIN_PX
    use_field = big.sum(1) >= SECT_MIN_N
    if not use_field.any():
        return None
    keep_sl = (big & use_field[:, None]).ravel()
    flat = slab.ravel()
    di = {d: k for k, d in enumerate(dates)}
    S = np.full((nsl, len(dates)), np.nan)
    for f in files:
        d, sensor, path = f.name[:-6].split("_")
        k = di.get(f"{d[:4]}-{d[4:6]}-{d[6:]}")
        if k is None:
            continue
        with rasterio.open(f) as src:
            o = src.read([1, 2])
        clear = (o[1] == 1) & (o[0] > -32768) & (flat.reshape(lab.shape) > 0)
        sel = clear.ravel()
        cnt = np.bincount(flat[sel], minlength=nsl + 1)[1:]
        sm = np.bincount(flat[sel], weights=o[0].ravel()[sel] / 1e4, minlength=nsl + 1)[1:]
        m = np.where(cnt >= 0.5 * np.maximum(npx, 1), sm / np.maximum(cnt, 1), np.nan)
        S[:, k] = np.where(np.isfinite(S[:, k]), np.nanmean(np.c_[S[:, k], m], 1), m)
    # the parent field's dropped looks (haze, spikes) are dropped in its sectors too
    S = np.where(np.repeat(dropped_dates_mask, N_SECT, axis=0), np.nan, S)
    return S[keep_sl], np.flatnonzero(keep_sl) // N_SECT, npx[keep_sl]


# ------------------------------------------------------------------ per region
def kappa(a, b):
    """Cohen's kappa of two label arrays."""
    a, b = np.asarray(a), np.asarray(b)
    if not len(a):
        return np.nan
    cats = np.union1d(a, b)
    po = float((a == b).mean())
    pe = float(sum((a == c).mean() * (b == c).mean() for c in cats))
    return (po - pe) / (1 - pe) if pe < 1 else np.nan


def tiers(info):
    ha = info.px40 * PX_HA
    return np.where((ha >= 5) | (info.int40 >= 20), "reliable",
                    np.where((ha >= 3) | (info.int40 >= 5), "provisional", "edge_mixed"))


def windbreak(rid, info):
    """Linear tree objects: minor axis < 3 px (120 m) or eccentricity > 0.95 (skimage regionprops)."""
    from skimage.measure import regionprops_table
    with rasterio.open(ROOT / "data" / "regions" / rid / "fields_labels.tif") as src:
        lab = src.read(1)
    rp = pd.DataFrame(regionprops_table(lab, properties=("label", "minor_axis_length", "eccentricity")))
    rp = rp.set_index("label").reindex(info.id.values)
    return ((rp.minor_axis_length < 3) | (rp.eccentricity > 0.95)).values


def run(rid, plot=None, summary=None):
    t_start = time.time()
    R = ROOT / "data" / "regions" / rid
    regions = {r["id"]: r for r in json.loads((ROOT / "data" / "national" / "regions.json").read_text())}
    zn = zone(regions[rid]["center"][0])
    sh = ZONE_SHIFT[zn]
    info, X, t, dates, sensor, xy = load_looks(rid)
    Xc, dropped, H = clean_looks(X, t, xy)
    feats, cyc, Z, cut = analyse(Xc, t, sh)
    label = feats.crop_type.values
    # split halves: Landsat 8 dates only vs Landsat 9 dates only
    halves = {}
    for s in ("L8", "L9"):
        cols = sensor == s
        halves[s] = analyse(Xc[:, cols], t[cols], sh)[0].crop_type.values if cols.sum() >= MIN_LOOKS else \
            np.full(len(info), "insufficient_data", object)
    # temporal bootstrap
    rng = np.random.default_rng(SEED)
    same = np.zeros(len(info))
    m = len(t)
    for _ in range(BOOT_RUNS):
        cols = np.sort(rng.choice(m, size=int(round(m * (1 - BOOT_DROP))), replace=False))
        same += analyse(Xc[:, cols], t[cols], sh)[0].crop_type.values == label
    stability = same / BOOT_RUNS
    # radar
    rf, rstats = radar_flags(rid, info, Xc, t)
    ragree = radar_agree(label, feats.stand.values, feats.n_cycles.values, feats.end1_day.values,
                         rf["winter"], rf["summer"])
    # split pivots
    sp = sector_series(rid, info, dates, dropped | ~np.isfinite(Xc))
    split_share = np.full(len(info), np.nan)
    per_share = np.full(len(info), np.nan)
    spread = np.full(len(info), np.nan)
    sect_cls = np.full(len(info), "", object)
    if sp is not None:
        S, parent, npx = sp
        sl = analyse(S, t, sh)[0].crop_type.values
        dfp = pd.DataFrame({"parent": parent, "lab": sl, "px": npx})
        tot = dfp.groupby("parent").px.sum()
        byl = dfp.groupby(["parent", "lab"]).px.sum()
        split_share[tot.index] = (byl.groupby("parent").max() / tot).values
        pp = dfp[dfp.lab == "perennial_forage"].groupby("parent").px.sum().reindex(tot.index).fillna(0)
        per_share[tot.index] = (pp / tot).values
        frac = (byl / tot.reindex(byl.index.get_level_values(0)).values).round(2)
        frac = frac.sort_values(ascending=False)
        txt = frac.reset_index().groupby("parent").apply(
            lambda g: ";".join(f"{a}:{b:.2f}" for a, b in zip(g.lab, g.px)), include_groups=False)
        sect_cls[txt.index] = txt.values
        # how different the sectors' NDVI really is: median over season dates of the sector range (needs 3 sectors)
        ins = (t >= day(SY0)) & (t <= day(SY1))
        Ss = pd.DataFrame(S[:, ins]).groupby(parent)
        rng_ = (Ss.max() - Ss.min()).where(Ss.count() >= 3)
        spread[rng_.index] = rng_.median(axis=1).values
    # Landsat version of the Sentinel-2 spring_brown flag (median look in the s2_spring window < 0.30)
    wsp = (t >= day(SPRING[0])) & (t <= day(SPRING[1]))
    spring_ls = np.nanmedian(Xc[:, wsp], 1) if wsp.any() else np.full(len(info), np.nan)
    fr = pd.read_csv(R / "fields_radar.csv").set_index("id").reindex(info.id.values)
    s2b = NS.tri(fr.spring_brown) if "spring_brown" in fr else pd.Series(np.nan, index=fr.index)
    okb = s2b.notna().values & np.isfinite(spring_ls)
    spring_agree = float(((spring_ls[okb] < 0.30) == s2b.values[okb].astype(bool)).mean()) if okb.any() else np.nan
    tier = tiers(info)
    n_looks = feats.n_looks.values
    conf = np.where((stability >= 0.9) & (feats.rule.values == "strict") & (n_looks >= 30) & (tier == "reliable"),
                    "high", np.where((stability >= 0.7) & (tier != "edge_mixed"), "medium", "low"))
    conf = np.where(label == "insufficient_data", "low", conf)
    wb = windbreak(rid, info) & (label == "tree_crop")
    out = pd.DataFrame({"id": info.id.values, "crop_type": label, "cycle_seq": feats.cycle_seq.values,
                        "rule": feats.rule.values, "stand": feats.stand.values, "tier": tier, "confidence": conf,
                        "stability": np.round(stability, 2), "label_l8": halves["L8"], "label_l9": halves["L9"],
                        "split_half_agree": (halves["L8"] == halves["L9"]).astype(int),
                        "n_looks": n_looks, "n_looks_window": feats.n_looks_window.values,
                        "max_gap_d": feats.max_gap_d.values.astype(int), "n_cycles": feats.n_cycles.values,
                        "days_green": feats.days_green.values, "longest_bare_d": feats.longest_bare_d.values.astype(int),
                        "amplitude": feats.amplitude.round(3).values, "p5": feats.p5.round(3).values,
                        "mean_ndvi": feats.mean_ndvi.round(3).values, "frac_ge035": feats.frac_ge035.round(2).values,
                        "summer_green": feats.summer_green.round(2).values, "low2": feats.low2.round(3).values,
                        "cuts": feats.cuts.values,
                        "cut_interval_d": feats.cut_interval_d.values})
    for k in ("1", "2"):
        out[f"greenup{k}_date"] = iso(feats[f"greenup{k}_day"].values)
        out[f"peak{k}_date"] = iso(feats[f"peak{k}_day"].values)
        out[f"end{k}_date"] = iso(feats[f"end{k}_day"].values)
        out[f"peak{k}_ndvi"] = feats[f"peak{k}_ndvi"].round(3).values
    out["greenup1_censored"] = feats.greenup1_censored.values.astype(int)
    out.loc[out.greenup1_censored == 1, "greenup1_date"] = ""
    out["deciduous"] = ((label == "tree_crop") & (feats.decid_drop.values >= 0.15)).astype(int)
    out["windbreak"] = wb.astype(int)
    out["radar_winter_canopy"] = rf["winter"]
    out["radar_summer_persist"] = rf["summer"]
    out["radar_agree"] = ragree
    out["split_share"] = np.round(split_share, 2)
    out["sector_spread"] = np.round(spread, 3)
    out["split_flag"] = np.where(np.isfinite(split_share),
                                 ((split_share < SPLIT_MAJ) & (spread >= SPLIT_SPREAD)).astype(float), np.nan)
    out["perennial_share"] = np.round(per_share, 2)
    out["sector_classes"] = sect_cls
    out["ndvi_spring_ls"] = np.round(spring_ls, 3)
    out["looks_dropped"] = dropped.sum(1)
    out.to_csv(R / "crop_types.csv", index=False)
    # ---- one summary line
    ha = info.px40.values * PX_HA
    area = pd.Series(ha).groupby(label).sum()
    ok = (halves["L8"] != "insufficient_data") & (halves["L9"] != "insufficient_data")
    k8 = kappa(halves["L8"][ok], halves["L9"][ok])
    top = ", ".join(f"{c} {area.get(c, 0):,.0f}" for c in CLASSES if area.get(c, 0) > 0)
    rs = "; ".join(f"radar {se} {v['threshold_db']} dB ({v['source']}, AUC {v['test_auc']})" if v.get("used")
                   else f"radar {se} off ({v['reason']})" for se, v in rstats.items())
    print(f"{rid} {len(info)} fields, {len(t)} dates, median {int(np.median(n_looks))} looks/field in season, "
          f"{dropped.sum()} looks dropped | ha: {top} | L8/L9 kappa {k8:.2f}, bootstrap stability median "
          f"{np.median(stability):.2f} (>=0.9: {np.mean(stability >= 0.9):.0%}) | {rs} | spring_brown vs Landsat "
          f"{spring_agree:.3f} | split {int(np.nansum(out.split_flag))} of {int(np.isfinite(split_share).sum())} | "
          f"{time.time() - t_start:.0f} s",
          flush=True)
    if summary is not None:
        summary[rid] = {"fields": len(info), "dates": len(t), "radar": rstats, "kappa_l8_l9": round(k8, 3),
                        "class_kappa_l8_l9": {c: round(kappa(halves["L8"][ok] == c, halves["L9"][ok] == c), 3)
                                              for c in ("perennial_forage", "winter_cereal", "tree_crop")},
                        "stability_median": float(np.median(stability)), "area_ha": area.round(1).to_dict(),
                        "spring_brown_agreement": round(spring_agree, 3),
                        "haze_dropped_by_date": dict(zip(dates, dropped.sum(0).tolist()))}
    if plot:
        plot_examples(rid, info, X, Xc, t, Z, cyc, cut, out, plot)
    return out


# ------------------------------------------------------------------ diagnostics
def plot_examples(rid, info, X, Xc, t, Z, cyc, cut, out, path, per_class=3):
    """2-3 example profiles per class: raw looks, dropped looks, smoothed curve, season cycles, cuts."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    rng = np.random.default_rng(1)
    cls = [c for c in CLASSES if (out.crop_type == c).any()]
    fig, axes = plt.subplots(len(cls), per_class, figsize=(4.2 * per_class, 1.9 * len(cls)), sharex=True,
                             sharey=True, squeeze=False)
    x_all = T0 + t.astype("timedelta64[D]")
    x_grid = T0 + GRID.astype("timedelta64[D]")
    for i, c in enumerate(cls):
        rows = np.flatnonzero((out.crop_type == c).values & (out.tier == "reliable").values)
        if not len(rows):
            rows = np.flatnonzero((out.crop_type == c).values)
        pick = rng.choice(rows, size=min(per_class, len(rows)), replace=False)
        for j in range(per_class):
            ax = axes[i, j]
            ax.axvspan(SY0, SY1, color="0.95", zorder=0)
            for y in (BARE, END, GREEN):
                ax.axhline(y, color="0.8", lw=0.6, zorder=0)
            if j >= len(pick):
                ax.axis("off")
                continue
            r = pick[j]
            for _, cy in cyc[cyc.row == r].iterrows():
                ax.axvspan(T0 + np.timedelta64(int(cy.gu), "D"), T0 + np.timedelta64(int(cy.en), "D"),
                           color="#cfe8cf" if cy.cstrict else "#f3e2c0", alpha=0.7, zorder=1)
            ax.plot(x_grid, Z[r], color="#1f6f3f", lw=1.4, zorder=3)
            ok = np.isfinite(Xc[r])
            ax.plot(x_all[ok], Xc[r, ok], "o", ms=2.6, color="#333333", zorder=4)
            dr = np.isfinite(X[r]) & ~ok
            ax.plot(x_all[dr], X[r, dr], "x", ms=4, color="#c0392b", zorder=4)
            cu = cut[r]
            ax.plot(x_all[cu], Xc[r, cu], "v", ms=5, color="#2c6fbb", zorder=5)
            o = out.iloc[r]
            stand = f" {o.stand}" if isinstance(o.stand, str) and o.stand else ""
            ax.set_title(f"{c} ({o.rule}{stand}) | id {o.id} {info.px40.iloc[r] * PX_HA:.0f} ha | {o.cycle_seq or '-'} "
                         f"| cuts {o.cuts} | stab {o.stability:.2f}", fontsize=6.5)
            ax.set_ylim(-0.05, 0.95)
            ax.tick_params(labelsize=6)
    fig.suptitle(f"{rid}: Landsat NDVI looks (dots; red x dropped as haze/spike), envelope smoothing (line), "
                 f"season cycles (green strict, tan loose), cuts (blue), season year shaded", fontsize=8)
    fig.tight_layout(rect=(0, 0, 1, 0.985))
    fig.savefig(path, dpi=110)
    plt.close(fig)


# ------------------------------------------------------------------ national
def national(rids):
    fn = pd.read_csv(ROOT / "data" / "national" / "fields_national.csv", low_memory=False,
                     usecols=["region", "id", "uid", "admin", "area_ha", "is_pivot", "class", "spring_brown"])
    parts = []
    for rid in rids:
        f = ROOT / "data" / "regions" / rid / "crop_types.csv"
        if f.exists():
            parts.append(pd.read_csv(f, keep_default_na=True).assign(region=rid))
    ct = pd.concat(parts, ignore_index=True)
    df = fn.merge(ct, on=["region", "id"], how="inner")
    df = df.rename(columns={"class": "class_v1"})
    first = ["region", "id", "uid", "admin", "area_ha", "is_pivot", "crop_type", "tier", "confidence", "n_looks",
             "n_cycles", "days_green", "longest_bare_d", "cuts", "peak1_date", "greenup1_date", "end1_date",
             "radar_winter_canopy", "radar_summer_persist", "radar_agree", "stability"]
    df = df[first + [c for c in df.columns if c not in first]]
    out = ROOT / "data" / "national" / "v2"
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "crop_types.csv", index=False)
    area = df.groupby("crop_type").area_ha.sum()
    missing = sorted(set(fn.region) - set(df.region))
    print(f"national: {len(df)} fields / {df.area_ha.sum():,.0f} ha in {df.region.nunique()} regions "
          f"(of {fn.region.nunique()}; missing {' '.join(missing) or 'none'}) | "
          + ", ".join(f"{c} {area.get(c, 0):,.0f}" for c in CLASSES if area.get(c, 0) > 0), flush=True)


if __name__ == "__main__":
    args = sys.argv[1:]
    plot = summ_path = None
    if "--plot" in args:
        i = args.index("--plot")
        plot = args[i + 1]
        del args[i:i + 2]
    if "--summary" in args:
        i = args.index("--summary")
        summ_path = args[i + 1]
        del args[i:i + 2]
    force = "--force" in args
    args = [a for a in args if a != "--force"]
    summary = {} if summ_path else None
    if args == ["all"]:
        rids = sorted(p.parent.name for p in (ROOT / "data" / "regions").glob("R*/landsat_ndvi.csv.gz"))
        me = Path(__file__).stat().st_mtime
        for rid in rids:
            R = ROOT / "data" / "regions" / rid
            f = R / "crop_types.csv"
            if not force and summary is None and f.exists() and f.stat().st_mtime > max(
                    me, (R / "landsat_ndvi.csv.gz").stat().st_mtime):
                print(rid, "crop_types.csv up to date; reused", flush=True)
                continue
            try:
                run(rid, summary=summary)
            except Exception as e:  # keep going; the region is left out of the national table
                import traceback
                traceback.print_exc()
                print(rid, "ERROR", repr(e)[:300], flush=True)
        national(rids)
    else:
        for rid in args:
            run(rid, plot=plot if len(args) == 1 else None, summary=summary)
    if summ_path:
        Path(summ_path).write_text(json.dumps(summary, indent=1, default=str))
