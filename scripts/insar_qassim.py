"""NISAR InSAR ground-movement pilot over the Qassim box: noise floor, false movement, detectability.

What it answers
  Can NISAR's 12-day L2 GUNW interferograms (track 42 / frame 15, ascending) see the
  aquifer-driven subsidence reported for the Saq belt (about 5-12 mm/yr from ENVISAT
  SBAS, Othman & Abotalib 2019; 4-15 mm/yr, Othman et al. 2018)? The honest output is a
  noise floor, the irrigation 'false movement', and how long a record is needed. It never
  produces a field-level displacement map, and nothing here is presented as subsidence.

Inputs
  data/nisar/gunw_insar/   per-pair layers from scripts/gunw_fetch.py (80 m, EPSG:32638):
                           unwrappedPhase, coherenceMagnitude, connectedComponents,
                           ionospherePhaseScreen(+Uncertainty), mask, radarGrid cubes, meta
  data/nisar/gunw_insar/dem_80m.tif   Copernicus GLO-90 heights on the same grid
  data/national/regions.json          boxes overlapping the Qassim grid (R06, R08, R11, R34)
  data/regions/<R>/fields_labels.tif, ndvi_{winter,summer,wcheck}.tif, worldcover.tif (40 m)
  data/national/fields_national.csv   owner-deduplicated fields and their Sentinel-2
                                      activity flags (join on region, id)

Method (per pair, then per segment)
  The 14 pairs form two disjoint segments: winter 2025-11-01 -> 12-31 (5 pairs, BETA
  X05010) and summer 2026-06-17 -> 10-15 (9 pairs incl. one 24-day pair, PROVISIONAL
  P05023). They are never chained across the Jan-Jun gap, and statistics are per segment.
  1. Corrections. phi_iono = unwrappedPhase - ionospherePhaseScreen (the screen is in the
     product but not applied). The wet + hydrostatic troposphere and the solid-earth-tide
     cubes are interpolated bilinearly on the 500 m grid and linearly in height at the
     DEM height (GLO-90 orthometric used as ellipsoidal; |N| of tens of metres is <10%
     of a 500 m level) and subtracted only if they lower the segment's median desert
     variance; every variant is reported.
  2. Masks. connectedComponents 0 (not in a reliable unwrapping component) or 65535 (fill);
     coherence < 0.35 (below it the 112-look phase noise exceeds ~3.5 mm per pixel and
     unwrapping errors become common); mask fill 255, water flag, an invalid subswath digit or any
     RSLC anomaly bit (8-23). Bit 24 (ionosphere screen interpolated) is reported, not
     masked. Irrigated land = mapped fields (any 40 m label pixel in the 80 m cell) or
     Sentinel-2 maximum NDVI > 0.25 in any region composite (far-desert maximum NDVI has
     p50 0.09-0.12 and p99 0.18-0.32 in these boxes; greener cells catch fallow, gardens,
     palms and small fields the 0.40 field mask misses), dilated by 2 px (160 m) against
     geocoding and edge mixing. 'Desert' for noise statistics = WorldCover shrub, grass or
     bare/sparse (20, 30, 60; no built-up, cropland, trees or water) outside that mask and
     at least 400 m (5 px) from fields and green patches of >= 4 cells (2.6 ha; isolated
     1-3 cell greens are composite speckle or lone trees, masked but not used for
     distances). Farms are dense here: about 35% of the box is irrigated land, 69% with
     the buffer, so 'desert' is about a quarter of the box.
  3. Reference. Median over a stable desert patch of >= 25 km2: the candidate cells inside
     the 10 x 10 km window that holds the most of them. Design target: desert land cover,
     >= 5 km from irrigated land, valid and coherence >= 0.5 in every pair. Only ~45 km2 of
     desert land in the box is >= 5 km from irrigated land, mostly low-coherence sand, so
     the criteria are relaxed along REF_LADDER (coherence, then the share of pairs a cell is
     valid in, then distance) and, if no window qualifies, all candidates form a
     distributed reference; the rung used is reported. The reference only shifts each pair
     by a constant, so every spread, deramped residual, chain spread and field-minus-local-
     desert offset is independent of it (only the noise map depends on it).
  4. Phase to LOS. d_LOS (mm, positive toward the satellite) = -(lambda / 4 pi) x phase,
     lambda = c / centerFrequency (1.229 GHz -> 0.24393 m, 19.41 mm/rad). Sign: ISCE3,
     the NISAR processor, forms reference x conj(secondary) (Crossmul.cpp), so positive
     phase is a range increase (motion away). The product spec D-102272 Rev E does not
     state it, so it is cross-checked empirically: the hydrostatic troposphere cube must
     follow the NASA POWER surface-pressure change (2.2768 mm zenith delay per hPa) with
     slope +1 under that convention, and subtracting the cube must lower the desert
     variance more than adding it (same convention as unwrappedPhase).
  5. Two published versions: 'corrected' (ionosphere, plus troposphere/tides where they
     help) and 'deramped' (plus a quadratic surface fitted to desert pixels and removed).
     The deramp removes wavelengths above ~20 km, i.e. broad aquifer bowls, so the
     deramped numbers bound only local (<~20 km) differential movement.
  (a) Desert noise per pair: std of 80 m pixels and of 1 km (13 x 13 px, >= 30% valid
      desert) and 5 km (63 x 63 px, >= 10% valid desert, i.e. >= 2.5 km2) block means, for
      raw / ionosphere / corrected phase, each with and without the quadratic deramp; structure
      function sqrt(E[(d(x) - d(x+r))^2] / 2) at 1-40 km; multilook theory
      sigma_phi = sqrt((1 - g^2) / (2 N g^2)), N = 16 x 7 looks. Pairs above the
      plausibility ranges of the v2 critique (deramped pixel sd > 6.8 mm, corrected 1 km
      sd > 6 mm) are flagged; they stay in the chains (dropping one would break them) and
      summaries are given for all pairs and for unflagged pairs.
  (b) False movement: per pair and field (core 80 m cells wholly inside one deduplicated
      field, >= 3 valid cells), median of deramped LOS minus the mean of desert pixels in
      a 2 km window (>= 10% desert). Fields split into active / idle by Sentinel-2 in the
      matching window (winter: s2_winter_check, max NDVI > 0.40 over 2025-12-07..12-31;
      summer: s2_summer_active, 2026-06-10..10-31). Cumulative sums over each segment,
      percentiles and AUC (active vs idle).
  (c) Chain: cumulative LOS over each segment on desert pixels valid in every pair;
      spread of 1 km and 5 km block means after k pairs.
  (d) Detectability: var(k) = a + k q fitted to the summer chain (a: per-epoch noise that
      telescopes, = 2 sigma_eps^2; q: non-closing per-pair noise that random-walks). The
      minimum detectable rate MDR = 2 sigma_v (GLS, annual sine/cosine co-estimated for
      records >= 1 yr) for (i) sequential 12-day chains, covariance
      (a/2)(I + 11') + q min(j, k); (ii) a redundant network with long pairs and the
      ionosphere corrected, where the non-closing term no longer accumulates: white
      per-epoch noise equal to one of today's 12-day pairs (a + q), with a band from half
      to double that variance (redundancy vs noisier long pairs).
      Rates are converted to vertical-equivalent with the LOS up-component from the cube
      (~0.72; an ascending-only track cannot separate horizontal motion), and the
      literature rates are treated as vertical.
  (e) Figures for the website (light theme, no baked titles) and insar.json.

Outputs (out/v2/insar/)
  insar.json                 every number, the pair list, method notes, caveats
  noise_floor_map.png        12-day LOS noise of 1 km averages over desert (fields grey)
  detectability.png          MDR vs record length against the Saq-belt bands
  false_movement.png         per-pair active vs idle field offsets
  false_movement_cumulative.png   summer-chain cumulative offsets, active vs idle
  chain_noise.png            spread of the chained desert LOS vs days

Usage:
  .venv/bin/python scripts/gunw_fetch.py      # once, about 3-4 min per pair
  .venv/bin/python scripts/insar_qassim.py    # local, under a minute
"""
import json
import os
import warnings
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import rasterio  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from pyproj import Transformer  # noqa: E402
from rasterio.enums import Resampling  # noqa: E402
from rasterio.warp import reproject  # noqa: E402
from scipy import ndimage as ndi  # noqa: E402
from scipy.optimize import nnls  # noqa: E402
from scipy.stats import rankdata  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
GUNW = ROOT / "data" / "nisar" / "gunw_insar"
REGIONS = ROOT / "data" / "regions"
REGIONS_JSON = ROOT / "data" / "national" / "regions.json"
NATIONAL = ROOT / "data" / "national" / "fields_national.csv"
OUT = ROOT / "out" / "v2" / "insar"

PX_M = 80.0
COH_MIN = 0.35          # analysis mask; 112-look phase noise is ~3.5 mm at g = 0.35 (2.2 mm at 0.5)
REF_COH_MIN = 0.5       # reference patch coherence (target: in every pair)
NDVI_MASK = 0.25        # far desert max NDVI: p50 0.09-0.12, p99 0.18-0.32; greener may carry moisture phase
GREEN_MIN_PX = 4        # green patches >= 4 cells (2.6 ha) count for distances; smaller ones are only masked
FIELD_BUFFER_PX = 2     # 160 m buffer round irrigated land (geocoding, edge mixing)
DESERT_GAP_M = 400.0    # noise statistics only on desert this far from irrigated land
REF_MIN_KM2 = 25.0
REF_MIN_PAIR_KM2 = 5.0  # and >= 5 km2 (~780 cells) of the patch valid in every single pair
REF_WIN_PX = 125        # 10 km square search window; the patch = candidate cells inside the best window
# Reference criteria tried in order until >= 25 km2 of candidates fit one window, >= 5 km2 of them
# valid in every pair (the December rain pairs decorrelate whole desert patches): (distance from
# irrigated land m, coherence rule, coherence threshold, share of pairs a cell must be valid in).
# Rung 0 is the design target (>= 5 km, coherence >= 0.5 and valid in every pair). In this box only
# ~45 km2 of desert land lies >= 5 km from irrigated land, mostly low-coherence sand, so later rungs
# relax coherence first (the reference is a median over >= 3,900 cells, so its own decorrelation
# noise is negligible), then validity (>= 80% of pairs; each pair uses the cells valid in it), then
# distance (irrigation moisture does not spread kilometres through dry sand). If no window holds
# 25 km2, every candidate cell of the last rung in the box forms a distributed reference.
# The choice only shifts each pair by a constant: block spreads, deramped residuals, chain
# spreads and field-minus-local-desert offsets do not depend on it; only the noise map does.
REF_LADDER = [(5000.0, "every_pair", REF_COH_MIN, 1.0), (5000.0, "mean", 0.45, 1.0), (5000.0, "mean", 0.45, 0.8),
              (3000.0, "mean", 0.45, 0.8), (2000.0, "mean", 0.45, 0.8), (2000.0, "mean", 0.40, 0.8),
              (1000.0, "mean", 0.45, 0.8)]
DESERT_WC = (20, 30, 60)  # WorldCover shrub, grassland, bare/sparse
BLOCK = {"1km": 13, "5km": 63}  # 1.04 km and 5.04 km blocks
# Valid desert is fragmented (about a quarter of the box, of which 20-80% is valid per pair), so a
# 5 km block mean needs >= 10% valid desert (>= 400 cells, 2.5 km2) and a 1 km block >= 30% (>= 51
# cells); the decorrelation noise of such means is a fraction of a millimetre. Spreads need >= 5 blocks.
BLOCK_MIN_FRAC = {"1km": 0.3, "5km": 0.1}
MIN_BLOCKS = 5
RAIN = ROOT / "data" / "national" / "eto_daily.csv"  # NASA POWER daily rain per region (v2 sidecar), optional
LOCAL_PX = 25           # 2 km window for the local desert reference of a field
LOCAL_MIN_FRAC = 0.10
FIELD_MIN_PX = 3        # >= 3 core 80 m cells (~2 ha) per field value
SF_KM = (1, 2, 5, 10, 20, 40)
LOOKS = 16 * 7          # numberOfAzimuthLooks x numberOfRangeLooks (from the granule meta)
SAQ_BAND = (5.0, 12.0)  # mm/yr, Othman & Abotalib 2019 (ENVISAT SBAS, central Saudi Arabia)
WEAK_BAND = (2.0, 4.0)  # mm/yr, slower subsidence (illustrative lower band)
REC_DT_DAYS = 12.0
SEED = 20261116
ZHD_M_PER_HPA = 2.2768e-3  # Saastamoinen zenith hydrostatic delay per hPa of surface pressure

# Website palette (docs/style.css tokens) + a single blue sequential ramp
INK, INK2, MUTED, LINE, LINE2, PANEL3 = "#0e1a26", "#3d4b58", "#5a6773", "#e3e7eb", "#cdd4db", "#eceff3"
BLUE, BLUE_LIGHT, SLATE = "#1d56a8", "#9ec5f4", "#8d99a6"
RAMP = LinearSegmentedColormap.from_list("blue_seq", ["#eef4fc", "#b7d3f6", "#6da7ec", "#2a78d6", "#1c5cab", "#0d366b"])


# ---------------------------------------------------------------- inputs

def load_pairs():
    """Pairs from the gunw_fetch manifest, with their meta and segment."""
    man = json.loads((GUNW / "manifest.json").read_text())
    pairs = []
    for m in man["pairs"]:
        meta = json.loads((GUNW / m["files"]["meta"]).read_text())
        if not all((GUNW / f).exists() for f in meta["files"].values()):
            continue
        meta["segment"] = "winter" if meta["ref"] < "20260301" else "summer"
        pairs.append(meta)
    return sorted(pairs, key=lambda p: p["ref"])


def read(p, layer):
    with rasterio.open(GUNW / p["files"][layer]) as s:
        return s.read(1)


def iso(d):
    return f"{d[:4]}-{d[4:6]}-{d[6:]}"


def grid_of(p):
    return rasterio.Affine(*p["grid_transform"]), tuple(p["grid_shape"]), f"EPSG:{p['epsg']}"


def land_layers(tf, shape, crs):
    """Field labels, NDVI and land cover of the overlapping region boxes on the 80 m grid."""
    h, w = shape
    xs = [tf.c, tf.c + w * tf.a]
    ys = [tf.f + h * tf.e, tf.f]
    lon, lat = Transformer.from_crs(crs, 4326, always_xy=True).transform([xs[0], xs[1], xs[0], xs[1]], [ys[0], ys[0], ys[1], ys[1]])
    gb = (min(lon), min(lat), max(lon), max(lat))
    regions = [r["id"] for r in json.loads(REGIONS_JSON.read_text())
               if r["bbox"][0] < gb[2] and r["bbox"][2] > gb[0] and r["bbox"][1] < gb[3] and r["bbox"][3] > gb[1]
               and (REGIONS / r["id"] / "fields_labels.tif").exists()]
    nat = pd.read_csv(NATIONAL, usecols=["id", "region", "area_ha", "is_pivot", "s2_winter_check", "s2_summer_active"],
                      dtype={"s2_winter_check": str, "s2_summer_active": str, "is_pivot": str})
    nat = nat[nat.region.isin(regions)]
    tri = {"True": True, "False": False}
    nat["act_winter"], nat["act_summer"] = nat.s2_winter_check.map(tri), nat.s2_summer_active.map(tri)
    kept = set(zip(nat.region, nat.id))

    frac = np.zeros(shape, "float32")
    ndvi = np.full(shape, np.nan, "float32")
    wc = np.zeros(shape, "uint8")
    uid = np.zeros(shape, "int64")
    for ri, R in enumerate(regions):
        d = REGIONS / R
        with rasterio.open(d / "fields_labels.tif") as s:
            lab = s.read(1)
            labf = (lab > 0).astype("float32")
            fr = np.full(shape, np.nan, "float32")
            reproject(labf, fr, src_transform=s.transform, src_crs=s.crs, dst_transform=tf, dst_crs=crs,
                      resampling=Resampling.average, src_nodata=-1, dst_nodata=np.nan)
            lo, hi = np.zeros(shape, "int32"), np.zeros(shape, "int32")
            for arr, rs in ((lo, Resampling.min), (hi, Resampling.max)):
                reproject(lab, arr, src_transform=s.transform, src_crs=s.crs, dst_transform=tf, dst_crs=crs,
                          resampling=rs, src_nodata=-1, dst_nodata=0)
        cover = np.isfinite(fr)
        frac = np.where(cover, np.fmax(frac, fr), frac)
        # a core cell lies wholly inside one field (2 x 2 label pixels, same id) owned by this region
        pure = cover & (fr >= 0.999) & (lo == hi) & (lo > 0)
        own = np.array([(R, int(i)) in kept for i in lo[pure]], bool)
        cell = np.zeros(shape, bool)
        cell[pure] = own
        cell &= uid == 0
        uid[cell] = ri * 1_000_000 + lo[cell]
        nd = None
        for season in ("winter", "summer", "wcheck"):
            p = d / f"ndvi_{season}.tif"
            if p.exists():
                with rasterio.open(p) as s:
                    a = np.full(shape, np.nan, "float32")
                    reproject(s.read(1), a, src_transform=s.transform, src_crs=s.crs, dst_transform=tf, dst_crs=crs,
                              resampling=Resampling.max, src_nodata=np.nan, dst_nodata=np.nan)
                nd = a if nd is None else np.fmax(nd, a)
        ndvi = np.fmax(ndvi, nd)
        w_ = np.zeros(shape, "uint8")
        with rasterio.open(d / "worldcover.tif") as s:
            reproject(s.read(1), w_, src_transform=s.transform, src_crs=s.crs, dst_transform=tf, dst_crs=crs,
                      resampling=Resampling.mode, src_nodata=0, dst_nodata=0)
        wc = np.where(wc == 0, w_, wc)

    region_of = {ri: R for ri, R in enumerate(regions)}
    ids = np.unique(uid[uid > 0])
    nat_i = nat.set_index(["region", "id"])
    rows = [(u, region_of[u // 1_000_000], u % 1_000_000) for u in ids]
    table = pd.DataFrame(rows, columns=["uid", "region", "id"]).set_index("uid")
    j = nat_i.loc[list(zip(table.region, table.id))]
    for c in ("act_winter", "act_summer", "area_ha"):
        table[c] = j[c].values
    table["is_pivot"] = (j["is_pivot"].values == "True")

    fields = frac > 0
    green = (ndvi > NDVI_MASK) & ~fields
    land = fields | green
    irrigated = ndi.binary_dilation(land, structure=np.ones((3, 3), bool), iterations=FIELD_BUFFER_PX)
    # distances are measured from fields and green patches >= GREEN_MIN_PX; isolated 1-3 cell
    # greens (half of the 12k green objects are single cells: composite speckle, lone trees)
    # are masked but do not push the desert or the reference patch away
    lab, _ = ndi.label(green, structure=np.ones((3, 3), bool))
    big = np.bincount(lab.ravel()) >= GREEN_MIN_PX
    big[0] = False
    dist = ndi.distance_transform_edt(~(fields | big[lab])) * PX_M
    desert_lc = np.isin(wc, DESERT_WC) & ~irrigated
    return {"regions": regions, "frac": frac, "ndvi": ndvi, "wc": wc, "uid": uid, "table": table, "land": land,
            "irrigated": irrigated, "dist_m": dist, "desert": desert_lc & (dist >= DESERT_GAP_M),
            "desert_lc": desert_lc, "coverage": float(np.isfinite(ndvi).mean()),
            "green_share": float(green.mean()), "field_share": float(fields.mean())}


def cube_sampler(p, tf, shape):
    """Fractional cube indices of the 80 m pixel centres (same cube grid for every pair)."""
    with rasterio.open(GUNW / p["files"]["losUnitVectorX"]) as s:
        ctf = s.transform
    r, c = np.mgrid[0:shape[0], 0:shape[1]]
    x, y = tf.c + (c + 0.5) * tf.a, tf.f + (r + 0.5) * tf.e
    return np.stack([(y - ctf.f) / ctf.e - 0.5, (x - ctf.c) / ctf.a - 0.5])


def cube_at(p, layer, coords, h):
    """Cube interpolated bilinearly in the plane and linearly in height at h (m)."""
    with rasterio.open(GUNW / p["files"][layer]) as s:
        cube = s.read().astype("float64")
        heights = np.array([float(v) for v in s.tags()["heights_m"].split(",")])
    planes = np.stack([ndi.map_coordinates(c, coords, order=1, mode="nearest") for c in cube])
    kf = np.clip((h - heights[0]) / (heights[1] - heights[0]), 0, len(heights) - 1 - 1e-9)
    k = np.floor(kf).astype(int)
    wgt = kf - k
    lo = np.take_along_axis(planes, k[None], 0)[0]
    hi = np.take_along_axis(planes, (k + 1)[None], 0)[0]
    return lo * (1 - wgt) + hi * wgt


def mask_ok(m):
    """GUNW mask: fill 255; low byte = decimal water/ref-subswath/sec-subswath code; bits 8-23 anomalies."""
    low = m & 0xFF
    return (m != 255) & (low // 100 != 1) & ((low // 10) % 10 > 0) & (low % 10 > 0) & (((m >> 8) & 0xFFFF) == 0)


def reference_patch(pairs, L, shape):
    """Stable desert reference: the first REF_LADDER rung with >= 25 km2 of candidates in one
    10 km window, else all candidate cells of the last rung (distributed reference)."""
    valid = np.stack([p["valid"] for p in pairs])
    valid_share = valid.mean(axis=0)
    coh = np.stack([p["coh"] for p in pairs])
    h2 = REF_WIN_PX // 2
    km2 = (PX_M / 1000) ** 2

    def ok(ref):
        return ref.sum() * km2 >= REF_MIN_KM2 and (valid & ref).sum(axis=(1, 2)).min() * km2 >= REF_MIN_PAIR_KM2

    for rung, (dist_m, rule, thr, vshare) in enumerate(REF_LADDER):
        coh_ok = (coh >= thr).all(0) if rule == "every_pair" else np.nanmean(coh, 0) >= thr
        cand = L["desert_lc"] & (L["dist_m"] >= dist_m) & (valid_share >= vshare - 1e-9) & coh_ok
        cnt = ndi.uniform_filter(cand.astype("float64"), REF_WIN_PX, mode="constant") * REF_WIN_PX ** 2
        r, c = np.unravel_index(np.argmax(cnt), cnt.shape)
        win = [int(max(r - h2, 0)), int(min(r - h2 + REF_WIN_PX, shape[0])), int(max(c - h2, 0)),
               int(min(c - h2 + REF_WIN_PX, shape[1]))]
        ref = np.zeros(shape, bool)
        ref[win[0]:win[1], win[2]:win[3]] = True
        ref &= cand
        if ok(ref):
            break
    else:
        ref, win = cand, [0, shape[0], 0, shape[1]]
        if not ok(ref):
            raise SystemExit("no stable desert reference (25 km2, 5 km2 valid per pair) on any REF_LADDER rung")
    rr, cc_ = np.where(ref)
    info = {"km2": float(ref.sum() * (PX_M / 1000) ** 2), "window_px": win,
            "distributed": bool(win == [0, shape[0], 0, shape[1]]), "ladder_rung": rung,
            "design_target_met": rung == 0, "min_distance_from_irrigated_m": dist_m, "coherence_rule": rule,
            "coherence_min": thr, "valid_share_min": vshare,
            "valid_km2_per_pair_min": float((valid & ref).sum(axis=(1, 2)).min() * km2),
            "coherence_mean_in_patch": float(np.nanmean(coh[:, ref])),
            "pair_median_coherence_in_patch_min": float(np.min(np.nanmedian(coh[:, ref], axis=1))),
            "far_desert_km2_at_5km": float((L["desert_lc"] & (L["dist_m"] >= 5000)).sum() * (PX_M / 1000) ** 2),
            "far_desert_mean_coherence_at_5km": float(np.nanmedian(np.nanmean(coh, 0)[L["desert_lc"] & (L["dist_m"] >= 5000)])),
            "centroid_px": [float(rr.mean()), float(cc_.mean())]}
    return ref, info


def rain_between(pairs, regions):
    """POWER daily rain (mean of the overlapping regions) summed over (ref, sec] of each pair."""
    if not RAIN.exists():
        return {}
    d = pd.read_csv(RAIN, usecols=["region", "date", "precip_mm"])
    d = d[d.region.isin(regions)].groupby("date").precip_mm.mean()
    return {p["ref"]: float(d[(d.index > iso(p["ref"])) & (d.index <= iso(p["sec"]))].sum()) for p in pairs}


def sign_check(pairs, inc_deg):
    """Independent check of the phase sign from the hydrostatic troposphere cube.

    The cube should equal +/-(4 pi / lambda) x 2.2768 mm/hPa x dP / cos(incidence), with dP the
    surface-pressure change secondary minus reference (NASA POWER, 00 UTC: the ECMWF HRES time
    the run configuration lists). Slope +1 means the cube is positive when the secondary has more
    delay, i.e. positive phase = range increase. If subtracting the cube also lowers the desert
    variance (troposphere_sign_check), unwrappedPhase shares that convention.
    """
    path = GUNW / "power_ps_hourly.json"
    if not path.exists():
        return None
    ps = json.loads(path.read_text())["ps_kpa"]
    rows = []
    for p in pairs:
        dp = (ps[p["sec"] + "00"] - ps[p["ref"] + "00"]) * 10.0
        pred = 4 * np.pi / p["wavelength_m"] * ZHD_M_PER_HPA * dp / np.cos(np.radians(inc_deg))
        rows.append({"ref": iso(p["ref"]), "sec": iso(p["sec"]), "dP_hPa": float(dp),
                     "cube_rad": float(np.median(p["hydro"])), "predicted_rad": float(pred)})
    x = np.array([r["predicted_rad"] for r in rows])
    y = np.array([r["cube_rad"] for r in rows])
    return {"slope_cube_vs_predicted": float(x @ y / (x @ x)), "correlation": float(np.corrcoef(x, y)[0, 1]),
            "pairs": rows,
            "meaning": "slope ~ +1: the cube is positive for more delay (range increase) at the secondary date"}


# ---------------------------------------------------------------- statistics

def block_means(d, m, b, min_frac):
    h, w = (d.shape[0] // b) * b, (d.shape[1] // b) * b
    v = np.where(m, d, np.nan)[:h, :w].reshape(h // b, b, w // b, b)
    n = np.isfinite(v).sum(axis=(1, 3))
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.nansum(v, axis=(1, 3)) / n
    return mean[n >= min_frac * b * b]


def noise(d, m):
    out = {"sd_px": float(np.std(d[m]))}
    for k, b in BLOCK.items():
        bm = block_means(d, m, b, BLOCK_MIN_FRAC[k])
        out[f"sd_{k}"] = float(np.std(bm)) if bm.size >= MIN_BLOCKS else None
        out[f"n_{k}"] = int(bm.size)
    return out


def structure_function(d, m, rng):
    iy, ix = np.where(m)
    sel = rng.choice(iy.size, min(30000, iy.size), replace=False)
    iy, ix = iy[sel], ix[sel]
    out = {}
    for km in SF_KM:
        r = km * 1000 / PX_M
        ang = rng.uniform(0, 2 * np.pi, iy.size)
        jy, jx = np.round(iy + r * np.sin(ang)).astype(int), np.round(ix + r * np.cos(ang)).astype(int)
        ok = (jy >= 0) & (jy < m.shape[0]) & (jx >= 0) & (jx < m.shape[1])
        ok[ok] &= m[jy[ok], jx[ok]]
        dd = d[iy[ok], ix[ok]] - d[jy[ok], jx[ok]]
        out[f"{km}km"] = float(np.sqrt(np.mean(dd ** 2) / 2)) if dd.size > 200 else None
    return out


def surface(m, order):
    """Design matrix columns (km, centred) for a planar or quadratic ramp."""
    r, c = np.mgrid[0:m.shape[0], 0:m.shape[1]]
    X, Y = (c - m.shape[1] / 2) * PX_M / 1000, (r - m.shape[0] / 2) * PX_M / 1000
    cols = [np.ones_like(X), X, Y] + ([X * X, X * Y, Y * Y] if order == 2 else [])
    return cols


def deramp(d, m, order, ref):
    cols = surface(m, order)
    A = np.stack([q[m] for q in cols], 1)
    co, *_ = np.linalg.lstsq(A, d[m], rcond=None)
    r = d - sum(ci * q for ci, q in zip(co, cols))
    return r - np.nanmedian(r[ref])


def median_ci(v, rng, n_boot=1000):
    if v.size < 5:
        return [None, None]
    idx = rng.integers(0, v.size, (n_boot, v.size))
    meds = np.median(v[idx], axis=1)
    return [float(np.percentile(meds, 2.5)), float(np.percentile(meds, 97.5))]


def auc(x, y):
    """Probability that a random active field's value is below a random idle one's (x active, y idle)."""
    r = rankdata(np.r_[x, y])
    n1, n0 = x.size, y.size
    u_low = n1 * n0 - (r[:n1].sum() - n1 * (n1 + 1) / 2)
    return float(u_low / (n1 * n0))


def rate_sigma(t_years, a, q, seasonal):
    """GLS 1-sigma of a linear rate, epochs t (yr) relative to epoch 0; cov (a/2)(I+11') + q min(j,k)."""
    n = t_years.size
    j = np.arange(1, n + 1)
    C = (a / 2.0) * (np.eye(n) + 1.0) + q * np.minimum.outer(j, j)
    cols = [t_years]
    if seasonal:
        cols += [np.sin(2 * np.pi * t_years), np.cos(2 * np.pi * t_years) - 1.0]
    A = np.stack(cols, 1)
    N = A.T @ np.linalg.solve(C, A)
    return float(np.sqrt(np.linalg.inv(N)[0, 0]))


def mdr_curve(years, a, q, up):
    """2-sigma minimum detectable vertical-equivalent rate for regular 12-day sampling."""
    out = []
    for T in years:
        n = int(np.floor(T * 365.25 / REC_DT_DAYS + 1e-9))
        t = np.arange(1, n + 1) * REC_DT_DAYS / 365.25
        out.append(2 * rate_sigma(t, a, q, seasonal=T >= 1.0) / up)
    return np.array(out)


def first_below(years, curve, thr):
    """First record length >= 1 yr whose MDR is <= thr (shorter records cannot separate the
    annual cycle from a trend, so a sub-year crossing would be optimistic); 1.0 means 'by 1 yr'."""
    hit = np.where((curve <= thr) & (years >= 1.0 - 1e-9))[0]
    return round(float(years[hit[0]]), 2) if hit.size else None


def rnd(x, k=3):
    """JSON-safe rounding: k decimals, but 5 significant digits below 1 (wavelength, fractions)."""
    if x is None:
        return None
    if isinstance(x, dict):
        return {kk: rnd(v, k) for kk, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [rnd(v, k) for v in x]
    if isinstance(x, (float, np.floating)):
        if not np.isfinite(x):
            return None
        return float(f"{float(x):.5g}") if abs(x) < 1 else round(float(x), k)
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.bool_):
        return bool(x)
    return x


# ---------------------------------------------------------------- figures

def style():
    plt.rcParams.update({
        "font.family": ["Helvetica Neue", "Arial", "DejaVu Sans"], "font.size": 12, "axes.edgecolor": LINE2,
        "axes.labelcolor": INK2, "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False,
        "axes.spines.right": False, "axes.grid": True, "grid.color": LINE, "grid.linewidth": 0.8,
        "axes.axisbelow": True, "legend.frameon": False, "figure.facecolor": "white", "axes.facecolor": "white",
        "savefig.facecolor": "white", "savefig.dpi": 200})


def save(fig, name):
    tmp = OUT / f".{name}.tmp.png"
    fig.savefig(tmp, bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)
    os.replace(tmp, OUT / name)


def fig_noise_map(nmap, show, land_buf, ref_window, vmax):
    """ref_window = (r0, r1, c0, c1) of a compact reference patch, or None for a distributed one."""
    h, w = nmap.shape
    fig, ax = plt.subplots(figsize=(8, 8 * h / w + 0.9))
    ax.grid(False)
    base = np.where(land_buf, 1.0, np.nan)
    ax.imshow(np.where(np.isnan(base), 0.0, 1.0), cmap=LinearSegmentedColormap.from_list("g", ["#ffffff", "#d5dbe1"]),
              vmin=0, vmax=1, interpolation="nearest")
    im = ax.imshow(np.where(show, nmap, np.nan), cmap=RAMP, vmin=0, vmax=vmax, interpolation="nearest")
    handles = [Patch(fc="#d5dbe1", ec="none", label="not used: fields, other green land, towns + buffer"),
               Patch(fc="white", ec=LINE2, lw=0.8, label="desert with too few coherent pairs")]
    if ref_window is not None:
        r0, r1, c0, c1 = ref_window
        ax.add_patch(plt.Rectangle((c0 - 0.5, r0 - 0.5), c1 - c0, r1 - r0, fill=False, ec=INK, lw=1.4))
        handles.append(Patch(fc="none", ec=INK, lw=1.4, label="reference desert window"))
    bar = 10_000 / PX_M
    ax.plot([w - 30 - bar, w - 30], [h - 25, h - 25], color=INK, lw=3, solid_capstyle="butt")
    ax.text(w - 30 - bar / 2, h - 35, "10 km", ha="center", va="bottom", color=INK, fontsize=11)
    ax.set_xticks([]), ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    cb = fig.colorbar(im, ax=ax, orientation="horizontal", fraction=0.045, pad=0.03, aspect=40, extend="max")
    cb.set_label("12-day line-of-sight noise of 1 km averages (mm)", color=INK2)
    cb.outline.set_visible(False)
    cb.ax.tick_params(color=MUTED, labelcolor=MUTED)
    leg = ax.legend(handles=handles,
                    loc="upper left", fontsize=10.5, handlelength=1.2, labelcolor=INK2, frameon=True, framealpha=0.92,
                    borderpad=0.5)
    leg.get_frame().set_edgecolor("none")
    save(fig, "noise_floor_map.png")


def fig_detectability(years, chain, net_lo, net_mid, net_hi, broad, current):
    fig, ax = plt.subplots(figsize=(8, 5.0))
    ax.axhspan(*SAQ_BAND, color=PANEL3, lw=0, zorder=0, label="Saq-belt subsidence, 5-12 mm/yr (ENVISAT era)")
    ax.axhspan(*WEAK_BAND, color="#f6f7f9", lw=0, zorder=0, label="slower subsidence, 2-4 mm/yr")
    sub, yr = years < 1.0, years >= 1.0
    ax.fill_between(years[yr], net_lo[yr], net_hi[yr], color=BLUE_LIGHT, alpha=0.45, lw=0)
    ax.plot(years[yr], chain[yr], color=INK2, lw=2, label="12-day pairs chained (today's GUNW)")
    ax.plot(years[sub], chain[sub], color=INK2, lw=2, ls=":")
    ax.plot(years[yr], net_mid[yr], color=BLUE, lw=2, label="network with long pairs (range shaded)")
    ax.plot(years[sub], net_mid[sub], color=BLUE, lw=2, ls=":")
    ax.plot(years[yr], broad[yr], color=SLATE, lw=1.6, ls="--", label="network, no deramp (bowls > 20 km)")
    top = max(c["mdr"] for c in current)
    for c in current:  # label the higher marker above-right, the lower one below-right
        ax.plot(c["years"], c["mdr"], "o", ms=8, mfc="white", mec=INK, mew=1.8, zorder=5)
        up_ = c["mdr"] == top
        ax.annotate(f"{c['label']}: {c['mdr']:.0f} mm/yr", (c["years"], c["mdr"]), xytext=(12, 9 if up_ else -10),
                    textcoords="offset points", fontsize=10.5, color=INK, va="center",
                    bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.85))
    ax.set_yscale("log")
    ymin = 1.0  # below ~1 mm/yr the white-noise network model is not credible (systematic floors)
    ymax = max(100.0, 1.3 * max(c["mdr"] for c in current))
    ticks = [t for t in (0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500) if ymin <= t <= ymax]
    ax.set_ylim(ymin, ymax)
    ax.set_yticks(ticks)
    ax.set_yticklabels([f"{t:g}" for t in ticks])
    ax.yaxis.set_minor_locator(matplotlib.ticker.NullLocator())
    ax.set_xlim(0, 6)
    ax.set_xlabel("Length of continuous NISAR record (years; dotted: under 1 year, seasons not separable)")
    ax.set_ylabel("Smallest detectable rate (mm/yr, vertical, 2σ)")
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncols=2, fontsize=10, labelcolor=INK2,
              handlelength=1.6, columnspacing=1.2)
    save(fig, "detectability.png")


def fig_false_movement(rows):
    fig, ax = plt.subplots(figsize=(8, 4.4))
    xs, labels, gap = [], [], 0
    for i, r in enumerate(rows):
        if i and r["segment"] != rows[i - 1]["segment"]:
            gap += 1
        xs.append(i + gap)
        labels.append(f"{r['ref'][5:7]}/{r['ref'][8:]}" + (f"\n({r['dt_days']:.0f} d)" if r["dt_days"] > 13 else ""))
    xs = np.array(xs, float)
    wbar = 0.38
    for key, col, off, lab in (("active", BLUE, -wbar / 2, "fields green in Sentinel-2 (irrigated)"),
                               ("idle", SLATE, wbar / 2, "fields bare in that season (idle)")):
        med = np.array([r[key]["median_mm"] if r[key]["median_mm"] is not None else np.nan for r in rows])
        lo = np.array([r[key]["ci95_mm"][0] if r[key]["ci95_mm"][0] is not None else np.nan for r in rows])
        hi = np.array([r[key]["ci95_mm"][1] if r[key]["ci95_mm"][1] is not None else np.nan for r in rows])
        ax.bar(xs + off, med, width=wbar - 0.04, color=col, label=lab, zorder=2)
        ax.errorbar(xs + off, med, yerr=[med - lo, hi - med], fmt="none", ecolor=INK2, elinewidth=1.1, capsize=0, zorder=3)
    ax.axhline(0, color=LINE2, lw=1, zorder=1)
    ax.set_xticks(xs)
    ax.set_xticklabels(labels, fontsize=10, rotation=0)
    ax.tick_params(axis="x", length=0)
    ax.grid(axis="x", visible=False)
    seg_x = {s: xs[[i for i, r in enumerate(rows) if r["segment"] == s]] for s in ("winter", "summer")}
    for s, name in (("winter", "Nov-Dec 2025"), ("summer", "Jun-Oct 2026")):
        if seg_x[s].size:
            ax.text(seg_x[s].mean(), -0.13, name, ha="center", va="top", fontsize=11, color=INK,
                    transform=ax.get_xaxis_transform())
    ax.set_ylabel("Apparent movement vs nearby desert\n(mm along line of sight; < 0 = away)")
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), fontsize=10.5, labelcolor=INK2, ncols=2,
              handlelength=1.2, columnspacing=1.5)
    save(fig, "false_movement.png")


def fig_cumulative(act, idle, seg_name):
    fig, ax = plt.subplots(figsize=(8, 4.2))
    lo, hi = np.percentile(np.r_[act, idle], [0.5, 99.5])
    bins = np.linspace(lo, hi, 36)  # ~2.5 mm bins for ~150 fields
    for v, col, lab in ((idle, SLATE, f"idle fields (n = {idle.size})"), (act, BLUE, f"irrigated fields (n = {act.size})")):
        ax.hist(v, bins=bins, density=True, histtype="stepfilled", color=col, alpha=0.30, lw=0)
        ax.hist(v, bins=bins, density=True, histtype="step", color=col, lw=2, label=lab)
        ax.axvline(np.median(v), color=col, lw=1.4, ls="--")
    ax.axvline(0, color=LINE2, lw=1)
    ax.set_yticks([])
    ax.grid(axis="y", visible=False)
    ax.spines["left"].set_visible(False)
    ax.set_xlabel(f"Summed apparent movement over the {seg_name} chain (mm along line of sight)")
    ax.legend(loc="upper left", fontsize=10.5, labelcolor=INK2)
    save(fig, "false_movement_cumulative.png")


def fig_chain(chains):
    fig, ax = plt.subplots(figsize=(8, 4.2))
    for seg, ls in (("summer", "-"), ("winter", "--")):
        if seg not in chains:
            continue
        st = chains[seg]["deramped"]
        days = [0] + [s["days"] for s in st]
        for k, col in (("1km", SLATE), ("5km", BLUE)):
            ax.plot(days, [0] + [s[f"sd_{k}"] for s in st], color=col, lw=2, ls=ls, marker="o", ms=5,
                    label=f"{'Jun-Oct 2026' if seg == 'summer' else 'Nov-Dec 2025'}, {k[:-2]} km averages")
    ax.set_xlabel("Days since the first acquisition of the segment")
    ax.set_ylabel("Spread of summed desert LOS (mm)")
    ax.set_ylim(bottom=0)
    ax.legend(loc="lower right", fontsize=10.5, labelcolor=INK2)
    save(fig, "chain_noise.png")


# ---------------------------------------------------------------- main

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    pairs = load_pairs()
    if len(pairs) < 14:
        print(f"WARNING: only {len(pairs)} of 14 pairs fetched; run scripts/gunw_fetch.py first")
    tf, shape, crs = grid_of(pairs[0])
    with rasterio.open(GUNW / "dem_80m.tif") as s:
        dem = s.read(1).astype("float64")
    dem = np.where(np.isfinite(dem), dem, np.nanmedian(dem))
    L = land_layers(tf, shape, crs)
    coords = cube_sampler(pairs[0], tf, shape)

    # geometry at the DEM height (same orbit track for every pair; use the first)
    lx, ly = cube_at(pairs[0], "losUnitVectorX", coords, dem), cube_at(pairs[0], "losUnitVectorY", coords, dem)
    up = np.sqrt(np.clip(1 - lx ** 2 - ly ** 2, 0, 1))
    inc = cube_at(pairs[0], "incidenceAngle", coords, dem)
    UP = float(np.median(up))

    # per-pair arrays and validity
    for p in pairs:
        p["unw"] = read(p, "unwrappedPhase").astype("float64")
        p["iono"] = read(p, "ionospherePhaseScreen").astype("float64")
        p["coh"] = read(p, "coherenceMagnitude")
        cc, mk = read(p, "connectedComponents"), read(p, "mask")
        p["cc0_frac"] = float(np.mean((cc == 0) | (cc == 65535)))
        p["iono_interp_frac"] = float(np.mean(((mk >> 24) & 1) == 1))
        p["mask_bad_frac"] = float(np.mean(~mask_ok(mk)))
        p["valid"] = (np.isfinite(p["unw"]) & np.isfinite(p["iono"]) & (cc != 0) & (cc != 65535)
                      & (p["coh"] >= COH_MIN) & mask_ok(mk))
        p["hydro"] = cube_at(p, "hydrostaticTroposphericPhaseScreen", coords, dem)
        p["tropo"] = cube_at(p, "wetTroposphericPhaseScreen", coords, dem) + p["hydro"]
        p["set"] = cube_at(p, "slantRangeSolidEarthTidesPhase", coords, dem)
        p["mm_per_rad"] = p["wavelength_m"] / (4 * np.pi) * 1000.0
        p["iono_unc_mm"] = float(np.nanmedian(read(p, "ionospherePhaseScreenUncertainty")[L["desert"]]) * p["mm_per_rad"])

    ref, ref_info = reference_patch(pairs, L, shape)
    ref_win = ref_info["window_px"]
    cy, cx = ref_info["centroid_px"]
    ref_lon, ref_lat = Transformer.from_crs(crs, 4326, always_xy=True).transform(
        tf.c + (cx + 0.5) * PX_M, tf.f - (cy + 0.5) * PX_M)
    ref_info["center_lonlat"] = [ref_lon, ref_lat]
    ref_km2 = ref_info["km2"]

    def to_mm(p, phase):
        """Reference to the patch median, then LOS mm, positive toward the satellite."""
        return -(phase - np.nanmedian(phase[ref & p["valid"]])) * p["mm_per_rad"]

    sign = sign_check(pairs, float(np.median(inc)))
    rain = rain_between(pairs, L["regions"])

    # versions of the corrected phase; troposphere / tides kept per segment only if they help
    variants = {"raw": lambda p: p["unw"], "iono": lambda p: p["unw"] - p["iono"],
                "iono_tropo": lambda p: p["unw"] - p["iono"] - p["tropo"],
                "iono_tropo_set": lambda p: p["unw"] - p["iono"] - p["tropo"] - p["set"],
                "iono_set": lambda p: p["unw"] - p["iono"] - p["set"],
                # diagnostic only (never chosen): the troposphere cube added instead of subtracted.
                # If subtracting beats adding in most pairs, the cube shares the phase convention.
                "iono_plus_tropo": lambda p: p["unw"] - p["iono"] + p["tropo"]}
    for p in pairs:
        m = p["valid"] & L["desert"]
        p["m"] = m
        p["var"] = {}
        for name, fn in variants.items():
            d = to_mm(p, fn(p))
            p["var"][name] = {"corrected": noise(d, m), "deramped": noise(deramp(d, m, 2, ref & p["valid"]), m)}
    chosen = {}
    for seg in ("winter", "summer"):
        sp = [p for p in pairs if p["segment"] == seg]
        if not sp:
            continue
        score = {v: float(np.median([p["var"][v]["corrected"]["sd_1km"] ** 2 for p in sp]))
                 for v in ("iono", "iono_tropo", "iono_tropo_set", "iono_set")}
        chosen[seg] = {"variant": min(score, key=score.get), "median_var_1km_mm2": score}

    # final per-pair fields: corrected and deramped LOS (mm)
    for p in pairs:
        v = chosen[p["segment"]]["variant"]
        d = to_mm(p, variants[v](p))
        p["d"] = np.where(p["valid"], d, np.nan)
        p["dq"] = np.where(p["valid"], deramp(d, p["m"], 2, ref & p["valid"]), np.nan)
        p["dp"] = np.where(p["valid"], deramp(d, p["m"], 1, ref & p["valid"]), np.nan)
        g = np.clip(p["coh"][p["m"]].astype("float64"), 0.05, 0.999)
        sig_phi = np.sqrt((1 - g ** 2) / (2 * LOOKS * g ** 2))
        p["theory_px_mm"] = float(np.sqrt(np.mean(sig_phi ** 2)) * p["mm_per_rad"])
        p["sf_deramped"] = structure_function(p["dq"], p["m"], rng)
        p["sf_corrected"] = structure_function(p["d"], p["m"], rng)
        iono_d = p["iono"][p["m"]]
        p["iono_spread_rad"] = float(np.subtract(*np.percentile(iono_d, [98, 2])))
        raw_d = p["unw"][p["m"]]
        p["raw_spread_rad"] = float(np.subtract(*np.percentile(raw_d, [98, 2])))

    # (a) plausibility flags (ranges from the v2 critique: deramped desert sd 2.7-6.8 mm,
    # ionosphere-corrected without deramp <= ~6 mm at 1 km); flagged pairs stay in the chain
    # (dropping one would break it); summaries are given with and without them
    for p in pairs:
        dq = p["var"][chosen[p["segment"]]["variant"]]["deramped"]["sd_px"]
        c1 = p["var"][chosen[p["segment"]]["variant"]]["corrected"]["sd_1km"]
        p["flags"] = ([f"deramped desert sd {dq:.1f} mm > 6.8"] if dq > 6.8 else []) + \
                     ([f"corrected 1 km sd {c1:.1f} mm > 6"] if c1 > 6.0 else [])

    # (b) false movement on fields: field minus local desert, per pair and cumulative
    uid, table = L["uid"], L["table"]
    rows_fm, per_field = [], {}
    for p in pairs:
        dm = np.where(p["m"], p["dq"], 0.0)
        dn = p["m"].astype("float64")
        num = ndi.uniform_filter(dm, LOCAL_PX, mode="constant")
        den = ndi.uniform_filter(dn, LOCAL_PX, mode="constant")
        off = p["dq"] - num / np.maximum(den, 1e-9)
        ok = p["valid"] & (uid > 0) & (den >= LOCAL_MIN_FRAC) & np.isfinite(off)
        g = pd.Series(off[ok]).groupby(uid[ok]).agg(["median", "size"])
        g = g[g["size"] >= FIELD_MIN_PX]["median"]
        per_field[p["ref"]] = g
        act_col = "act_winter" if p["segment"] == "winter" else "act_summer"
        act = table.loc[g.index, act_col]
        row = {"ref": iso(p["ref"]), "sec": iso(p["sec"]), "dt_days": p["dt_days"], "segment": p["segment"]}
        for key, sel in (("active", act == True), ("idle", act == False)):  # noqa: E712 (object column)
            v = g[sel.values].values
            row[key] = {"median_mm": float(np.median(v)) if v.size else None, "ci95_mm": median_ci(v, rng),
                        "p25_mm": float(np.percentile(v, 25)) if v.size else None,
                        "p75_mm": float(np.percentile(v, 75)) if v.size else None, "n_fields": int(v.size)}
        rows_fm.append(row)

    cum = {}
    for seg in ("winter", "summer"):
        sp = [p for p in pairs if p["segment"] == seg]
        if not sp:
            continue
        df = pd.concat([per_field[p["ref"]] for p in sp], axis=1).dropna()
        tot = df.sum(axis=1)
        act = table.loc[tot.index, "act_winter" if seg == "winter" else "act_summer"]
        a_, i_ = tot[(act == True).values].values, tot[(act == False).values].values  # noqa: E712
        cum[seg] = {"pairs": len(sp), "days": float(sum(p["dt_days"] for p in sp)), "n_active": int(a_.size),
                    "n_idle": int(i_.size),
                    "active_mm": {"median": float(np.median(a_)), "p10": float(np.percentile(a_, 10)),
                                  "p90": float(np.percentile(a_, 90))},
                    "idle_mm": {"median": float(np.median(i_)), "p10": float(np.percentile(i_, 10)),
                                "p90": float(np.percentile(i_, 90))},
                    "auc_active_below_idle": auc(a_, i_), "_a": a_, "_i": i_}

    # (c) chained desert LOS per segment
    chains = {}
    for seg in ("winter", "summer"):
        sp = [p for p in pairs if p["segment"] == seg]
        if not sp:
            continue
        M = L["desert"].copy()
        for p in sp:
            M &= p["valid"]
        chains[seg] = {"desert_px": int(M.sum())}
        for ver, key in (("corrected", "d"), ("deramped", "dq"), ("planar", "dp")):
            acc, days, steps = np.zeros(shape), 0.0, []
            for k, p in enumerate(sp, 1):
                acc = acc + np.nan_to_num(p[key])
                days += p["dt_days"]
                steps.append({"k": k, "days": round(days, 3), **noise(acc, M)})
            chains[seg][ver] = steps

    # (d) detectability: var(k) = a + k q from the summer chain (5 km blocks primary)
    cal = {}
    for seg in chains:
        for ver in ("deramped", "corrected"):
            for b in ("1km", "5km"):
                st = [s for s in chains[seg][ver] if s[f"sd_{b}"] is not None]
                if len(st) < 3:
                    continue
                k = np.array([s["k"] for s in st], float)
                var = np.array([s[f"sd_{b}"] ** 2 for s in st])
                q, a = np.polyfit(k, var, 1)                       # free fit, reported
                (a_nn, q_nn), _ = nnls(np.stack([np.ones_like(k), k], 1), var)  # a, q >= 0, used
                cal[f"{seg}_{ver}_{b}"] = {"a_mm2": float(a), "q_mm2_per_pair": float(q),
                                           "a_used": float(max(a_nn, 1e-6)), "q_used": float(q_nn),
                                           "k": k.astype(int).tolist(), "var_k_mm2": var.tolist()}
    base = cal["summer_deramped_5km"]
    broad_cal = cal["summer_corrected_5km"]
    A0, Q0 = base["a_used"], base["q_used"]
    AB, QB = broad_cal["a_used"], broad_cal["q_used"]
    years = np.round(np.arange(0.1, 6.0001, 0.05), 3)
    chain_c = mdr_curve(years, A0, Q0, UP)
    # Network: every epoch pinned by long pairs, so nothing random-walks, but each epoch keeps
    # the noise of one of today's 12-day pairs, sigma_e^2 = a + q (the per-pair ionosphere-screen
    # error is independent per pair and does not shrink in long pairs). Band: half (redundancy
    # helps) to double (long pairs decorrelate, residual ionosphere) that variance. rate_sigma
    # takes 2 sigma_e^2 as its 'a' (white per-epoch noise relative to epoch 0).
    s2 = A0 + Q0
    net_lo, net_mid, net_hi = (mdr_curve(years, 2 * f * s2, 0.0, UP) for f in (0.5, 1.0, 2.0))
    broad_lo, broad_c, broad_hi = (mdr_curve(years, 2 * f * (AB + QB), 0.0, UP) for f in (0.5, 1.0, 2.0))
    current = []
    for seg, label in (("summer", "Jun-Oct 2026 chain"), ("winter", "Nov-Dec 2025 chain")):
        sp = [p for p in pairs if p["segment"] == seg]
        if not sp:
            continue
        t = np.cumsum([p["dt_days"] for p in sp]) / 365.25
        ca = cal.get(f"{seg}_deramped_5km", base)
        current.append({"segment": seg, "label": label, "years": float(t[-1]), "pairs": len(sp),
                        "mdr": 2 * rate_sigma(t, ca["a_used"], ca["q_used"], seasonal=False) / UP,
                        "mdr_using_summer_calibration": 2 * rate_sigma(t, A0, Q0, seasonal=False) / UP})
    window_sd_5km = chains["summer"]["deramped"][-1]["sd_5km"]
    window_days = chains["summer"]["deramped"][-1]["days"]
    exp_window = [SAQ_BAND[0] * UP * window_days / 365.25, SAQ_BAND[1] * UP * window_days / 365.25]

    # noise-floor map: per-pixel std over pairs of 1 km moving averages of deramped desert LOS
    stack = []
    for p in pairs:
        num = ndi.uniform_filter(np.where(p["m"], p["dq"], 0.0), BLOCK["1km"], mode="constant")
        den = ndi.uniform_filter(p["m"].astype("float64"), BLOCK["1km"], mode="constant")
        stack.append(np.where((den >= 0.3) & p["m"], num / np.maximum(den, 1e-9), np.nan))
    stack = np.array(stack)
    nval = np.isfinite(stack).sum(0)
    with np.errstate(invalid="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN columns under fields
        nmap = np.where(nval >= max(len(pairs) - 4, 3), np.nanstd(stack, axis=0), np.nan)
    show = np.isfinite(nmap) & L["desert"]
    map_stats = {"median_mm": float(np.nanmedian(nmap[show])), "p90_mm": float(np.nanpercentile(nmap[show], 90)),
                 "desert_share_of_box": float(show.mean())}

    # figures
    style()
    vmax = float(np.ceil(np.nanpercentile(nmap[show], 98)))
    fig_noise_map(nmap, show, L["irrigated"] | ~L["desert"], None if ref_info["distributed"] else ref_win, vmax)
    fig_detectability(years, chain_c, net_lo, net_mid, net_hi, broad_c,
                      [{"years": c["years"], "mdr": c["mdr"], "label": c["label"]} for c in current])
    fig_false_movement(rows_fm)
    if "summer" in cum:
        fig_cumulative(cum["summer"]["_a"], cum["summer"]["_i"], "Jun-Oct 2026")
    fig_chain(chains)

    # per-pair console summary (one line per pair)
    for p, fm in zip(pairs, rows_fm):
        v = p["var"][chosen[p["segment"]]["variant"]]
        print(f"  {p['ref']}_{p['sec']} {p['segment']:6s} dt={p['dt_days']:5.1f} d valid={p['valid'].mean():.2f} "
              f"raw 1km {p['var']['raw']['corrected']['sd_1km']:5.1f} -> iono {p['var']['iono']['corrected']['sd_1km']:4.1f} "
              f"-> deramp px/1km/5km {v['deramped']['sd_px']:.1f}/{v['deramped']['sd_1km']:.1f}/{v['deramped']['sd_5km']:.1f} mm; "
              f"fields active {fm['active']['median_mm']:+.1f} idle {fm['idle']['median_mm']:+.1f} mm"
              + (f"  FLAG {'; '.join(p['flags'])}" if p["flags"] else ""))

    # JSON
    ok_pairs = [p for p in pairs if not p["flags"]]
    metrics = {"raw_no_deramp_1km": ("raw", "corrected", "sd_1km"), "iono_no_deramp_1km": ("iono", "corrected", "sd_1km"),
               "corrected_no_deramp_px": ("chosen", "corrected", "sd_px"),
               "corrected_no_deramp_1km": ("chosen", "corrected", "sd_1km"),
               "corrected_no_deramp_5km": ("chosen", "corrected", "sd_5km"),
               "raw_deramped_px": ("raw", "deramped", "sd_px"), "raw_deramped_1km": ("raw", "deramped", "sd_1km"),
               "deramped_px": ("chosen", "deramped", "sd_px"), "deramped_1km": ("chosen", "deramped", "sd_1km"),
               "deramped_5km": ("chosen", "deramped", "sd_5km")}

    def summ(group, key, ver, field):
        vals = [p["var"][chosen[p["segment"]]["variant"] if key == "chosen" else key][ver][field] for p in group]
        vals = [v for v in vals if v is not None]
        return {"min": min(vals), "median": float(np.median(vals)), "max": max(vals), "n": len(vals)} if vals else None

    def summary(group):
        if not group:
            return None
        sf = {k: float(np.median([p["sf_deramped"][k] for p in group if p["sf_deramped"][k] is not None]))
              for k in group[0]["sf_deramped"]}
        return {**{name: summ(group, *spec) for name, spec in metrics.items()},
                "structure_function_deramped_median": sf,
                "decorrelation_theory_px_median": float(np.median([p["theory_px_mm"] for p in group]))}

    pair_rows = []
    for p, fm in zip(pairs, rows_fm):
        pair_rows.append({
            "ref": iso(p["ref"]), "sec": iso(p["sec"]), "dt_days": p["dt_days"], "segment": p["segment"],
            "crid": p["crid"], "pge": p["pge"], "product_version": p.get("productVersion"),
            "spec_version": p.get("productSpecificationVersion"), "software_version": p.get("software_version"),
            "granule": p["granule"], "wavelength_m": p["wavelength_m"], "mm_per_rad": p["mm_per_rad"],
            "bperp_m": p["perpendicular_baseline_m_bottom_top"][0],
            "valid_frac": float(p["valid"].mean()), "unreliable_component_frac": p["cc0_frac"],
            "mask_invalid_frac": p["mask_bad_frac"], "iono_interpolated_frac": p["iono_interp_frac"],
            "desert_coherence_median": float(np.median(p["coh"][p["m"]])),
            "desert_coherence_median_all_desert_cells": float(np.median(p["coh"][L["desert"]])),
            "desert_valid_share": float(p["m"].sum() / max(L["desert"].sum(), 1)),
            "rain_mm_power": rain.get(p["ref"]),
            "raw_phase_spread_rad_p2_p98": p["raw_spread_rad"], "iono_screen_spread_rad_p2_p98": p["iono_spread_rad"],
            "iono_uncertainty_median_mm": p["iono_unc_mm"], "correction_used": chosen[p["segment"]]["variant"],
            "noise_mm": {name: p["var"][name] for name in variants},
            "structure_function_mm": {"corrected": p["sf_corrected"], "deramped": p["sf_deramped"]},
            "decorrelation_theory_px_mm": p["theory_px_mm"],
            "false_movement_mm": {"active": fm["active"], "idle": fm["idle"]},
            "flags": p["flags"]})

    cs = {s: {k: v for k, v in cum[s].items() if not k.startswith("_")} for s in cum}
    sm = chains["summer"]["deramped"]
    n_sub = sum(p["var"]["iono_tropo"]["corrected"]["sd_1km"] < p["var"]["iono_plus_tropo"]["corrected"]["sd_1km"] for p in pairs)
    sign_text = ("ISCE3 (the NISAR processor) Crossmul forms reference x conj(secondary) and flattens with exp(-i 4 pi dR / lambda), "
                 "so positive unwrapped phase = range increase (away from the satellite). The product spec D-102272 Rev E "
                 "does not state the sign. Empirical cross-check: ")
    if sign:
        sign_text += (f"the hydrostatic troposphere cube follows the NASA POWER surface-pressure change with slope "
                      f"{sign['slope_cube_vs_predicted']:+.2f} (r = {sign['correlation']:.2f}, {len(pairs)} pairs) for the "
                      f"'positive = more delay at the secondary date' convention, and subtracting the troposphere cube "
                      f"lowers the desert variance more than adding it in {n_sub} of {len(pairs)} pairs.")
    else:
        sign_text += "not run (no POWER pressure file)."

    def when(curve, thr):
        y = first_below(years, curve, thr)
        return "more than 6 years" if y is None else f"about {y:.1f} years"

    def span(lo_curve, hi_curve, thr):
        a, b = first_below(years, lo_curve, thr), first_below(years, hi_curve, thr)
        if a is None:
            return "more than 6 years"
        if b is None:
            return f"{a:.1f} to more than 6 years"
        return f"about {a:.1f} years" if a == b else f"about {a:.1f}-{b:.1f} years"

    wet = max(pairs, key=lambda p: rain.get(p["ref"]) or 0.0)
    low = [p for p in pairs if np.median(p["coh"][L["desert"]]) < 0.3]
    rain_note = (f"Rain: NASA POWER gives {rain.get(wet['ref'], 0):.0f} mm over the box in the {iso(wet['ref'])} -> "
                 f"{iso(wet['sec'])} pair (mostly 15-18 Dec 2025). Pairs with desert coherence < 0.3 ("
                 + ", ".join(f"{iso(p['ref'])}: {np.median(p['coh'][L['desert']]):.2f}, "
                             f"{p['m'].sum() / L['desert'].sum():.0%} of desert valid" for p in low)
                 + ") are decorrelated by that rain, which also gives idle fields a moisture offset.")
    prov = [p for p in pairs if p["segment"] == "summer"]
    iono_note = ("Ionosphere: the screen leaves long-wavelength residuals in the flagged pairs ("
                 + ", ".join(f"{iso(p['ref'])}: {p['var']['iono']['corrected']['sd_1km']:.0f} mm at 1 km without deramp"
                             for p in pairs if p["flags"])
                 + f"); the PROVISIONAL mask flags the screen as interpolated over "
                 f"{np.median([p['iono_interp_frac'] for p in prov]):.0%} of the box (bit 24); the screen-uncertainty layer is "
                 f"not a usable error estimate (median {np.median([p['iono_unc_mm'] for p in pairs if p['segment'] == 'winter']):.0f} mm "
                 f"in BETA, {np.median([p['iono_unc_mm'] for p in prov]):.0f} mm in PROVISIONAL granules, against 2-5 mm observed residuals).")
    helped = [p for p in pairs if p["var"]["iono_tropo"]["corrected"]["sd_1km"] < p["var"]["iono"]["corrected"]["sd_1km"]]
    tropo_note = ("Troposphere: the cube lowers the 1 km desert noise in " + ", ".join(iso(p["ref"]) for p in helped)
                  + f" and raises it in the other {len(pairs) - len(helped)} pairs; the choice is made per segment (used: "
                  + "; ".join(f"{seg} {chosen[seg]['variant']}" for seg in chosen)
                  + "), and per-pair numbers for every variant are in pairs[].noise_mm.")
    ref_note = (("The design reference (>= 25 km2, >= 5 km from irrigated land, coherence >= 0.5 in every pair) is met."
                 if ref_info["design_target_met"] else
                 f"The design reference (>= 25 km2, >= 5 km from irrigated land, coherence >= 0.5 in every pair) does not exist "
                 f"in this farm-dense box: only {ref_info['far_desert_km2_at_5km']:.0f} km2 of desert lies >= 5 km away, with "
                 f"median mean coherence {ref_info['far_desert_mean_coherence_at_5km']:.2f} (sand). Used: ladder rung "
                 f"{ref_info['ladder_rung']} ({'distributed' if ref_info['distributed'] else '10 km window'}, "
                 f"{ref_info['km2']:.0f} km2, >= {ref_info['min_distance_from_irrigated_m']:.0f} m from irrigated land).")
                + " Spreads, deramped residuals, chain spreads and field offsets do not depend on the reference.")
    act_s, idle_s = cs["summer"]["active_mm"]["median"], cs["summer"]["idle_mm"]["median"]
    detectable_now = current[0]["mdr"] <= SAQ_BAND[0]
    conclusion = (
        f"{'Not detectable yet' if not detectable_now else 'Detectable'}. Over the {window_days:.0f}-day Jun-Oct 2026 chain "
        f"the desert noise of 5 km averages is {window_sd_5km:.1f} mm after the quadratic deramp "
        f"({chains['summer']['corrected'][-1]['sd_5km']:.1f} mm without it), while Saq-belt subsidence of "
        f"{SAQ_BAND[0]:g}-{SAQ_BAND[1]:g} mm/yr would move the ground only {exp_window[0]:.1f}-{exp_window[1]:.1f} mm along the "
        f"line of sight in that window; the smallest rate the current record could detect is about {current[0]['mdr']:.0f} mm/yr "
        f"(vertical, 2 sigma). With 12-day pairs chained, 12 mm/yr becomes detectable after {when(chain_c, SAQ_BAND[1])} and "
        f"5 mm/yr after {when(chain_c, SAQ_BAND[0])} of continuous data. Processed as a redundant network with long pairs, "
        f"5 mm/yr needs {span(net_lo, net_hi, SAQ_BAND[0])}, 4 mm/yr {span(net_lo, net_hi, WEAK_BAND[1])} and 2 mm/yr "
        f"{span(net_lo, net_hi, WEAK_BAND[0])} (a year is the shortest record that separates the annual cycle). "
        f"The deramp hides bowls wider than ~20 km. Irrigated fields sum to a median {act_s:+.0f} mm of apparent "
        f"line-of-sight movement over the same chain (idle fields {idle_s:+.0f} mm): water in the soil, not ground motion, "
        f"so short-pair chains cannot monitor subsidence under farms.")

    out = {
        "generated": date.today().isoformat(),
        "title": "NISAR InSAR ground-movement pilot, Qassim",
        "conclusion": conclusion,
        "track_frame": {"track": 42, "frame": 15, "direction": "ascending", "look": "left"},
        "box": {"bbox_lonlat": [43.2, 26.1, 43.85, 26.55], "grid_epsg": 32638, "posting_m": PX_M,
                "shape": list(shape), "transform": list(tf)[:6], "regions_used": L["regions"],
                "land_data_coverage": L["coverage"]},
        "phase_to_los": {
            "formula": "d_LOS_mm = -(wavelength / (4 pi)) * phase * 1000, positive = toward the satellite",
            "wavelength_m": pairs[0]["wavelength_m"], "center_frequency_hz": pairs[0]["center_frequency_hz"],
            "mm_per_rad": pairs[0]["mm_per_rad"],
            "sign_basis": sign_text,
            "los_up_median": UP, "los_up_p5_p95": [float(np.percentile(up, 5)), float(np.percentile(up, 95))],
            "incidence_deg_median": float(np.median(inc)),
            "los_east_median": float(np.median(lx)), "los_north_median": float(np.median(ly)),
            "vertical_equivalent": "LOS / up-component (assumes vertical motion; one ascending geometry cannot separate horizontal)"},
        "masks": {"coherence_min": COH_MIN, "connected_components_excluded": [0, 65535],
                  "gunw_mask": "fill 255, water flag, invalid subswath digit or any anomaly bit 8-23 excluded; bit 24 reported",
                  "irrigated": f"mapped fields or Sentinel-2 max NDVI > {NDVI_MASK}, dilated {FIELD_BUFFER_PX} px ({FIELD_BUFFER_PX * PX_M:.0f} m)",
                  "desert": f"WorldCover {list(DESERT_WC)} and >= {DESERT_GAP_M:.0f} m from irrigated land",
                  "irrigated_share_of_box": float(L["irrigated"].mean()),
                  "desert_share_of_box": float(L["desert"].mean())},
        "reference_patch": {**ref_info, "ladder": [list(r) for r in REF_LADDER]},
        "corrections": {**{seg: {"variant_used": chosen[seg]["variant"], "median_var_1km_mm2_by_variant": chosen[seg]["median_var_1km_mm2"],
                                 "rule": "lowest median 1 km desert variance among ionosphere +/- troposphere +/- tides"}
                           for seg in chosen},
                        "troposphere_sign_check": {
                            "pairs_where_subtracting_beats_adding": int(sum(
                                p["var"]["iono_tropo"]["corrected"]["sd_1km"] < p["var"]["iono_plus_tropo"]["corrected"]["sd_1km"]
                                for p in pairs)),
                            "pairs": len(pairs),
                            "meaning": "the troposphere cube is in the same phase convention as unwrappedPhase if subtracting wins"},
                        "hydrostatic_pressure_sign_check": sign},
        "pairs": pair_rows,
        "noise_summary_mm": {
            "pairs_flagged": {f"{iso(p['ref'])}_{iso(p['sec'])}": p["flags"] for p in pairs if p["flags"]},
            "flag_rule": "deramped desert pixel sd > 6.8 mm or corrected (no deramp) 1 km sd > 6 mm (plausibility ranges of the v2 critique)",
            "all_pairs": summary(pairs), "unflagged_pairs": summary(ok_pairs),
            "winter": summary([p for p in pairs if p["segment"] == "winter"]),
            "summer": summary([p for p in pairs if p["segment"] == "summer"]),
            "noise_map_12day_1km": map_stats},
        "false_movement": {
            "definition": ("per field: median over core 80 m cells of deramped LOS minus the mean of desert pixels within 2 km; "
                           "active/idle from Sentinel-2 in the same season window; negative = apparent motion away from the satellite"),
            "per_pair": rows_fm, "cumulative": cs,
            "fields_with_values": int(len(set().union(*[set(per_field[p['ref']].index) for p in pairs])))},
        "chain": chains,
        "detectability": {
            "model": "var(k) = a + k q (k = pairs chained); a telescopes (per-epoch), q random-walks (non-closing)",
            "calibration": cal, "primary": "summer_deramped_5km",
            "los_up_used": UP, "record_sampling_days": REC_DT_DAYS,
            "years": years.tolist(),
            "mdr_vertical_mm_yr_2sigma": {"chain_12day": chain_c.tolist(), "network_low": net_lo.tolist(),
                                          "network_high": net_hi.tolist(),
                                          "network_mid": net_mid.tolist(),
                                          "network_no_deramp_low": broad_lo.tolist(),
                                          "network_no_deramp_high": broad_hi.tolist(),
                                          "network_no_deramp_mid": broad_c.tolist()},
            "network_noise": ("white per-epoch noise with variance a + q (one of today's 12-day pairs per epoch, no "
                              "accumulation; mid), from half (low) to double (high) that variance"),
            "seasonal_terms": "annual sine and cosine co-estimated for records >= 1 yr; shorter records linear only (optimistic, dotted)",
            "current_record": current,
            "first_year_below": {
                f"{name}_{thr:g}mm": first_below(years, cur, thr)
                for name, cur in (("chain", chain_c), ("network_low", net_lo), ("network_mid", net_mid),
                                  ("network_high", net_hi), ("network_no_deramp", broad_c))
                for thr in (12.0, 5.0, 4.0, 2.0)},
            "expected": {"saq_band_vertical_mm_yr": list(SAQ_BAND), "weak_band_vertical_mm_yr": list(WEAK_BAND),
                         "saq_band_los_mm_yr": [SAQ_BAND[0] * UP, SAQ_BAND[1] * UP],
                         "summer_window_days": window_days, "summer_window_signal_los_mm": exp_window,
                         "summer_window_noise_5km_deramped_mm": window_sd_5km,
                         "summer_window_noise_5km_corrected_mm": chains["summer"]["corrected"][-1]["sd_5km"],
                         "summer_window_noise_1km_deramped_mm": sm[-1]["sd_1km"],
                         "sources": ["Othman & Abotalib 2019, Environ Earth Sci 78 (ENVISAT SBAS, 5-12 mm/yr)",
                                     "Othman et al. 2018, Surv Geophys (4-15 mm/yr)"]}},
        "figures": {
            "noise_floor_map": {"file": "noise_floor_map.png", "alt": (
                f"Map of the Qassim box: 12-day line-of-sight noise of 1 km averages over desert, median "
                f"{map_stats['median_mm']:.1f} mm; farms, green land and towns are greyed out.")},
            "detectability": {"file": "detectability.png", "alt": (
                f"Smallest detectable subsidence rate against record length: the current record detects only about "
                f"{current[0]['mdr']:.0f} mm/yr; 12-day chains reach 12 mm/yr after {when(chain_c, SAQ_BAND[1])}, a long-pair "
                f"network reaches 5 mm/yr after {when(net_lo, SAQ_BAND[0])} to {when(net_hi, SAQ_BAND[0])}.")},
            "false_movement": {"file": "false_movement.png", "alt": (
                "Bar chart per 12-day pair: irrigated fields show a few millimetres of apparent movement relative to the "
                "desert, idle fields much less.")},
            "false_movement_cumulative": {"file": "false_movement_cumulative.png", "alt": (
                f"Histogram of summed apparent movement over the Jun-Oct 2026 chain: irrigated fields median "
                f"{cs['summer']['active_mm']['median']:+.0f} mm, idle fields {cs['summer']['idle_mm']['median']:+.0f} mm.")},
            "chain_noise": {"file": "chain_noise.png", "alt": (
                f"Spread of the summed desert line-of-sight values grows with each 12-day pair, to "
                f"{window_sd_5km:.1f} mm for 5 km averages after {window_days:.0f} days.")}},
        "method_notes": [
            "14 GUNW pairs (12-day nearest-neighbour; one 24-day pair, 2026-07-23 to 08-16) in two disjoint segments: "
            "winter 2025-11-01 to 12-31 (BETA, X05010) and summer 2026-06-17 to 10-15 (PROVISIONAL, P05023). GUNW never "
            "bridges 2025-12-31 to 2026-06-17, so the segments are analysed separately and never chained together.",
            "Phase corrected with the product's ionosphere screen (included in GUNW but not applied); troposphere (ECMWF HRES "
            "via RAiDER) and solid-earth-tide cubes interpolated at the DEM height and kept only where they lower the desert variance.",
            "Masks: connected component 0 or fill, coherence < 0.35, GUNW mask invalid/water/anomaly, irrigated land (fields + "
            "NDVI > 0.25) buffered 160 m. Noise statistics use desert land cover at least 400 m from irrigated land.",
            "All values are relative to a stable desert reference (target >= 25 km2, >= 5 km from irrigated land, coherence >= 0.5 "
            "in every pair; relaxed along a documented ladder when the target does not exist, see reference_patch).",
            "LOS mm = -(lambda/4pi) x phase with lambda = c / centerFrequency = 0.24393 m (19.41 mm/rad); vertical-equivalent = LOS / 0.72.",
            "The quadratic deramp removes wavelengths above about 20 km, so deramped numbers bound only local differential "
            "movement; broad regional aquifer bowls are invisible to it (see the no-deramp numbers).",
            "Minimum detectable rate = 2 sigma of a GLS rate with the noise model var(k) = a + k q calibrated on the summer chain."],
        "caveats": [
            "No subsidence is claimed. The pilot measures the noise floor and the irrigation phase bias only.",
            "No field-level displacement map is published: on irrigated fields the 12-day phase carries a systematic soil-moisture "
            "and vegetation bias that does not close in sequential sums, so chained field values are false movement, not ground motion.",
            "Sign convention taken from the ISCE3 processor (reference x conj(secondary)) and cross-checked with the hydrostatic "
            "troposphere cube against surface pressure; the NISAR product specification does not state it.",
            "Winter (BETA) and summer (PROVISIONAL) granules come from different processor releases and are kept separate.",
            "Only one (ascending) geometry: vertical-equivalent values assume no horizontal motion. Literature rates are treated as vertical.",
            "The detectability curves assume continuous 12-day acquisitions from now on and a noise model calibrated on a single "
            "120-day summer chain; seasonal moisture, residual ionosphere in long pairs and decorrelation in long pairs may raise the network curve.",
            "The network curves treat per-epoch noise as white, so they keep falling as T^-1.5; real records meet systematic floors "
            "(residual long-wavelength ionosphere, long-pair phase bias, reference-frame and seasonal non-sinusoidal signals) of "
            "order 1 mm/yr, so values below ~1-2 mm/yr are optimistic.",
            rain_note, iono_note,
            tropo_note, ref_note,
            "DEM heights are orthometric (EGM2008) used as ellipsoidal for the cube interpolation; the error is small against the 500 m cube spacing."],
    }
    tmp = OUT / ".insar.json.tmp"
    tmp.write_text(json.dumps(rnd(out, 3), indent=1, allow_nan=False))
    os.replace(tmp, OUT / "insar.json")
    print(f"InSAR pilot: {len(pairs)} pairs, ref patch {ref_km2:.0f} km2 at {ref_lon:.3f},{ref_lat:.3f}; "
          f"summer chain 5 km sd {window_sd_5km:.1f} mm vs signal {exp_window[0]:.1f}-{exp_window[1]:.1f} mm; "
          f"MDR now {current[0]['mdr']:.0f} mm/yr; a={A0:.2f} q={Q0:.2f} mm2 -> {OUT / 'insar.json'}")


if __name__ == "__main__":
    main()
