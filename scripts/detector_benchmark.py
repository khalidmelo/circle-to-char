"""Benchmark the pipeline's radar rule (D0) against simpler farmed/not-farmed detectors.

Every detector is scored against Sentinel-2 field-season flags (area-weighted and count-based; winter
reference = s2_winter_check, the composite over the radar's own winter dates; summer = s2_summer_active)
and against far-from-field desert patches (false-alarm rate, FAR):

  D0      pipeline rule: seasonal peak of desert-normalised HV > per region-season threshold
          (p50 + 3 * (p50 - p16) of the desert patches' seasonal peaks). Also D0-1dB and D0+1dB.
  D1      seasonal peak of raw HV (dB) > ONE national threshold per season, set so that D1's pooled desert
          FAR equals D0's pooled desert FAR (matched FAR; matched separately in each pool).
  D1r     (diagnostic) raw HV peak, per region-season threshold with the pipeline formula on raw patch peaks:
          separates "per-region threshold" from "per-date desert normalisation".
  D2      temporal coefficient of variation (std/mean, ddof=0) of linear HV over all of a field's dates
          (>= 4 dates) > 0.5, the NISAR crop-area rule (Whelen & Siqueira 2018; Rose et al. 2021). Also at
          the Youden-optimal CV between farmed fields and desert patches (oracle) and at the CV whose pooled
          desert FAR equals D0's year-level FAR (matched). CV is per year, so D2 is scored per field against
          'green in at least one observed season', next to D0/D1 'active in at least one season'.
  D2n     (diagnostic) the same CV on desert-normalised linear HV (field / same-date desert median), which
          removes date-to-date calibration steps from the CV.

Per-region and per-group tables apply national cuts (D1, D2 oracle/matched) fitted on the QC-passing pool
and, separately, on all region-seasons. Southwest = majority admin region of the field centres in the
project's southwest list (model/scenario_params.json); dune regions are listed in DUNE below.

Desert patches, desert medians, thresholds and field values are recomputed from the stored HV crops on the
pipeline's grid with its reprojection (copied from scripts/region_pipeline.py, not imported: importing it
pulls in the data-service clients) and checked against meta.json, hv_timeseries.csv and fields_radar.csv.
D0's FAR is in-sample (its threshold is fitted on the same patches), so it is also reported on a held-out
half of the patches (threshold fitted on a random half per region, fixed seed), and on a spatially blocked
split (1.6 km super-blocks) as a check on leakage between neighbouring patches.

Inputs (read-only): data/regions/R*/{meta.json, fields_labels.tif, fields_radar.csv, hv_timeseries.csv,
  hv_<date>.tif, worldcover.tif}, data/national/sau_adm1.geojson, model/scenario_params.json
Output: out/detector_benchmark.json, out/detector_benchmark.md
Usage:  .venv/bin/python scripts/detector_benchmark.py [--workers 6] [--cache DIR] [--regions R01 R02 ...]
"""
import argparse
import hashlib
import json
import os
import pickle
import time
import warnings
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import shapely
from pyproj import Transformer
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.warp import reproject
from scipy import ndimage as ndi
from shapely.geometry import shape

ROOT = Path(__file__).resolve().parents[1]
REG_DIR = ROOT / "data" / "regions"
OUT_JSON = ROOT / "out" / "detector_benchmark.json"
OUT_MD = ROOT / "out" / "detector_benchmark.md"
CODE_VERSION = "1"  # bump to invalidate --cache entries

# --- copied from scripts/region_pipeline.py
WINTER = ("2025-10-15", "2026-01-31")
SUMMER = ("2026-06-10", "2026-10-31")
RES = 40                     # metres
B = max(8, int(320 / RES))   # desert patch side in pixels (8 x 8 x 40 m = 10.24 ha)
DILATE = 10                  # far-from-field mask: fields grown by 10 pixels
MIN_DESERT_PX = 1000         # a date needs this many valid far-from-field pixels
# --- copied from model/national_supply.py (radar quality check)
BG_MAX_DB, THR_MAX_DB = -21.0, 6.0
# --- benchmark settings
SEASONS = ("winter", "summer")
REF = {"winter": "s2_winter_check", "summer": "s2_summer_active"}
CV_THR = 0.5
MIN_CV_DATES = 4
SEED = 20261115
SUPER = 5          # spatially blocked split: super-blocks of 5 x 5 patches (1.6 km)
TIE = 0.02         # per-region winner: kappa margin below which it is a tie
MIN_CLASS = 20     # per-region winner: both reference classes need this many fields
# Dune regions: dune texture visible in the far-from-field desert of the HV images (visual inspection of a
# summer date for all 60 regions): the sand belts east of Qassim (Nafud ath-Thuwayrat; R05 and R22 less
# certain), the Great Nafud edge north of Hail (R27) and the Rub al Khali sand edge at Najran (R59).
DUNE = ("R05", "R08", "R22", "R27", "R33", "R37", "R39", "R51", "R59", "R60")
WC_CLASSES = np.array([0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100])
WC_NAMES = {0: "no data", 10: "tree", 20: "shrub", 30: "grass", 40: "cropland", 50: "built-up", 60: "bare",
            70: "snow", 80: "water", 90: "wetland", 95: "mangrove", 100: "moss"}


def season_of(d):
    return "winter" if WINTER[0] <= d <= WINTER[1] else ("summer" if SUMMER[0] <= d <= SUMMER[1] else None)


def pipeline_grid(bbox, crs):
    """The region grid exactly as s2_fields.grid() builds it."""
    lon0, lat0, lon1, lat1 = bbox
    tr = Transformer.from_crs(4326, crs, always_xy=True)
    xs, ys = tr.transform([lon0, lon1, lon0, lon1], [lat0, lat0, lat1, lat1])
    x0, x1 = np.floor(min(xs) / RES) * RES, np.ceil(max(xs) / RES) * RES
    y0, y1 = np.floor(min(ys) / RES) * RES, np.ceil(max(ys) / RES) * RES
    return from_origin(x0, y1, RES, RES), int((x1 - x0) / RES), int((y1 - y0) / RES)


def tri(s):
    """True/False/blank column -> 1.0/0.0/NaN."""
    return s.map({True: 1.0, False: 0.0, "True": 1.0, "False": 0.0}).astype(float)


def nanmax_rows(x):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmax(x, axis=1)


def thr_rule(peaks):
    """Pipeline threshold: p50 + 3 * (p50 - p16) of the finite patch peaks (same dtype path as the pipeline)."""
    pk = peaks[np.isfinite(peaks)]
    if not len(pk):
        return np.nan
    p16, p50 = np.nanpercentile(pk, [16, 50])
    return float(p50 + 3 * (p50 - p16))


def region_inputs(rid):
    D = REG_DIR / rid
    meta = json.loads((D / "meta.json").read_text())
    names = ["meta.json", "fields_labels.tif", "fields_radar.csv", "hv_timeseries.csv", "worldcover.tif"]
    names += [f"hv_{d}.tif" for d in meta.get("dates", [])]
    return [D / n for n in names if (D / n).exists()]


def fingerprint(paths):
    h = hashlib.sha1(CODE_VERSION.encode())
    for p in paths:
        st = p.stat()
        h.update(f"{p.name}:{st.st_size}:{st.st_mtime_ns};".encode())
    return h.hexdigest()


# ------------------------------------------------------------------------------------------- extraction
def extract(rid):
    """Recompute per-date field means and desert-patch means for one region, as the pipeline does."""
    t0 = time.time()
    D = REG_DIR / rid
    meta = json.loads((D / "meta.json").read_text())
    res = {"id": rid, "status": meta.get("status"), "bbox": meta.get("bbox")}
    if meta.get("status") != "ok":
        return res
    transform, w, h = pipeline_grid(meta["bbox"], meta["crs"])
    with rasterio.open(D / "fields_labels.tif") as src:
        labels = src.read(1)
        grid_ok = bool(src.transform == transform and src.shape == (h, w)
                       and src.crs == CRS.from_user_input(meta["crs"]))
    wc = np.zeros((h, w), dtype="uint8")
    if (D / "worldcover.tif").exists():
        with rasterio.open(D / "worldcover.tif") as src:
            if src.shape == (h, w):
                wc = src.read(1)
    ids = np.unique(labels[labels > 0])

    # --- desert patches: same mask and blocks as the pipeline
    far = ~ndi.binary_dilation(labels > 0, iterations=DILATE)
    hb, wb = h // B, w // B
    okp = far[:hb * B, :wb * B].reshape(hb, B, wb, B).all(axis=(1, 3))
    prow, pcol = np.nonzero(okp)
    blocks = wc[:hb * B, :wb * B].reshape(hb, B, wb, B).transpose(0, 2, 1, 3)[okp].reshape(-1, B * B)
    counts = np.stack([(blocks == c).sum(axis=1) for c in WC_CLASSES], axis=1)
    wc_major = WC_CLASSES[np.argmax(counts, axis=1)] if len(blocks) else np.zeros(0, int)

    dates, bg, F, P = [], {}, [], []
    for d in meta.get("dates", []):
        p = D / f"hv_{d}.tif"
        if not p.exists():
            continue
        with rasterio.open(p) as src:
            a = np.full((h, w), np.nan, dtype="float32")
            reproject(rasterio.band(src, 1), a, src_nodata=src.nodata, dst_transform=transform,
                      dst_crs=meta["crs"], dst_nodata=np.nan, resampling=Resampling.average)
        a = np.where(a > 0, a, np.nan)
        valid = far & np.isfinite(a)
        if valid.sum() < MIN_DESERT_PX:
            continue
        bg[d] = float(np.nanmedian(10 * np.log10(a[valid])))
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            blk = np.nanmean(a[:hb * B, :wb * B].reshape(hb, B, wb, B), axis=(1, 3))
        P.append(blk[okp])                     # linear patch mean (float32, as in the pipeline)
        ok = np.isfinite(a) & (labels > 0)
        sm = ndi.sum(np.where(ok, a, 0), labels, ids)
        n = ndi.sum(ok, labels, ids)
        with np.errstate(all="ignore"):
            F.append(np.where(n > 0, sm / n, np.nan))  # linear field mean (float64)
        dates.append(d)
    F = np.array(F).T if F else np.zeros((len(ids), 0))
    P = np.array(P, dtype="float32").T if P else np.zeros((len(prow), 0), dtype="float32")

    # --- field attributes and Sentinel-2 reference
    fr = pd.read_csv(D / "fields_radar.csv", low_memory=False).set_index("id")
    fields = pd.DataFrame(index=pd.Index(ids, name="id"))
    fields["area_ha"] = fr.area_ha.reindex(ids).astype(float).values
    for c in ("lon", "lat", "tree_frac"):
        fields[c] = fr[c].reindex(ids).astype(float).values
    for c in ("s2_winter_check", "s2_summer_active", "s2_winter_active", "winter_active", "summer_active"):
        fields[c] = tri(fr[c]).reindex(ids).values if c in fr else np.nan

    # --- checks against what the pipeline stored
    ts = pd.read_csv(D / "hv_timeseries.csv")
    piv = ts.pivot_table(index="field_id", columns="date", values="hv_db", aggfunc="first").reindex(ids)
    diffs, nan_mis = [], 0
    with np.errstate(all="ignore"):
        Fdb = 10 * np.log10(F)
    for j, d in enumerate(dates):
        st = piv[d].values if d in piv else np.full(len(ids), np.nan)
        diffs.append(np.nanmax(np.abs(Fdb[:, j] - st)) if np.isfinite(Fdb[:, j] - st).any() else 0.0)
        nan_mis += int((np.isnan(Fdb[:, j]) != np.isnan(st)).sum())
    res.update({
        "crs": meta["crs"], "grid_ok": grid_ok, "dates": dates, "season": [season_of(d) for d in dates],
        "bg": bg, "meta_bg": meta.get("bg_median_db", {}), "meta_dates": meta.get("dates", []),
        "meta_thr": meta.get("validation", {}).get("thresholds_db", {}),
        "ids": ids, "F": F, "P": P, "prow": prow, "pcol": pcol, "wc": wc_major, "fields": fields,
        "fields_csv_match": bool(len(fr) == len(ids) and np.array_equal(np.sort(fr.index.values), ids)),
        "ts_max_abs_diff_db": float(max(diffs) if diffs else 0.0), "ts_nan_mismatch": nan_mis,
        "ts_dates_match": sorted(ts.date.unique().tolist()) == sorted(dates),
        "seconds": round(time.time() - t0, 2)})
    return res


def extract_cached(rid, cache):
    if not cache:
        return extract(rid)
    key = fingerprint(region_inputs(rid))
    p = Path(cache) / f"{rid}.pkl"
    if p.exists():
        with open(p, "rb") as f:
            obj = pickle.load(f)
        if obj.get("_key") == key:
            return obj
    obj = extract(rid)
    obj["_key"] = key
    Path(cache).mkdir(parents=True, exist_ok=True)
    with open(p, "wb") as f:
        pickle.dump(obj, f)
    return obj


# ----------------------------------------------------------------------------------------------- metrics
def confusion(pred, ref, wts):
    pred, ref = np.asarray(pred, bool), np.asarray(ref, bool)
    return np.array([wts[pred & ref].sum(), wts[pred & ~ref].sum(), wts[~pred & ref].sum(), wts[~pred & ~ref].sum()],
                    dtype=float)


def scores(c):
    tp, fp, fn, tn = (float(x) for x in c)
    tot = tp + fp + fn + tn
    if tot == 0:
        return None
    po = (tp + tn) / tot
    pe = ((tp + fp) * (tp + fn) + (fn + tn) * (fp + tn)) / tot ** 2
    r = lambda x: None if x is None else round(float(x), 4)  # noqa: E731
    return {"recall": r(tp / (tp + fn)) if tp + fn else None,
            "specificity": r(tn / (tn + fp)) if tn + fp else None,
            "precision": r(tp / (tp + fp)) if tp + fp else None,
            "kappa": r((po - pe) / (1 - pe)) if pe < 1 else None,
            "agreement": r(po), "f1": r(2 * tp / (2 * tp + fp + fn)) if 2 * tp + fp + fn else None,
            "tp": round(tp, 1), "fp": round(fp, 1), "fn": round(fn, 1), "tn": round(tn, 1)}


def score_block(pred, ref, area):
    """Area-weighted and count-based scores for boolean predictions against a boolean reference."""
    return {"area": scores(confusion(pred, ref, area)), "count": scores(confusion(pred, ref, np.ones(len(ref))))}


def match_threshold(values, k):
    """Threshold above which exactly k of the values lie (midpoint between the k-th and k+1-th largest)."""
    v = np.sort(np.asarray(values, float))[::-1]
    if not len(v):
        return np.nan
    if k <= 0:
        return float(v[0]) + 1e-3
    if k >= len(v):
        return float(v[-1]) - 1e-3
    return float((v[k - 1] + v[k]) / 2)


def youden(pos, neg):
    """CV threshold maximising TPR(pos > c) - FPR(neg > c)."""
    pos, neg = np.sort(pos), np.sort(neg)
    cand = np.unique(np.concatenate([pos, neg]))
    tpr = 1 - np.searchsorted(pos, cand, side="right") / len(pos)
    fpr = 1 - np.searchsorted(neg, cand, side="right") / len(neg)
    j = int(np.argmax(tpr - fpr))
    return float(cand[j]), float(tpr[j]), float(fpr[j])


def far(pred):
    pred = np.asarray(pred, bool)
    return None if not len(pred) else round(float(pred.mean()), 5)




# ------------------------------------------------------------------------------------------- unit tables
def build_tables(regions, sw_admin):
    """Long tables of field-season (FS), patch-season (PS), field-year (FY) and patch-year (PY) units."""
    fs, ps, fy, py, rinfo = [], [], [], [], {}
    polys = [(f["properties"]["shapeName"], shape(f["geometry"]))
             for f in json.loads((ROOT / "data" / "national" / "sau_adm1.geojson").read_text())["features"]]
    boxes = [(R["id"], R["bbox"]) for R in regions if R.get("bbox")]  # rank order
    for R in regions:
        rid = R["id"]
        if R.get("status") != "ok":
            rinfo[rid] = {"status": R.get("status")}
            continue
        fl = R["fields"]
        lon, lat, area_ha = fl.lon.values, fl.lat.values, fl.area_ha.values
        # majority admin region (by field area) of the field centres
        adm = np.full(len(fl), "", dtype=object)
        for name, g in polys:
            adm[shapely.contains_xy(g, lon, lat)] = name
        known = adm != ""
        a_ha = pd.Series(area_ha[known]).groupby(adm[known]).sum()
        admin = str(a_ha.idxmax()) if len(a_ha) else None
        # fields another region also mapped: owner = first region (rank order) whose box holds the centre,
        # the rule model/national_supply.py uses to deduplicate the national table
        owner = np.full(len(fl), "", dtype=object)
        for oid, (x0, y0, x1, y1) in boxes:
            inside = (owner == "") & (lon >= x0) & (lon <= x1) & (lat >= y0) & (lat <= y1)
            owner[inside] = oid
        dup = (owner != "") & (owner != rid)
        with np.errstate(all="ignore"):
            Fdb = 10 * np.log10(R["F"])
            Pdb = 10 * np.log10(R["P"])
        npch = len(R["prow"])
        rnum = int(rid[1:])
        half_a = np.zeros(npch, bool)
        half_a[np.random.default_rng([SEED, rnum]).permutation(npch)[: npch // 2]] = True
        sb = (R["prow"] // SUPER) * 1_000_000 + (R["pcol"] // SUPER)
        usb, inv = np.unique(sb, return_inverse=True)
        sb_a = (np.random.default_rng([SEED, rnum, 1]).random(len(usb)) < 0.5)[inv]
        info = {"admin": admin, "southwest": admin in sw_admin, "dune": rid in DUNE, "fields": int(len(fl)),
                "field_ha": round(float(area_ha.sum()), 1), "duplicate_fields": int(dup.sum()),
                "duplicate_ha": round(float(area_ha[dup].sum()), 1), "patches": npch,
                "wc_share": {WC_NAMES[int(c)]: round(float((R["wc"] == c).mean()), 4)
                             for c in np.unique(R["wc"])} if npch else {},
                "dates": R["dates"], "seasons": {}}
        obs = []
        ycols_f = {}
        ycols_p = {}
        for se in SEASONS:
            nanf, nanp = np.full(len(fl), np.nan), np.full(npch, np.nan)
            ycols_f.update({f"f_norm_{se}": nanf, f"f_raw_{se}": nanf, f"thr0_{se}": np.nan})
            ycols_p.update({f"p_norm_{se}": nanp, f"p_raw_{se}": nanp, f"thr0_{se}": np.nan})
            cols = [j for j, s in enumerate(R["season"]) if s == se]
            if not cols:
                continue
            bgs = [R["bg"][R["dates"][j]] for j in cols]
            f_norm = nanmax_rows(np.stack([Fdb[:, j] - b for j, b in zip(cols, bgs)], axis=1))
            f_raw = nanmax_rows(Fdb[:, cols])
            p_norm = nanmax_rows(np.stack([Pdb[:, j] - b for j, b in zip(cols, bgs)], axis=1))
            p_raw = nanmax_rows(Pdb[:, cols])
            thr0 = thr_rule(p_norm)
            if not np.isfinite(thr0):
                continue
            obs.append(se)
            thr_a, thr_b = thr_rule(np.where(half_a, p_norm, np.nan)), thr_rule(np.where(~half_a, p_norm, np.nan))
            thr_sa = thr_rule(np.where(sb_a, p_norm, np.nan))
            thr_r = thr_rule(p_raw)
            mbg = [v for d, v in R["meta_bg"].items() if season_of(d) == se]
            mthr = R["meta_thr"].get(se)
            qc = bool(mthr is not None and any(v <= BG_MAX_DB for v in mbg) and mthr <= THR_MAX_DB)
            ref = fl[REF[se]].values
            ok = np.isfinite(f_norm)
            fs.append(pd.DataFrame({
                "region": rid, "season": se, "idx": np.nonzero(ok)[0], "area": area_ha[ok], "ref": ref[ok],
                "f_norm": f_norm[ok], "f_raw": f_raw[ok], "thr0": thr0, "thr_a": thr_a, "thr_r": thr_r, "qc": qc,
                "stored": fl[f"{se}_active"].values[ok], "dup": dup[ok]}))
            okp = np.isfinite(p_norm)
            ps.append(pd.DataFrame({
                "region": rid, "season": se, "idx": np.nonzero(okp)[0], "p_norm": p_norm[okp],
                "p_raw": p_raw[okp], "half_a": half_a[okp], "sb_a": sb_a[okp], "wc": R["wc"][okp],
                "thr0": thr0, "thr_a": thr_a, "thr_b": thr_b, "thr_sa": thr_sa, "thr_r": thr_r, "qc": qc}))
            ycols_f.update({f"f_norm_{se}": f_norm, f"f_raw_{se}": f_raw, f"thr0_{se}": thr0})
            ycols_p.update({f"p_norm_{se}": p_norm, f"p_raw_{se}": p_raw, f"thr0_{se}": thr0})
            pn = np.nanpercentile(p_norm, [1, 16, 50, 84, 99])
            info["seasons"][se] = {
                "dates": [R["dates"][j] for j in cols], "bg_db": [round(b, 2) for b in bgs],
                "thr0_db": round(thr0, 3), "thr_meta_db": mthr,
                "thr_match": bool(mthr is not None and round(thr0, 2) == round(mthr, 2)),
                "thr_half_a_db": round(thr_a, 3), "thr_raw_region_db": round(thr_r, 3), "qc": qc,
                "patches_finite": int(okp.sum()),
                "patch_norm_pct": {k: round(float(v), 2) for k, v in zip(("p1", "p16", "p50", "p84", "p99"), pn)},
                "patch_raw_p50_db": round(float(np.nanmedian(p_raw)), 2),
                "s2_green_share": round(float(np.nanmean(ref)), 3) if np.isfinite(ref).any() else None}
        info["observed"] = obs
        info["qc_year"] = bool(obs) and all(info["seasons"][se]["qc"] for se in obs)
        rinfo[rid] = info
        if not obs:
            continue
        # --- year level: CV over all dates the pipeline used; reference = green in >= 1 observed season
        bgl = np.array([10 ** (R["bg"][d] / 10) for d in R["dates"]])
        Pl = R["P"].astype(float)
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            f_cv = np.nanstd(R["F"], axis=1) / np.nanmean(R["F"], axis=1)
            p_cv = np.nanstd(Pl, axis=1) / np.nanmean(Pl, axis=1)
            f_cvn = np.nanstd(R["F"] / bgl, axis=1) / np.nanmean(R["F"] / bgl, axis=1)
            p_cvn = np.nanstd(Pl / bgl, axis=1) / np.nanmean(Pl / bgl, axis=1)
        refs = np.stack([fl[REF[se]].values for se in obs], axis=1)
        ref_any = np.where((refs == 1).any(axis=1), 1.0, np.where((refs == 0).all(axis=1), 0.0, np.nan))
        both = len(obs) == 2
        rw, rs = fl[REF["winter"]].values, fl[REF["summer"]].values
        fy.append(pd.DataFrame({
            "region": rid, "idx": np.arange(len(fl)), "area": area_ha, "ref": ref_any,
            "green_both": both & (rw == 1) & (rs == 1),
            "green_one": both & (((rw == 1) & (rs == 0)) | ((rw == 0) & (rs == 1))),
            "green_w_only": both & (rw == 1) & (rs == 0), "green_s_only": both & (rw == 0) & (rs == 1),
            "tree": fl.tree_frac.values >= 0.3, "n": np.isfinite(R["F"]).sum(axis=1), "cv": f_cv, "cvn": f_cvn,
            "qc": info["qc_year"], "dup": dup, **ycols_f}))
        py.append(pd.DataFrame({
            "region": rid, "idx": np.arange(npch), "n": np.isfinite(Pl).sum(axis=1), "cv": p_cv, "cvn": p_cvn,
            "qc": info["qc_year"], "wc": R["wc"], **ycols_p}))
    def cat(parts):
        df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
        for c in ("region", "season"):  # categorical: fast masks over ~2 million patch rows
            if c in df:
                df[c] = pd.Categorical(df[c])
        return df
    return cat(fs), cat(ps), cat(fy), cat(py), rinfo


def by_season(season, T1, key):
    """Per-row value of a per-season national threshold (NaN where the pool has no such season)."""
    out = np.full(len(season), np.nan)
    for se, v in T1.items():
        out[(season == se).values] = v[key]
    return out


# --------------------------------------------------------------------------------------------- detectors
SEASON_DETS = ("D0", "D0-1dB", "D0+1dB", "D1", "D1r")
HALF_DETS = ("D0 (half-A thr)", "D1 (half-A thr)")
YEAR_DETS = ("D0 any season", "D1 any season", "D2 CV>0.5", "D2 oracle", "D2 matched FAR",
             "D2n CV>0.5", "D2n oracle", "D2n matched FAR")
VAR_DEP = {"D1", "D1 (half-A thr)", "D1 any season", "D2 oracle", "D2 matched FAR", "D2n oracle", "D2n matched FAR"}


def d0_any(df, kind):
    out = np.zeros(len(df), bool)
    for se in SEASONS:
        out |= df[f"{kind}_norm_{se}"].values > df[f"thr0_{se}"].values  # NaN (season unobserved) -> False
    return out


def fit_d1(PS, ps_m):
    """D1 national raw thresholds per season, count-matched to D0's pooled desert false alarms."""
    out = {}
    for se in SEASONS:
        m = ps_m & (PS.season.values == se)
        if not m.any():
            continue
        p = PS[m]
        ha = p.half_a.values
        k = int((p.p_norm.values > p.thr0.values).sum())
        ka = int((p.p_norm.values[ha] > p.thr_a.values[ha]).sum())
        out[se] = {"t1": match_threshold(p.p_raw.values, k), "k_d0": k, "n": int(len(p)),
                   "t1_half_a": match_threshold(p.p_raw.values[ha], ka), "k_d0_half_a": ka, "n_half_a": int(ha.sum())}
    return out


def year_valid(FY, PY, fy_m, py_m):
    return (fy_m & (FY.n.values >= MIN_CV_DATES) & FY.ref.notna().values), (py_m & (PY.n.values >= MIN_CV_DATES))


def fit_cuts(FY, PY, fy_m, py_m):
    """Oracle (Youden) and matched-FAR CV cuts for raw (D2) and desert-normalised (D2n) HV."""
    fv, pv = year_valid(FY, PY, fy_m, py_m)
    k = int(d0_any(PY, "p")[pv].sum())
    pos = FY.ref.values[fv] == 1
    out = {"matched_k": k, "fields": int(fv.sum()), "patches": int(pv.sum())}
    for col in ("cv", "cvn"):
        c, tpr, fpr = youden(FY[col].values[fv][pos], PY[col].values[pv])
        out[col] = {"oracle": c, "oracle_tpr_count": tpr, "oracle_fpr": fpr,
                    "matched": match_threshold(PY[col].values[pv], k)}
    return out


def make_calls(FS, PS, FY, PY, T1, cuts):
    def t1(s, key):
        return by_season(s, T1, key)

    def d1_any(df, kind):
        out = np.zeros(len(df), bool)
        for se, v in T1.items():
            out |= df[f"{kind}_raw_{se}"].values > v["t1"]
        return out
    fn, fr, th = FS.f_norm.values, FS.f_raw.values, FS.thr0.values
    pn, pr, tp = PS.p_norm.values, PS.p_raw.values, PS.thr0.values
    C = {"sf": {"D0": fn > th, "D0-1dB": fn > th - 1, "D0+1dB": fn > th + 1, "D1": fr > t1(FS.season, "t1"),
                "D1r": fr > FS.thr_r.values, "D0 (half-A thr)": fn > FS.thr_a.values,
                "D1 (half-A thr)": fr > t1(FS.season, "t1_half_a")},
         "sp": {"D0": pn > tp, "D0-1dB": pn > tp - 1, "D0+1dB": pn > tp + 1, "D1": pr > t1(PS.season, "t1"),
                "D1r": pr > PS.thr_r.values}}
    for part, df, kind in (("yf", FY, "f"), ("yp", PY, "p")):
        C[part] = {"D0 any season": d0_any(df, kind), "D1 any season": d1_any(df, kind)}
        for tag, col in (("D2", "cv"), ("D2n", "cvn")):
            v = df[col].values
            C[part].update({f"{tag} CV>0.5": v > CV_THR, f"{tag} oracle": v > cuts[col]["oracle"],
                            f"{tag} matched FAR": v > cuts[col]["matched"]})
    return C


def merge_calls(Cq, Ca):
    """One call table with variant-dependent detectors fitted on the QC pool and on all region-seasons."""
    M = {}
    for part in Cq:
        M[part] = {}
        for name, v in Cq[part].items():
            if name in VAR_DEP:
                M[part][f"{name} (qc fit)"] = v
                M[part][f"{name} (all fit)"] = Ca[part][name]
            else:
                M[part][name] = v
    return M


# --------------------------------------------------------------------------------------------- evaluation
def eval_season(FS, PS, C, fs_m, ps_m, dets, T1=None, full=False):
    out = {}
    for se in SEASONS + (("both",) if full else ()):
        sm = fs_m & FS.ref.notna().values & ((FS.season.values == se) if se != "both" else True)
        pm = ps_m & ((PS.season.values == se) if se != "both" else True)
        if not pm.any():
            continue
        ref, area = FS.ref.values[sm] == 1, FS.area.values[sm]
        res = {"fields": int(sm.sum()), "field_ha": round(float(area.sum())), "s2_green_fields": int(ref.sum()),
               "s2_not_green_fields": int((~ref).sum()),
               "s2_green_share_area": round(float(area[ref].sum() / area.sum()), 4) if area.sum() else None,
               "patches": int(pm.sum()), "detectors": {}}
        for name in dets:
            d = score_block(C["sf"][name][sm], ref, area) if sm.any() else {"area": None, "count": None}
            if name in C["sp"]:
                d["desert_far"] = far(C["sp"][name][pm])
                if full:
                    d["desert_far_bare_only"] = far(C["sp"][name][pm & (PS.wc.values == 60)])
            res["detectors"][name] = d
        if full and T1 is not None:
            p = PS[pm]
            t1a = by_season(p.season, T1, "t1_half_a")
            ha, sa = p.half_a.values, p.sb_a.values
            res["held_out_far"] = {
                "D0_random_half": far((p.p_norm.values > p.thr_a.values)[~ha]),
                "D0_random_half_swapped": far((p.p_norm.values > p.thr_b.values)[ha]),
                "D0_spatial_blocks": far((p.p_norm.values > p.thr_sa.values)[~sa]),
                "D1_random_half": far((p.p_raw.values > t1a)[~ha]), "patches_scored": int((~ha).sum())}
            dd = sm & ~FS.dup.values
            res["dedup_check_kappa_area"] = {n: (score_block(C["sf"][n][dd], FS.ref.values[dd] == 1, FS.area.values[dd])["area"] or {}).get("kappa")
                                             for n in ("D0", "D1")} if dd.any() else None
        out[se] = res
    return out


def eval_year(FY, PY, C, fy_m, py_m, dets, full=False):
    fv, pv = year_valid(FY, PY, fy_m, py_m)
    if not fv.any() or not pv.any():
        return None
    pos, area = FY.ref.values[fv] == 1, FY.area.values[fv]
    cvf, cvp = FY.cv.values[fv], PY.cv.values[pv]
    res = {"regions": int(FY.region[fv].nunique()), "fields": int(fv.sum()), "patches": int(pv.sum()),
           "s2_green_fields": int(pos.sum()), "detectors": {}}
    subsets = {"green_both": FY.green_both.values[fv]}
    if full:
        res["fields_excluded_lt4_dates"] = int((fy_m & (FY.n.values < MIN_CV_DATES) & FY.ref.notna().values).sum())
        gb = subsets["green_both"] & pos
        res["cv_median"] = {"farmed_fields": round(float(np.median(cvf[pos])), 3),
                            "green_both_fields": round(float(np.median(cvf[gb])), 3) if gb.any() else None,
                            "not_green_fields": round(float(np.median(cvf[~pos])), 3) if (~pos).any() else None,
                            "desert_patches": round(float(np.median(cvp)), 3),
                            "desert_patches_normalised": round(float(np.median(PY.cvn.values[pv])), 3),
                            "farmed_fields_normalised": round(float(np.median(FY.cvn.values[fv][pos])), 3)}
        subsets.update({"green_one": FY.green_one.values[fv], "green_winter_only": FY.green_w_only.values[fv],
                        "green_summer_only": FY.green_s_only.values[fv], "tree_cover_green": FY.tree.values[fv] & pos})
    for name in dets:
        cf, cp = C["yf"][name][fv], C["yp"][name][pv]
        d = score_block(cf, pos, area)
        d["desert_far"] = far(cp)
        if full:
            d["desert_far_bare_only"] = far(cp[PY.wc.values[pv] == 60])
        d["recall_subsets"] = {}
        for sname, sm in subsets.items():
            if sm.any():
                d["recall_subsets"][sname] = {"fields": int(sm.sum()), "ha": round(float(area[sm].sum())),
                                              "recall_area": round(float(area[sm & cf].sum() / area[sm].sum()), 4),
                                              "recall_count": round(float((sm & cf).sum() / sm.sum()), 4)}
        res["detectors"][name] = d
    return res


def kappa_of(block, name):
    d = (block or {}).get("detectors", {}).get(name)
    return ((d or {}).get("area") or {}).get("kappa")


def winner(kappas, minority):
    if minority < MIN_CLASS:
        return "n/a"
    k = {n: v for n, v in kappas.items() if v is not None}
    if not k:
        return "n/a"
    best = max(k, key=k.get)
    close = [n for n in k if n != best and k[best] - k[n] < TIE]
    return "tie " + "=".join([best] + close) if close else best


def context(rinfo):
    """Desert medians across regions, the summer-winter step and the within-season spread."""
    out = {}
    for pool in ("qc", "all"):
        for se in SEASONS:
            v = [float(np.mean(s["bg_db"])) for i in rinfo.values() for k, s in i.get("seasons", {}).items()
                 if k == se and (pool == "all" or s["qc"])]
            if v:
                out[f"desert_median_db_{pool}_{se}"] = dict(zip(("min", "p25", "median", "p75", "max"),
                                                               (round(float(x), 2) for x in np.percentile(v, [0, 25, 50, 75, 100]))),
                                                           n=len(v))
    step = [float(np.mean(i["seasons"]["summer"]["bg_db"]) - np.mean(i["seasons"]["winter"]["bg_db"]))
            for i in rinfo.values() if set(i.get("seasons", {})) == set(SEASONS) and i["qc_year"]]
    if step:
        out["summer_minus_winter_desert_db_qc"] = dict(zip(("min", "p25", "median", "p75", "max"),
                                                           (round(float(x), 2) for x in np.percentile(step, [0, 25, 50, 75, 100]))),
                                                       n=len(step))
    rng = [max(s["bg_db"]) - min(s["bg_db"]) for i in rinfo.values() for s in i.get("seasons", {}).values() if s["qc"]]
    if rng:
        out["within_season_desert_range_db_qc"] = {"median": round(float(np.median(rng)), 2), "max": round(float(max(rng)), 2)}
    # scenes whose desert median is more than 3 dB above the region's median over all its dates
    anom = []
    for rid, i in rinfo.items():
        dd = [(d, b) for s in i.get("seasons", {}).values() for d, b in zip(s["dates"], s["bg_db"])]
        if len(dd) >= 3:
            med = float(np.median([b for _, b in dd]))
            anom += [{"region": rid, "date": d, "desert_median_db": b, "region_median_db": round(med, 2)}
                     for d, b in dd if b - med > 3]
    out["anomalous_scenes"] = anom
    return out


# ----------------------------------------------------------------------------------------------- report
def pct(x, nd=1):
    return "–" if x is None else f"{100 * x:.{nd}f}"


def kap(x):
    return "–" if x is None else f"{x:.2f}".replace("-0.00", "0.00")


def write_md(J):
    P, ctx = J["pooled"], J["context"]
    L = ["# Detector benchmark: does the pipeline's radar rule beat simpler ones?\n",
         f"Built by `scripts/detector_benchmark.py` from stored data only ({J['run']['regions']} regions; runtime "
         f"{J['run']['runtime_s']:.0f} s with {J['run']['workers']} worker processes, {J['run']['extract_s']:.0f} s of it reading and "
         f"reprojecting {J['run']['hv_files']} HV rasters). Reference: Sentinel-2 field greenness per season (winter over the radar's "
         "own late-November to January dates, summer June-October). False alarms: share of the pipeline's own 10 ha far-from-field "
         "desert patches that a detector calls 'active'.\n",
         "## Key findings\n"]
    L += [f"- {s}" for s in J["verdict"]]
    L += ["", "## The detectors\n",
          "- **D0**: the pipeline rule: seasonal peak of HV minus the same-date desert median, above a threshold fitted per "
          "region and season on desert patches (p50 + 3 × (p50 − p16)). **D0±1dB**: same with the threshold moved 1 dB.",
          "- **D1**: seasonal peak of raw HV (no desert normalisation) above one national threshold per season, set so that "
          "D1's pooled desert false-alarm rate equals D0's (fitted separately for each pool). **D1r** (diagnostic): raw HV with "
          "the pipeline's formula per region and season, which separates 'regional threshold' from 'per-date normalisation'.",
          "- **D2**: temporal coefficient of variation (std/mean) of linear HV over all of a field's dates (≥ 4), crop if "
          "CV > 0.5 (NISAR crop-area rule); also at the best possible CV cut (oracle, Youden) and at the cut that matches D0's "
          "year-level false-alarm rate. **D2n** (diagnostic): the same on desert-normalised HV. CV is a per-year statistic, so "
          "D2 is scored per field against 'green in at least one season', next to D0/D1 'active in at least one season'.", ""]
    for pool, title in (("qc", "Region-seasons that pass the radar quality check"), ("all", "All region-seasons")):
        p = P[pool]
        t1 = p["d1_thresholds_db"]
        L.append(f"## {title} ({p['region_seasons']} region-seasons in {len(p['regions'])} regions)\n")
        L.append("D1 national thresholds: " + ", ".join(f"{se} {t1[se]['t1']:.2f} dB raw HV" for se in t1) + ".\n")
        L.append("| Season | Detector | Recall (area) | Precision (area) | Specificity (area) | κ (area) | Recall (count) | Precision (count) | κ (count) | Desert FAR % | Held-out FAR % |")
        L.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for se in SEASONS:
            s = p["season"].get(se)
            if not s:
                continue
            ho = s["held_out_far"]
            for name in SEASON_DETS:
                d = s["detectors"][name]
                a, c = d["area"], d["count"]
                hof = {"D0": ho["D0_random_half"], "D1": ho["D1_random_half"]}.get(name)
                L.append(f"| {se} | {name} | {pct(a['recall'])} | {pct(a['precision'])} | {pct(a['specificity'])} | {kap(a['kappa'])} | "
                         f"{pct(c['recall'])} | {pct(c['precision'])} | {kap(c['kappa'])} | {pct(d.get('desert_far'), 2)} | "
                         f"{pct(hof, 2) if hof is not None else ''} |")
        L.append("")
        for se in SEASONS:
            s = p["season"].get(se)
            if s:
                ho = s["held_out_far"]
                L.append(f"- {se.capitalize()}: {s['fields']:,} field-seasons ({s['field_ha']:,} ha; {pct(s['s2_green_share_area'])}% of the "
                         f"area green in Sentinel-2), {s['patches']:,} desert patches. Held-out D0 FAR (threshold fitted on the other "
                         f"half): random half {pct(ho['D0_random_half'], 2)}%, halves swapped {pct(ho['D0_random_half_swapped'], 2)}%, "
                         f"1.6 km spatial blocks {pct(ho['D0_spatial_blocks'], 2)}%; on WorldCover-bare patches only, in-sample "
                         f"{pct(s['detectors']['D0']['desert_far_bare_only'], 2)}%.")
        L.append("")
        y = p.get("year")
        if y:
            cm, cu = y["cv_median"], p["cv_cuts"]
            L.append(f"**Per year** ({y['fields']:,} fields with ≥ {MIN_CV_DATES} radar dates in {y['regions']} regions; "
                     f"{y['fields_excluded_lt4_dates']:,} fields with fewer dates left out). Median CV: farmed fields "
                     f"{cm['farmed_fields']}, of which green in both seasons {cm['green_both_fields']}; not-green fields "
                     f"{cm['not_green_fields']}; desert patches {cm['desert_patches']} (normalised: farmed "
                     f"{cm['farmed_fields_normalised']}, desert {cm['desert_patches_normalised']}). CV cuts: oracle "
                     f"{cu['cv']['oracle']:.3f}, matched {cu['cv']['matched']:.3f}; D2n oracle {cu['cvn']['oracle']:.3f}, "
                     f"matched {cu['cvn']['matched']:.3f}.\n")
            L.append("| Detector | Recall (area) | Precision (area) | Specificity (area) | κ (area) | Recall (count) | κ (count) | Recall: green both seasons | Recall: green one season | Desert FAR % |")
            L.append("|---|---|---|---|---|---|---|---|---|---|")
            for name in YEAR_DETS:
                d = y["detectors"][name]
                a, c, rs = d["area"], d["count"], d["recall_subsets"]
                L.append(f"| {name} | {pct(a['recall'])} | {pct(a['precision'])} | {pct(a['specificity'])} | {kap(a['kappa'])} | "
                         f"{pct(c['recall'])} | {kap(c['kappa'])} | {pct(rs.get('green_both', {}).get('recall_area'))} | "
                         f"{pct(rs.get('green_one', {}).get('recall_area'))} | {pct(d['desert_far'], 2)} |")
            L.append("")
    L.append("## Where each detector wins\n")
    L.append("Area-weighted κ against Sentinel-2, with the share of the region's desert patches each detector calls active in "
             "brackets (FAR %). D1 and D2m use the national cuts fitted on the QC-passing pool, applied to every region (the cuts "
             "fitted on all region-seasons are in the JSON); per region they are not matched to D0's false-alarm rate. Flags: "
             "SW = southwest (Jazan, Asir, Najran, Al Bahah; majority of field area), DUNE = dune texture in the desert background, "
             "SEA = at least 5% of desert patches are water. QC: ✓ pass, ✗ fail, · season not observed. Thr = D0 threshold. "
             f"Year FAR = desert patches called active in at least one season. Winner by κ (tie if within {TIE}; n/a when "
             f"Sentinel-2 has fewer than {MIN_CLASS} fields in one class); * = the winner flags more than 1 point more of this "
             "region's desert than D0 does.\n")
    L.append("| Region | Admin | Flags | QC W/S | Thr W/S dB | Fields | Winter κ D0/D1 (FAR %) | Summer κ D0/D1 (FAR %) | Year κ D0/D2/D2m (FAR % D0/D2m) | Winner W / S | Winner year |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for rid, r in J["regions"].items():
        if "seasons" not in r:
            L.append(f"| {rid} | | | | | | {r.get('status')} | | | | |")
            continue
        sx, sc = r["seasons"], r.get("scores", {})
        q = "/".join("·" if se not in sx else ("✓" if sx[se]["qc"] else "✗") for se in SEASONS)
        th = "/".join("·" if se not in sx else f"{sx[se]['thr0_db']:.1f}" for se in SEASONS)
        flags = " ".join(f for f, c in (("SW", r["southwest"]), ("DUNE", r["dune"]),
                                       ("SEA", r["wc_share"].get("water", 0) >= 0.05)) if c)
        kk, ww = [], []
        for se in SEASONS:
            b = sc.get("season", {}).get(se)
            if not b:
                kk.append("·")
                ww.append("·")
                continue
            fd = b["detectors"]
            kk.append(f"{kap(kappa_of(b, 'D0'))}/{kap(kappa_of(b, 'D1 (qc fit)'))} "
                      f"({pct(fd['D0']['desert_far'], 0)}/{pct(fd['D1 (qc fit)']['desert_far'], 0)})")
            ww.append(b["winner"])
        y = sc.get("year")
        if y:
            yd_ = y["detectors"]
            yk = ("/".join(kap(kappa_of(y, n)) for n in ("D0 any season", "D2 CV>0.5", "D2 matched FAR (qc fit)"))
                  + f" ({pct(yd_['D0 any season']['desert_far'], 0)}/{pct(yd_['D2 matched FAR (qc fit)']['desert_far'], 0)})")
        else:
            yk = "·"
        L.append(f"| {rid} | {(r['admin'] or '').replace(' Region', '')} | {flags} | {q} | {th} | {r['fields']:,} | {kk[0]} | {kk[1]} | "
                 f"{yk} | {ww[0]} / {ww[1]} | {y['winner'] if y else '·'} |")
    L.append("")
    L.append("**By group** (pooled within the group; area κ; D1 with the QC-fitted / all-fitted national thresholds; "
             "'QC pass' rows keep only region-seasons that pass the quality check):\n")
    L.append("| Group | Regions | Winter κ D0 / D1qc / D1all | Summer κ D0 / D1qc / D1all | Year κ D0 / D2 / D2m | Desert FAR % D0 / D1qc, winter; summer |")
    L.append("|---|---|---|---|---|---|")
    for name, g in J["groups"].items():
        s = g["season"]

        def fa(se, det):
            d = s.get(se, {}).get("detectors", {}).get(det)
            return pct(d.get("desert_far"), 1) if d else "–"
        sk = [" / ".join(kap(kappa_of(s.get(se), n)) for n in ("D0", "D1 (qc fit)", "D1 (all fit)")) for se in SEASONS]
        yk = " / ".join(kap(kappa_of(g.get("year"), n)) for n in ("D0 any season", "D2 CV>0.5", "D2 matched FAR (qc fit)"))
        L.append(f"| {name} | {len(g['regions'])} | {sk[0]} | {sk[1]} | {yk} | {fa('winter', 'D0')} / {fa('winter', 'D1 (qc fit)')}; "
                 f"{fa('summer', 'D0')} / {fa('summer', 'D1 (qc fit)')} |")
    L.append("")
    L.append("## Context\n")
    for k, lab in (("desert_median_db_qc_winter", "Desert median HV, QC-passing winters"),
                   ("desert_median_db_qc_summer", "Desert median HV, QC-passing summers"),
                   ("desert_median_db_all_winter", "Desert median HV, all winters"),
                   ("desert_median_db_all_summer", "Desert median HV, all summers"),
                   ("summer_minus_winter_desert_db_qc", "Summer minus winter desert median (regions passing QC in both seasons)")):
        if k in ctx:
            c = ctx[k]
            L.append(f"- {lab}: median {c['median']} dB (range {c['min']} to {c['max']}, IQR {c['p25']} to {c['p75']}; n = {c['n']}).")
    if "within_season_desert_range_db_qc" in ctx:
        c = ctx["within_season_desert_range_db_qc"]
        L.append(f"- Within a season, desert medians move by {c['median']} dB between dates (median; max {c['max']} dB) in QC-passing region-seasons.")
    L.append("")
    L.append("## Caveats\n")
    L += [f"- {c}" for c in J["caveats"]]
    v = J["verification"]
    L += ["", "## Reproduction check\n",
          f"Desert medians, thresholds and field values were recomputed from the stored HV rasters on the pipeline's grid with its "
          f"reprojection: grids match for {v['grid_matches_pipeline']}/{v['regions_ok']} regions, thresholds for "
          f"{v['thresholds_match']}/{v['region_seasons']} region-seasons (to 0.01 dB), desert medians to {v['max_bg_diff_db']:.1e} dB, "
          f"field HV to {v['max_field_db_diff']:.1e} dB, and D0 reproduces the stored field calls for "
          f"{pct(v['d0_calls_equal_stored'], 3)}% of {v['d0_calls_compared']:,} field-seasons. Deterministic: fixed seed {SEED} for the "
          "patch splits, no other randomness.", ""]
    OUT_MD.write_text("\n".join(L) + "\n")


def narrative(P, groups, rinfo, ctx):
    """Plain-language findings and caveats, computed from the numbers."""
    q, a = P["qc"], P["all"]

    def sd(p, se, det, part="area"):
        return (p["season"][se]["detectors"][det][part] or {})

    def yd(p, det, part="area"):
        return p["year"]["detectors"][det][part]
    V = []
    k0 = [sd(q, se, "D0")["kappa"] for se in SEASONS]
    k1 = [sd(q, se, "D1")["kappa"] for se in SEASONS]
    kr = [sd(q, se, "D1r")["kappa"] for se in SEASONS]
    r0 = [sd(q, se, "D0")["recall"] for se in SEASONS]
    r1 = [sd(q, se, "D1")["recall"] for se in SEASONS]
    p0 = [sd(q, se, "D0")["precision"] for se in SEASONS]
    p1 = [sd(q, se, "D1")["precision"] for se in SEASONS]
    f0 = [q["season"][se]["detectors"]["D0"]["desert_far"] for se in SEASONS]
    dk = [round(k0[i], 2) - round(k1[i], 2) for i in range(2)]
    V.append(f"At matched desert false-alarm rates D0 beats D1 in both seasons where the radar passes QC: area κ {kap(k0[0])} vs "
             f"{kap(k1[0])} in winter (+{dk[0]:.2f}) and {kap(k0[1])} vs {kap(k1[1])} in summer (+{dk[1]:.2f}). With "
             f"{pct(f0[0])}% / {pct(f0[1])}% of desert patches flagged by both, D0 finds {pct(r0[0])}% vs {pct(r1[0])}% (winter) and "
             f"{pct(r0[1])}% vs {pct(r1[1])}% (summer) of the area Sentinel-2 sees green, at the same precision "
             f"({pct(p0[0])}/{pct(p1[0])}% and {pct(p0[1])}/{pct(p1[1])}%). Count-based κ tells the same story "
             f"({kap(sd(q, 'winter', 'D0', 'count')['kappa'])}/{kap(sd(q, 'winter', 'D1', 'count')['kappa'])} winter, "
             f"{kap(sd(q, 'summer', 'D0', 'count')['kappa'])}/{kap(sd(q, 'summer', 'D1', 'count')['kappa'])} summer).")
    st = ctx.get("summer_minus_winter_desert_db_qc", {})
    ws = ctx.get("within_season_desert_range_db_qc", {})
    dq = [ctx.get(f"desert_median_db_qc_{se}", {}) for se in SEASONS]
    V.append(f"The gain comes from fitting the threshold per region, not from per-date normalisation: D1r (raw HV, per-region "
             f"threshold) scores κ {kap(kr[0])} / {kap(kr[1])}, close to D0's {kap(k0[0])} / {kap(k0[1])}. Desert medians span "
             f"{dq[0].get('max', 0) - dq[0].get('min', 0):.1f} dB across QC-passing regions in winter and "
             f"{dq[1].get('max', 0) - dq[1].get('min', 0):.1f} dB in summer, so one raw threshold must sit above the brightest "
             f"desert and misses fields on dark sand. The winter-to-summer step in desert medians (median +{st.get('median')} dB over "
             f"{st.get('n')} regions; the two seasons come from different NISAR processing versions) is absorbed by any per-season "
             f"threshold, D1's included; within a season desert medians move by a median {ws.get('median')} dB between dates.")
    a0 = [sd(a, se, "D0")["kappa"] for se in SEASONS]
    a1 = [sd(a, se, "D1")["kappa"] for se in SEASONS]
    t1a = a["d1_thresholds_db"]
    fa = a["d1_false_alarms"]
    top = {se: ", ".join(f"{x['region']} {pct(x['share'], 0)}%" for x in fa[se]["top"][:4]) for se in SEASONS if se in fa}
    an = ctx.get("anomalous_scenes", [])
    an_r = sorted({x["region"] for x in an}, key=lambda r: int(r[1:]))
    an_txt = (f"{len(an)} scenes in {', '.join(an_r)} whose desert median is "
              f"{min(x['desert_median_db'] - x['region_median_db'] for x in an):.0f}-"
              f"{max(x['desert_median_db'] - x['region_median_db'] for x in an):.0f} dB above the region's other dates") if an else ""
    V.append(f"Without the QC filter a national threshold breaks down: matched to D0's false-alarm rate over all region-seasons it "
             f"rises to {t1a['winter']['t1']:.1f} dB (winter) and {t1a['summer']['t1']:.1f} dB (summer), and D1 falls to κ "
             f"{kap(a1[0])} / {kap(a1[1])} (D0 {kap(a0[0])} / {kap(a0[1])}; recall D0 {pct(sd(a, 'winter', 'D0')['recall'])}% / "
             f"{pct(sd(a, 'summer', 'D0')['recall'])}% vs D1 {pct(sd(a, 'winter', 'D1')['recall'])}% / {pct(sd(a, 'summer', 'D1')['recall'])}%). "
             f"Its desert false alarms sit almost entirely in region-seasons that fail QC ({pct(fa['winter']['share_qc_fail'], 0)}% in "
             f"winter, {pct(fa['summer']['share_qc_fail'], 0)}% in summer; largest shares {top.get('winter')} in winter, "
             f"{top.get('summer')} in summer): bright Shield and limestone desert"
             + (f", and {an_txt}" if an_txt else "") + ". D0 absorbs both, because it normalises by each scene's own desert.")
    yq = q["year"]
    gb = lambda det: yq["detectors"][det]["recall_subsets"].get("green_both", {}).get("recall_area")  # noqa: E731
    V.append(f"D2 (CV) is weaker than D0 at every operating point. CV > 0.5 almost never fires on field-averaged HV (median CV "
             f"{yq['cv_median']['farmed_fields']} on farmed fields, {yq['cv_median']['desert_patches']} on desert): recall "
             f"{pct(yd(q, 'D2 CV>0.5')['recall'])}% (QC pool), {pct(gb('D2 CV>0.5'))}% on fields green in both seasons. At D0's "
             f"year-level false-alarm rate ({pct(yq['detectors']['D0 any season']['desert_far'])}%) D2 reaches κ "
             f"{kap(yd(q, 'D2 matched FAR')['kappa'])} vs D0 {kap(yd(q, 'D0 any season')['kappa'])} (recall "
             f"{pct(yd(q, 'D2 matched FAR')['recall'])}% vs {pct(yd(q, 'D0 any season')['recall'])}%; fields green in both seasons "
             f"{pct(gb('D2 matched FAR'))}% vs {pct(gb('D0 any season'))}%); even the oracle cut gives κ {kap(yd(q, 'D2 oracle')['kappa'])}. "
             f"Normalising by the desert median shrinks desert CV (median {yq['cv_median']['desert_patches']} → "
             f"{yq['cv_median']['desert_patches_normalised']}) but field CV too ({yq['cv_median']['farmed_fields']} → "
             f"{yq['cv_median']['farmed_fields_normalised']}): at matched FAR D2n scores κ {kap(yd(q, 'D2n matched FAR')['kappa'])}, and "
             f"its best cut κ {kap(yd(q, 'D2n oracle')['kappa'])} at a {pct(yq['detectors']['D2n oracle']['desert_far'])}% false-alarm rate. "
             f"With 4-7 dates and one canopy per season, the seasonal peak carries the signal and the year's spread does not.")
    # where D0 does not win (QC-fitted national cuts; per region these are not matched to D0's false-alarm rate)
    s_hi, s_lo, s_low_k, y_hi, y_lo = [], [], 0, [], []
    for rid, i in rinfo.items():
        sc = i.get("scores", {})
        tag = "".join(t for t, c in ((" SW", i.get("southwest")), (" DUNE", i.get("dune"))) if c)
        for se, b in sc.get("season", {}).items():
            w = b["winner"].rstrip("*")
            if w == "D1" or (w.startswith("tie") and "D0" not in w):
                lab = f"{rid} {se[0].upper()} ({'QC pass' if i['seasons'][se]['qc'] else 'QC fail'}{tag})"
                (s_hi if b["winner"].endswith("*") else s_lo).append(lab)
                s_low_k += max(kappa_of(b, "D0") or 0, kappa_of(b, "D1 (qc fit)") or 0) < 0.2
        y = sc.get("year") or {}
        w = y.get("winner", "").rstrip("*")
        if w in ("D1", "D2", "D2m") or (w.startswith("tie") and "D0" not in w):
            lab = f"{rid} {w}{(' (' + tag.strip() + ')') if tag else ''}"
            (y_hi if y["winner"].endswith("*") else y_lo).append(lab)
    ns = len(s_hi) + len(s_lo)
    V.append(f"Where D0 does not win: per region the national cuts are not matched to D0's false-alarm rate. With the QC-fitted "
             f"cut, D1 has the higher κ in {ns} region-seasons, but in {len(s_hi)} of them it also flags more of that region's desert "
             f"(it trades false alarms for recall where the national cut falls below D0's regional one), and in {s_low_k} of the {ns} "
             f"neither detector reaches κ 0.2. At an equal or lower regional false-alarm rate D1 wins only in "
             + (", ".join(s_lo) if s_lo else "no region-season")
             + ". Per year, D1 or D2m beats D0 at no extra desert false alarms in " + (", ".join(y_lo) if y_lo else "no region")
             + ("; with more false alarms in " + ", ".join(y_hi) if y_hi else "") + ".")
    g = groups

    def gk(grp, se, det):
        return kap(kappa_of(g[grp]["season"].get(se), det))

    def gf(grp, se, det="D0"):
        d = g[grp]["season"].get(se, {}).get("detectors", {}).get(det)
        return pct(d["desert_far"]) if d else "–"
    V.append(f"Dune regions (all pass QC except R59): D0 keeps its lead over D1 (winter κ {gk('Dune, QC pass', 'winter', 'D0')} vs "
             f"{gk('Dune, QC pass', 'winter', 'D1 (qc fit)')}, summer {gk('Dune, QC pass', 'summer', 'D0')} vs "
             f"{gk('Dune, QC pass', 'summer', 'D1 (qc fit)')}), but flags more desert than in other QC-passing regions "
             f"({gf('Dune, QC pass', 'winter')}% / {gf('Dune, QC pass', 'summer')}% vs {gf('Other, QC pass', 'winter')}% / "
             f"{gf('Other, QC pass', 'summer')}%), probably bright dune faces above a threshold set by the darker sand. Southwest: "
             f"no detector works. D0 reaches κ {gk('Southwest', 'winter', 'D0')} in winter and {gk('Southwest', 'summer', 'D0')} in "
             f"summer; the QC-fitted D1 calls {gf('Southwest', 'winter', 'D1 (qc fit)')}% / {gf('Southwest', 'summer', 'D1 (qc fit)')}% "
             f"of the bright rocky desert active (κ {gk('Southwest', 'winter', 'D1 (qc fit)')} / {gk('Southwest', 'summer', 'D1 (qc fit)')}), "
             f"and Sentinel-2's summer green there is largely rain-fed or natural vegetation.")
    h = [q["season"][se]["held_out_far"] for se in SEASONS]
    pp = [np.median([s["patch_norm_pct"]["p50"] - s["patch_norm_pct"]["p16"] for i in rinfo.values()
                     for k, s in i.get("seasons", {}).items() if k == se and s["qc"]]) for se in SEASONS]
    pu = [np.median([s["patch_norm_pct"]["p84"] - s["patch_norm_pct"]["p50"] for i in rinfo.values()
                     for k, s in i.get("seasons", {}).items() if k == se and s["qc"]]) for se in SEASONS]
    V.append(f"D0's own desert false-alarm rate is far above what '3 sigma' suggests: {pct(f0[0])}% (winter) and {pct(f0[1])}% (summer) "
             f"of far-from-field desert patches pass the threshold in the QC pool. This is not an artefact of fitting on the same "
             f"patches (held-out half {pct(h[0]['D0_random_half'])}% / {pct(h[1]['D0_random_half'])}%; 1.6 km spatial blocks "
             f"{pct(h[0]['D0_spatial_blocks'])}% / {pct(h[1]['D0_spatial_blocks'])}%) nor of towns or water (WorldCover-bare patches "
             f"{pct(q['season']['winter']['detectors']['D0']['desert_far_bare_only'])}% / {pct(q['season']['summer']['detectors']['D0']['desert_far_bare_only'])}%): "
             f"the desert patch peaks are right-skewed (median p50 − p16 = {pp[0]:.2f} / {pp[1]:.2f} dB, p84 − p50 = {pu[0]:.2f} / {pu[1]:.2f} dB), "
             f"so p50 + 3 × (p50 − p16) sits inside the bright tail. D0+1dB cuts the rate to "
             f"{pct(q['season']['winter']['detectors']['D0+1dB']['desert_far'])}% / {pct(q['season']['summer']['detectors']['D0+1dB']['desert_far'])}% "
             f"for {pct(r0[0] - sd(q, 'winter', 'D0+1dB')['recall'])} / {pct(r0[1] - sd(q, 'summer', 'D0+1dB')['recall'])} points of recall; "
             f"D0−1dB raises κ to {kap(sd(q, 'winter', 'D0-1dB')['kappa'])} / {kap(sd(q, 'summer', 'D0-1dB')['kappa'])} but doubles the rate.")
    # caveats
    nd = sum(i.get("duplicate_fields", 0) for i in rinfo.values())
    nf = sum(i.get("fields", 0) for i in rinfo.values())
    ded = q["season"]["summer"].get("dedup_check_kappa_area") or {}
    sea = [r for r, i in rinfo.items() if i.get("wc_share", {}).get("water", 0) >= 0.05]
    bw = q["season"]["winter"]["detectors"]["D0"]
    sw_pass, f_bg, f_thr = [], [], []
    for rid, i in rinfo.items():
        for se, s in i.get("seasons", {}).items():
            lab = f"{rid} {se[0].upper()}"
            if i.get("southwest"):
                if s["qc"]:
                    sw_pass.append(lab)
            elif not s["qc"]:
                if min(s["bg_db"]) > BG_MAX_DB:
                    f_bg.append(lab)
                if s["thr_meta_db"] is not None and s["thr_meta_db"] > THR_MAX_DB:
                    f_thr.append(lab)
    C = [
        "Sentinel-2 greenness (field median of the seasonal maximum NDVI > 0.40) is a reference, not ground truth: winter crops that "
        "green after the late-November to January radar dates, weedy fallow, rain-greened natural vegetation in the southwest and "
        "palms/orchards all blur it. Summer is lopsided (most mapped fields are green), so summer κ moves a lot with small "
        "changes in specificity.",
        f"Desert patches are the pipeline's own 320 m blocks at least 400 m from any mapped field. They are mostly bare "
        f"(WorldCover), but include rock outcrops, dunes, roads, some built-up land, unmapped small plots and, on the Jazan coast, "
        f"sea ({', '.join(sea) if sea else 'none'} have ≥ 5% water patches). D0's false-alarm rate on WorldCover-bare patches only is "
        f"{pct(bw['desert_far_bare_only'])}% vs {pct(bw['desert_far'])}% on all (QC winter).",
        "Patches are 10.24 ha; fields range from 3 ha to several hundred. A small field's mean is noisier than a patch mean, so the "
        "false-alarm rate for small fields is likely above the patch rate, and below it for large pivots.",
        "D1's thresholds are matched to D0's pooled rate in-sample by construction; on the held-out half the two rates stay within "
        f"{abs(h[0]['D0_random_half'] - h[0]['D1_random_half']) * 100:.2f} / {abs(h[1]['D0_random_half'] - h[1]['D1_random_half']) * 100:.2f} "
        "points (winter / summer). Pooled rates weight regions by their desert area, so per-region rates differ a lot (table above): "
        "a national raw threshold concentrates its false alarms in bright-desert regions and has almost none on dark sand.",
        "CV uses only 4-7 dates (3 between late November and January, 4 in June-October; summer-only regions have 4), far sparser than the "
        "12-day series the NISAR crop-area rule (CV > 0.5) was designed for, and is computed on field means (not pixels) with the "
        "population standard deviation (a sample std would raise CV by 8-15%, not enough to change the ranking). Between-season "
        "calibration steps inflate desert CV, which D2n removes.",
        "The QC rule is the project's (a date's desert median ≤ −21 dB and threshold ≤ 6 dB), applied to the values in meta.json. "
        f"Outside the southwest (where only {', '.join(sw_pass) or 'none'} pass{'es' if len(sw_pass) == 1 else ''}) it rejects "
        f"region-seasons whose desert is brighter than −21 dB on every date ({', '.join(f_bg) or 'none'}: Shield and limestone ground, "
        f"or anomalously bright scenes) or whose threshold exceeds 6 dB ({', '.join(f_thr) or 'none'}; in R12 a dark swath-edge "
        "strip inside the desert mask inflates it).",
        "Dune flags come from visual inspection of the HV images (dune texture in the desert background), R05 and R22 being the "
        "least certain; 'southwest' is the majority admin region of the field centres (the project's own list).",
        f"Fields mapped by two overlapping regions are scored in each region, as the pipeline validates per region: {nd:,} of "
        f"{nf:,} fields ({100 * nd / max(nf, 1):.1f}%) belong to another region under the national table's de-duplication rule. "
        f"Dropping them barely moves the result (QC summer area κ D0 {kap(ded.get('D0'))}, D1 {kap(ded.get('D1'))}).",
        "Per-region κ is unstable where Sentinel-2 is one-sided (e.g. southwest summers where nearly every mapped field is green); "
        "the winner is then marked n/a. Ties use a 0.02 κ margin.",
        "All numbers come from the stored region outputs at run time. Another session may re-run parts of the pipeline; the "
        "reproduction check (thresholds, desert medians, field values, D0 calls) is recomputed on every run and would show any "
        "region that changed mid-run."]
    return V, C


# ------------------------------------------------------------------------------------------------- main
def clean(o):
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=min(6, os.cpu_count() or 1))
    ap.add_argument("--cache", help="optional directory for per-region extraction caches (keyed on input files)")
    ap.add_argument("--regions", nargs="*")
    args = ap.parse_args()
    t0 = time.time()
    rids = args.regions or sorted((p.name for p in REG_DIR.glob("R[0-9]*") if (p / "meta.json").exists()),
                                  key=lambda r: int(r[1:]))
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        regions = list(ex.map(extract_cached, rids, [args.cache] * len(rids)))
    t_extract = time.time() - t0
    sw_admin = tuple(json.loads((ROOT / "model" / "scenario_params.json").read_text())["southwest_admin"]["values"])
    FS, PS, FY, PY, rinfo = build_tables(regions, sw_admin)

    # --- reproduction check against the stored pipeline outputs
    ok_regions = [R for R in regions if R.get("status") == "ok"]
    rs = [(rid, se, s) for rid, i in rinfo.items() for se, s in i.get("seasons", {}).items()]
    st = FS.stored.notna().values
    d0 = FS.f_norm.values > FS.thr0.values
    verification = {
        "regions_ok": len(ok_regions), "grid_matches_pipeline": int(sum(R["grid_ok"] for R in ok_regions)),
        "region_seasons": len(rs), "thresholds_match": int(sum(s["thr_match"] for _, _, s in rs)),
        "thresholds_mismatch": [f"{rid} {se}" for rid, se, s in rs if not s["thr_match"]],
        "max_bg_diff_db": float(max((abs(R["bg"][d] - R["meta_bg"][d]) for R in ok_regions for d in R["bg"]
                                     if d in R["meta_bg"]), default=0.0)),
        "bg_dates_match": int(sum(sorted(R["bg"]) == sorted(R["meta_bg"]) for R in ok_regions)),
        "max_field_db_diff": float(max(R["ts_max_abs_diff_db"] for R in ok_regions)),
        "field_nan_mismatch": int(sum(R["ts_nan_mismatch"] for R in ok_regions)),
        "timeseries_dates_match": int(sum(R["ts_dates_match"] for R in ok_regions)),
        "fields_csv_match": int(sum(R["fields_csv_match"] for R in ok_regions)),
        "d0_calls_equal_stored": round(float((d0[st] == (FS.stored.values[st] == 1)).mean()), 6),
        "d0_calls_compared": int(st.sum())}

    # --- pooled results: QC-passing region-seasons and all
    pooled, calls = {}, {}
    for pool in ("qc", "all"):
        allf = lambda df: np.ones(len(df), bool)  # noqa: E731
        fs_m, ps_m = (FS.qc.values, PS.qc.values) if pool == "qc" else (allf(FS), allf(PS))
        fy_m, py_m = (FY.qc.values, PY.qc.values) if pool == "qc" else (allf(FY), allf(PY))
        T1 = fit_d1(PS, ps_m)
        cuts = fit_cuts(FY, PY, fy_m, py_m)
        C = make_calls(FS, PS, FY, PY, T1, cuts)
        calls[pool] = C
        pooled[pool] = {
            "region_seasons": int(FS[fs_m][["region", "season"]].drop_duplicates().shape[0]),
            "regions": sorted(set(FS.region[fs_m]), key=lambda r: int(r[1:])),
            "d1_thresholds_db": {se: {k: (round(v, 3) if isinstance(v, float) else v) for k, v in d.items()} for se, d in T1.items()},
            "cv_cuts": {k: ({kk: round(vv, 4) for kk, vv in v.items()} if isinstance(v, dict) else v) for k, v in cuts.items()},
            "season": eval_season(FS, PS, C, fs_m, ps_m, SEASON_DETS + HALF_DETS, T1=T1, full=True),
            "year": eval_year(FY, PY, C, fy_m, py_m, YEAR_DETS, full=True)}
        # where D1's desert false alarms fall (pooled rates weight regions by desert area)
        fa = {}
        for se in T1:
            m = ps_m & (PS.season.values == se) & C["sp"]["D1"]
            if m.any():
                vc = pd.Series(PS.region.values[m]).astype(str).value_counts()
                vc = vc.reindex(sorted(vc.index, key=lambda r: (-vc[r], int(r[1:]))))
                fa[se] = {"false_alarms": int(m.sum()),
                          "share_qc_fail": round(float((~PS.qc.values[m]).mean()), 4),
                          "share_southwest": round(float(np.isin(PS.region.values[m].astype(str),
                                                                 [r for r, i in rinfo.items() if i.get("southwest")]).mean()), 4),
                          "top": [{"region": r, "share": round(float(c / m.sum()), 4)} for r, c in vc.head(8).items()]}
        pooled[pool]["d1_false_alarms"] = fa

    # --- per region and per group, national cuts from both pools
    M = merge_calls(calls["qc"], calls["all"])
    sdets = tuple(n for n in M["sf"] if not n.startswith(("D0 (half", "D1 (half")))
    ydets = tuple(M["yf"])

    def star(block, win, names, ref_name):
        """Mark a winner without D0 whose detectors all flag more than 1 point more of the region's desert than D0."""
        ws = win[4:].split("=") if win.startswith("tie ") else [win]
        if "D0" in ws or not all(w in names for w in ws):
            return win
        f_0 = block["detectors"][ref_name]["desert_far"]
        f_w = [block["detectors"][names[w]]["desert_far"] for w in ws]
        return win + "*" if f_0 is not None and all(f is not None and f > f_0 + 0.01 for f in f_w) else win
    for rid, info in rinfo.items():
        if "seasons" not in info:
            continue
        fs_m, ps_m = (FS.region == rid).values, (PS.region == rid).values
        fy_m, py_m = (FY.region == rid).values, (PY.region == rid).values
        S = eval_season(FS, PS, M, fs_m, ps_m, sdets)
        for se, b in S.items():
            w = winner({"D0": kappa_of(b, "D0"), "D1": kappa_of(b, "D1 (qc fit)")},
                       min(b["s2_green_fields"], b["s2_not_green_fields"]))
            b["winner"] = star(b, w, {"D1": "D1 (qc fit)"}, "D0")
        Y = eval_year(FY, PY, M, fy_m, py_m, ydets)
        if Y:
            w = winner({"D0": kappa_of(Y, "D0 any season"), "D1": kappa_of(Y, "D1 any season (qc fit)"),
                        "D2": kappa_of(Y, "D2 CV>0.5"), "D2m": kappa_of(Y, "D2 matched FAR (qc fit)")},
                       min(Y["s2_green_fields"], Y["fields"] - Y["s2_green_fields"]))
            Y["winner"] = star(Y, w, {"D1": "D1 any season (qc fit)", "D2": "D2 CV>0.5", "D2m": "D2 matched FAR (qc fit)"},
                               "D0 any season")
        info["scores"] = {"season": S, "year": Y}
    groups = {}
    sw_r = [r for r, i in rinfo.items() if i.get("southwest")]
    dn_r = [r for r, i in rinfo.items() if i.get("dune")]
    ot_r = [r for r, i in rinfo.items() if "seasons" in i and not i.get("southwest") and not i.get("dune")]
    for name, regs, qc_only in (("Southwest", sw_r, False), ("Dune", dn_r, False), ("Other", ot_r, False),
                                ("Dune, QC pass", dn_r, True), ("Other, QC pass", ot_r, True)):
        fs_m, ps_m = FS.region.isin(regs).values, PS.region.isin(regs).values
        fy_m, py_m = FY.region.isin(regs).values, PY.region.isin(regs).values
        if qc_only:
            fs_m, ps_m, fy_m, py_m = fs_m & FS.qc.values, ps_m & PS.qc.values, fy_m & FY.qc.values, py_m & PY.qc.values
        groups[name] = {"regions": sorted(set(FS.region[fs_m].astype(str)), key=lambda r: int(r[1:])),
                        "qc_only": qc_only, "season": eval_season(FS, PS, M, fs_m, ps_m, sdets),
                        "year": eval_year(FY, PY, M, fy_m, py_m, ydets)}

    ctx = context(rinfo)
    verdict, caveats = narrative(pooled, groups, rinfo, ctx)
    t_total = time.time() - t0
    J = {"run": {"finished": time.strftime("%Y-%m-%d %H:%M:%S %z"), "runtime_s": round(t_total, 1),
                 "extract_s": round(t_extract, 1), "analysis_s": round(t_total - t_extract, 1),
                 "workers": args.workers, "regions": len(rids), "cache_used": bool(args.cache),
                 "hv_files": int(sum(len(R.get("dates", [])) for R in ok_regions)),
                 "region_extract_s": {R["id"]: R.get("seconds") for R in regions},
                 "input_fingerprint": hashlib.sha1("".join(fingerprint(region_inputs(r)) for r in rids).encode()).hexdigest()},
         "config": {"res_m": RES, "patch_px": B, "patch_ha": B * B * (RES / 100) ** 2, "dilate_px": DILATE,
                    "min_desert_px": MIN_DESERT_PX, "winter_window": WINTER, "summer_window": SUMMER,
                    "qc_rule": f"season passes if a date's desert median <= {BG_MAX_DB} dB and the threshold <= {THR_MAX_DB} dB",
                    "reference": REF, "cv_threshold": CV_THR, "min_cv_dates": MIN_CV_DATES, "cv_std_ddof": 0,
                    "seed": SEED, "spatial_block_patches": SUPER, "tie_kappa": TIE, "winner_min_class_fields": MIN_CLASS,
                    "dune_regions": list(DUNE), "southwest_admin": list(sw_admin)},
         "verification": verification, "verdict": verdict, "context": ctx, "pooled": pooled, "groups": groups,
         "regions": rinfo, "caveats": caveats}
    J = clean(J)
    OUT_JSON.write_text(json.dumps(J, indent=1, allow_nan=False))
    write_md(J)
    print(f"wrote {OUT_JSON.relative_to(ROOT)} and {OUT_MD.relative_to(ROOT)} in {t_total:.0f}s "
          f"(extraction {t_extract:.0f}s, {args.workers} workers)")


if __name__ == "__main__":
    main()
