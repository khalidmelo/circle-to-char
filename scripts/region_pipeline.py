"""Run the whole field + radar chain for one region box (national scale-out).

For region R (from data/national/regions.json):
  1. Sentinel-2: fields from seasonal maximum NDVI (offset-corrected; winter Nov-Mar, summer Jun-Oct) on a
     40 m UTM grid, plus a check composite over the radar's own winter dates. Optional WorldCover filter
     (CTC_LC_FILTER): drop fields whose majority class is natural shrubland or grassland.
  2. NISAR GCOV HV for up to 3 winter + 4 summer dates on the best-covering track/frame.
  3. Per-field HV peak above each scene's desert median vs same-season desert patches; desert-patch tail threshold
     = median + 3 x (median - 16th percentile) of patch peaks (about 13-14% of desert patches exceed it).
  4. Validation against Sentinel-2 over matched windows.
  5. Palm groves: fields with >= 30% ESA WorldCover tree cover (class 10), active in every season observed.

Output: data/regions/<R>/fields_radar.csv, meta.json, fields_labels.tif, worldcover.tif, ndvi_*/nobs_*.tif, hv_*.tif
Usage:  .venv/bin/python scripts/region_pipeline.py R01 [R02 ...]
        CTC_GREEN=0.55 CTC_LC_FILTER=none ... (field-mask options; defaults 0.40 / natural_nonpivot)
"""
import json
import os
import re
import sys
import time
from pathlib import Path

import earthaccess
import h5py
import numpy as np
import pandas as pd
import planetary_computer
import pystac_client
import rasterio
import requests
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT
from rasterio.warp import reproject
from scipy import ndimage as ndi
from shapely.geometry import box as sbox, shape
from skimage.feature import peak_local_max
from skimage.measure import regionprops
from skimage.morphology import binary_opening, disk, remove_small_objects
from skimage.segmentation import watershed

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nisar_fetch as NF  # noqa: E402
import s2_fields as S2  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REG = json.loads((ROOT / "data" / "national" / "regions.json").read_text())
ASF = "https://api.daac.asf.alaska.edu/services/search/param"
WINTER = ("2025-10-15", "2026-01-31")
SUMMER = ("2026-06-10", "2026-10-31")
GREEN = float(os.environ.get("CTC_GREEN", "0.40"))  # seasonal-max NDVI above this = field candidate
MIN_HA = 3.0
# none | natural_nonpivot (drop non-circular fields whose WorldCover majority is shrub/grass) | natural (drop all such)
LC_FILTER = os.environ.get("CTC_LC_FILTER", "natural_nonpivot")
NATURAL = (20, 30)  # WorldCover v200 shrubland, grassland
RES = 40          # metres; national runs (Qassim deep dive uses 20 m)
PX_HA = (RES / 100) ** 2


def utm_epsg(lon, lat):
    return (32600 if lat >= 0 else 32700) + int((lon + 180) // 6) + 1


def pick_scenes(bbox):
    lon0, lat0, lon1, lat1 = bbox
    poly = f"POLYGON(({lon0} {lat0},{lon1} {lat0},{lon1} {lat1},{lon0} {lat1},{lon0} {lat0}))"
    for k in range(4):
        try:
            feats = requests.get(ASF, params={"dataset": "NISAR", "processingLevel": "GCOV", "intersectsWith": poly,
                                              "maxResults": 1000, "output": "geojson"}, timeout=180).json()["features"]
            break
        except Exception:
            if k == 3:
                raise
            time.sleep(15 * (k + 1))
    b = sbox(*bbox)
    groups = {}
    for f in feats:
        p = f["properties"]
        if "DHDH" not in p["fileName"] and "QPDH" not in p["fileName"]:
            continue
        k = (p["pathNumber"], p["frameNumber"])
        cov = shape(f["geometry"]).intersection(b).area / b.area
        d = p["startTime"][:10]
        g = groups.setdefault(k, {"cov": cov, "dates": {}})
        g["cov"] = min(g["cov"], cov) if g["dates"] else cov
        # keep newest processing version per date
        if d not in g["dates"] or p["fileName"] > g["dates"][d]["file"]:
            g["dates"][d] = {"url": p["url"], "file": p["fileName"], "start": p["startTime"]}
    best, score = None, -1
    for k, g in groups.items():
        w = [d for d in g["dates"] if WINTER[0] <= d <= WINTER[1]]
        s = [d for d in g["dates"] if SUMMER[0] <= d <= SUMMER[1]]
        sc = g["cov"] * (min(len(w), 3) + min(len(s), 4)) * (1 if w and s else 0.3)
        if sc > score:
            best, score = k, sc
    if best is None:
        return None, 0, []
    g = groups[best]
    w = sorted(d for d in g["dates"] if WINTER[0] <= d <= WINTER[1])[-3:]       # latest winter = biggest canopy
    s = sorted(d for d in g["dates"] if SUMMER[0] <= d <= SUMMER[1])
    if len(s) > 4:
        s = [s[i] for i in np.linspace(0, len(s) - 1, 4).round().astype(int)]
    return best, g["cov"], [g["dates"][d] | {"date": d} for d in w + s]


def season(d):
    return "winter" if WINTER[0] <= d <= WINTER[1] else ("summer" if SUMMER[0] <= d <= SUMMER[1] else None)


def run(rid):
    t0 = time.time()
    R = next(r for r in REG if r["id"] == rid)
    D = ROOT / "data" / "regions" / rid
    D.mkdir(parents=True, exist_ok=True)
    lon_c, lat_c = (R["bbox"][0] + R["bbox"][2]) / 2, (R["bbox"][1] + R["bbox"][3]) / 2
    cfg = {"bbox": R["bbox"], "crs": f"EPSG:{utm_epsg(lon_c, lat_c)}", "res_m": RES}
    S2.CFG = cfg
    NF.CFG = cfg
    S2.MAX_SCENES = 8  # scenes per Sentinel-2 tile and relative orbit, spread over the window
    S2.USE_OVERVIEWS = True  # 10 m bands read at their 40 m overview

    # --- radar scene choice first (to align the Sentinel-2 check window)
    tf_key, cov, scenes = pick_scenes(R["bbox"])
    meta = {"id": rid, "bbox": R["bbox"], "crs": cfg["crs"], "track_frame": tf_key, "coverage": round(cov, 2),
            "dates": [s["date"] for s in scenes]}
    print(rid, "track/frame", tf_key, "coverage", round(cov, 2), "dates", meta["dates"], flush=True)
    if not scenes:
        (D / "meta.json").write_text(json.dumps(meta | {"status": "no radar"}, indent=1))
        return

    # --- Sentinel-2 fields
    transform, w, h = S2.grid()
    nd = {}
    wd = [s["date"] for s in scenes if season(s["date"]) == "winter"]
    windows = {"winter": ("2025-11-01", "2026-03-15"), "summer": SUMMER}  # Sentinel-2 sees the wheat peak (Feb-Mar)
    if wd:
        windows["wcheck"] = (min(wd), max(wd))
    empty, skipped = {}, {}
    for name, (s, e) in windows.items():
        p, pc = D / f"ndvi_{name}.tif", D / f"nobs_{name}.tif"
        tags = {"ndvi": S2.NDVI_TAG, "window": f"{s}/{e}"}
        cached = None
        if p.exists() and pc.exists():
            with rasterio.open(p) as src, rasterio.open(pc) as srcc:
                # reuse only if made on this grid, from offset-corrected reflectance, over the same dates
                t = src.tags()
                if src.shape == (h, w) and t.get("ndvi") == S2.NDVI_TAG and t.get("window", tags["window"]) == tags["window"]:
                    cached, count = src.read(1), srcc.read(1)
        if cached is not None:
            nd[name] = cached
        else:
            nd[name], count = S2.season_max_ndvi(s, e, transform, w, h, return_count=True)
            skipped[name] = S2.LAST_SKIPPED
            # a composite missing scenes (failed reads) is saved untagged, so the next run rebuilds it
            S2.save_tif(nd[name], transform, p, tags=None if S2.LAST_SKIPPED else tags)
            S2.save_tif(count, transform, pc, dtype="uint8", nodata=None)
        empty[name] = round(float((count == 0).mean()), 4)  # share of the box with no clear look (a hole)
    print(rid, "Sentinel-2 empty share", empty, "skipped scenes", skipped, flush=True)
    meta["s2_empty_frac"] = empty
    meta["s2_skipped_scenes"] = skipped

    # --- ESA WorldCover v200 classes on the same grid (tree cover for palms; optional field filter), cached
    wc_p = D / "worldcover.tif"
    wc = None
    if wc_p.exists():
        with rasterio.open(wc_p) as src:
            if src.shape == (h, w):
                wc = src.read(1)
    if wc is None:
        wc = np.zeros((h, w), dtype="uint8")
        for it in S2.search_items(collections=["esa-worldcover"], bbox=R["bbox"],
                                  query={"esa_worldcover:product_version": {"eq": "2.0.0"}}):
            with rasterio.open(planetary_computer.sign(it.assets["map"].href.split("?")[0])) as src:
                with WarpedVRT(src, crs=cfg["crs"], transform=transform, width=w, height=h,
                               resampling=Resampling.mode) as vrt:
                    a = vrt.read(1)
            wc = np.where(wc == 0, a, wc).astype("uint8")  # tiles cover parts of the grid; 0 = no data
        S2.save_tif(wc, transform, wc_p, dtype="uint8", nodata=0)
    tree = wc == 10

    mask = (np.nan_to_num(nd["winter"]) > GREEN) | (np.nan_to_num(nd["summer"]) > GREEN)
    mask = remove_small_objects(binary_opening(mask, disk(1)), min_size=int(MIN_HA / PX_HA))
    dist = ndi.distance_transform_edt(mask)
    peaks = peak_local_max(dist, min_distance=max(3, int(160 / RES)), labels=ndi.label(mask)[0], exclude_border=False)
    markers = np.zeros(dist.shape, dtype="int32")
    markers[tuple(peaks.T)] = np.arange(1, len(peaks) + 1)
    labels = watershed(-dist, markers, mask=mask)
    if LC_FILTER != "none":
        # natural vegetation greened by rain (south-west) passes the NDVI test; drop fields whose WorldCover
        # majority is shrubland or grassland (natural_nonpivot keeps circular pivots of 10 ha or more)
        drop, drop_ha = [], 0.0
        for rp in regionprops(labels):
            cls = wc[rp.slice][labels[rp.slice] == rp.label]
            vals, cnt = np.unique(cls, return_counts=True)
            circ = 4 * np.pi * rp.area / (rp.perimeter ** 2) if rp.perimeter > 0 else 0
            pivot = circ > 0.75 and rp.area * PX_HA >= 10
            if vals[np.argmax(cnt)] in NATURAL and (LC_FILTER == "natural" or not pivot):
                drop.append(rp.label)
                drop_ha += rp.area * PX_HA
        labels[np.isin(labels, drop)] = 0
        meta["lc_filter"] = {"rule": LC_FILTER, "dropped_fields": len(drop), "dropped_ha": round(drop_ha)}
    meta["field_mask"] = {"green": GREEN, "lc_filter": LC_FILTER}
    S2.save_tif(labels, transform, D / "fields_labels.tif", dtype="int32", nodata=0)
    ids = np.unique(labels[labels > 0])
    print(rid, f"{len(ids)} fields mapped ({time.time() - t0:.0f}s)", flush=True)
    if not len(ids):  # e.g. small terraced or rain-fed plots below MIN_HA: nothing for the radar to classify
        (D / "meta.json").write_text(json.dumps(meta | {"fields": 0, "status": "no fields",
                                                        "seconds": round(time.time() - t0)}, indent=1))
        print(rid, "no fields of at least", MIN_HA, "ha; radar skipped", flush=True)
        return

    # --- NISAR HV
    todo = [s for s in scenes if not (D / f"hv_{s['date']}.tif").exists()]  # crops are cached per date
    files = {}
    if todo:
        earthaccess.login(strategy="netrc")
        files = dict(zip([s["date"] for s in todo], earthaccess.open([s["url"] for s in todo])))
    hv = {}
    for s in scenes:
        p = D / f"hv_{s['date']}.tif"
        if not p.exists():
            with h5py.File(files[s["date"]], "r") as h5:
                path = next(x for x in NF.find_layers(h5, NF.WANTED["GCOV"]) if x.endswith("HVHV"))
                res = NF.crop(h5, path)
                if res is None:
                    continue
                NF.save(*res, p)
        with rasterio.open(p) as src:
            a = np.full((h, w), np.nan, dtype="float32")
            reproject(rasterio.band(src, 1), a, src_nodata=src.nodata, dst_transform=transform,
                                    dst_crs=cfg["crs"], dst_nodata=np.nan, resampling=Resampling.average)
        hv[s["date"]] = np.where(a > 0, a, np.nan)
    print(rid, f"radar read ({time.time() - t0:.0f}s)", flush=True)

    # --- desert background and thresholds
    far = ~ndi.binary_dilation(labels > 0, iterations=10)
    B = max(8, int(320 / RES))  # desert patches ~10-40 ha
    hb, wb = h // B, w // B
    okp = far[:hb * B, :wb * B].reshape(hb, B, wb, B).all(axis=(1, 3))
    bg, patch, pseas = {}, [], []
    rows = []
    for d, a in hv.items():
        valid = far & np.isfinite(a)
        if valid.sum() < 1000:
            continue
        bg[d] = float(np.nanmedian(10 * np.log10(a[valid])))
        with np.errstate(all="ignore"):
            bm = 10 * np.log10(np.nanmean(a[:hb * B, :wb * B].reshape(hb, B, wb, B), axis=(1, 3)))
        patch.append(bm[okp] - bg[d])
        pseas.append(season(d))
        ok = np.isfinite(a) & (labels > 0)
        sm = ndi.sum(np.where(ok, a, 0), labels, ids)
        n = ndi.sum(ok, labels, ids)
        with np.errstate(all="ignore"):
            v = 10 * np.log10(np.where(n > 0, sm / n, np.nan))
        rows += [{"field_id": i, "date": d, "hv_db": float(x), "hv_norm": float(x - bg[d])} for i, x in zip(ids, v)]
    if not rows:  # every radar date missed the box or had too little desert to calibrate against
        (D / "meta.json").write_text(json.dumps(meta | {"fields": int(len(ids)), "status": "no radar",
                                                        "reason": "no usable radar date", "seconds": round(time.time() - t0)}, indent=1))
        print(rid, "no usable radar date", flush=True)
        return
    ts = pd.DataFrame(rows)
    ts["season"] = ts.date.map(season)
    ts.to_csv(D / "hv_timeseries.csv", index=False)
    patch, pseas = np.array(patch), np.array(pseas)
    thr = {}
    for se in ("winter", "summer"):
        if (pseas == se).sum():
            pk = np.nanmax(patch[pseas == se], axis=0)
            p16, p50 = np.nanpercentile(pk, [16, 50])
            thr[se] = float(p50 + 3 * (p50 - p16))

    # --- per-field table
    px_ha = PX_HA
    to_ll = Transformer.from_crs(cfg["crs"], 4326, always_xy=True)
    peak = ts.groupby(["field_id", "season"]).hv_norm.max().unstack()
    mean_all = ts.groupby("field_id").hv_db.mean()
    sd_all = ts.groupby("field_id").hv_db.std()
    recs = []
    for rp in regionprops(labels):
        r, c = rp.centroid
        x, y = transform * (c + 0.5, r + 0.5)
        lon, lat = to_ll.transform(x, y)
        sl = labels[rp.slice] == rp.label
        with np.errstate(all="ignore"):
            med = {k: float(np.nanmedian(np.where(sl, nd[k][rp.slice], np.nan))) for k in nd}
        circ = 4 * np.pi * rp.area / (rp.perimeter ** 2) if rp.perimeter > 0 else 0

        def green(k):  # None when Sentinel-2 had no clear look at the field (unknown, not 'not green')
            return None if k not in med or not np.isfinite(med[k]) else bool(med[k] > GREEN)

        rec = {"id": rp.label, "region": rid, "lon": round(lon, 5), "lat": round(lat, 5),
               "area_ha": round(rp.area * px_ha, 2), "circularity": round(min(circ, 1), 3),
               "tree_frac": round(float(tree[rp.slice][sl].mean()), 3),
               "s2_winter_active": green("winter"), "s2_summer_active": green("summer"),
               "s2_winter_check": green("wcheck"),
               "hv_mean_db": round(float(mean_all.get(rp.label, np.nan)), 2),
               "hv_sd_db": round(float(sd_all.get(rp.label, np.nan)), 2)}
        for se in ("winter", "summer"):
            v = peak[se].get(rp.label, np.nan) if se in peak else np.nan
            rec[f"hv_above_desert_{se}"] = round(float(v), 2) if np.isfinite(v) else None
            # None = season not observed (no radar date, no desert to calibrate, or no valid pixel on the field)
            rec[f"{se}_active"] = bool(v > thr[se]) if np.isfinite(v) and se in thr else None
        recs.append(rec)
    df = pd.DataFrame(recs)
    df["radar_seen"] = df.hv_mean_db.notna()
    wa, sa = df.winter_active, df.summer_active
    # palms are evergreen: tree cover and active in every season the radar observed (at least one)
    df["palm_grove"] = ((df.tree_frac >= 0.3) & (wa.notna() | sa.notna())
                        & (wa.isna() | wa.eq(True)) & (sa.isna() | sa.eq(True)))
    df.to_csv(D / "fields_radar.csv", index=False)

    # --- validation (fields the radar observed in that season and Sentinel-2 saw clearly)
    val = {"thresholds_db": {k: round(v, 2) for k, v in thr.items()}}
    for se, refc in (("winter", "s2_winter_check"), ("summer", "s2_summer_active")):
        m = df[df[f"{se}_active"].notna() & df[refc].notna()]
        if not len(m):
            continue
        r, s = m[f"{se}_active"].astype(bool), m[refc].astype(bool)
        w_ = m.area_ha
        tp, tn, fp, fn = (float(w_[r & s].sum()), float(w_[~r & ~s].sum()), float(w_[r & ~s].sum()), float(w_[~r & s].sum()))
        tot = tp + tn + fp + fn
        if tot == 0:
            continue
        po = (tp + tn) / tot
        pe = ((tp + fp) * (tp + fn) + (fn + tn) * (fp + tn)) / tot ** 2
        val[se] = {"area_agreement": round(po, 3), "kappa": round((po - pe) / (1 - pe), 3) if pe < 1 else None,
                   "radar_ha": round(tp + fp), "s2_ha": round(tp + fn),
                   "precision": round(tp / (tp + fp), 3) if tp + fp else None,
                   "recall": round(tp / (tp + fn), 3) if tp + fn else None,
                   "confusion_ha": {"tp": round(tp), "fp": round(fp), "fn": round(fn), "tn": round(tn)}}
    meta |= {"fields": int(len(df)), "radar_seen_fields": int(df.radar_seen.sum()), "field_ha": round(df.area_ha.sum()),
             "palm_ha": round(df[df.palm_grove].area_ha.sum()), "validation": val, "bg_median_db": bg,
             "seasons_observed": sorted(thr), "s2": {"ndvi": S2.NDVI_TAG, "scenes_per_tile_orbit": S2.MAX_SCENES},
             "status": "ok", "seconds": round(time.time() - t0)}
    (D / "meta.json").write_text(json.dumps(meta, indent=1))
    print(rid, "done", json.dumps(val), f"{meta['seconds']}s", flush=True)


if __name__ == "__main__":
    for rid in sys.argv[1:]:
        mp = ROOT / "data" / "regions" / rid / "meta.json"
        if mp.exists() and json.loads(mp.read_text()).get("status") in ("ok", "no radar", "no fields"):
            print(rid, "already finished, skipped", flush=True)
            continue
        try:
            run(rid)
        except Exception as e:  # keep the batch going; record the failure
            d = ROOT / "data" / "regions" / rid
            d.mkdir(parents=True, exist_ok=True)
            (d / "meta.json").write_text(json.dumps({"id": rid, "status": f"error: {e!r}"}))
            print(rid, "ERROR", repr(e), flush=True)
