"""Landsat 8/9 Collection 2 Level-2 per overpass, cached per region on two grids aligned with the field labels.

Grids
  40 m  = the region's field-label grid (data/regions/<R>/fields_labels.tif)          -> optical file  <stem>_o.tif
  120 m = 3 x 3 label pixels, same origin; Landsat's thermal band is measured at 100 m -> thermal file  <stem>_t.tif

Per overpass (acquisition date x WRS path; rows of one path and date are mosaicked, first scene wins):
  red, nir08   surface reflectance = DN * scale + offset (STAC raster:bands), averaged onto 40 m
  qa_pixel     nearest onto 40 m; clear = bits 0-4 (fill, dilated cloud, cirrus, cloud, shadow) 0 and bit 6 (clear) set
  qa_aerosol   nearest onto 40 m; aerosol level (bits 6-7) 3 = high -> not clear
  lwir11       surface temperature (K), averaged onto 120 m
  emis         the ST product's surface emissivity (ASTER GED based), averaged onto 120 m
  drad         downwelling radiance; smooth, so one coarse read per scene gives a scene median (tag)

Optical file (int16): 1 NDVI x 10000, 2 clear flag from qa_pixel (1 clear, 0 not, -1 no data), 3 aerosol-high flag
  (qa_aerosol level 3; kept separate because the flag is set widely over bright desert, where the aerosol retrieval
  is weak; it never masks the thermal band)
Thermal file (int16): 1 ST in 0.01 K above 200 K, 2 emissivity x 10000, 3 NDVI x 10000 (from 3x3-averaged
  reflectance), 4 clear flag (1 only if all nine 40 m sub-pixels are clear); nodata -32768
Tags: landsat=LS_TAG, items, drad (W m-2 sr-1 um-1), sensor. Files are written to .tmp and renamed.
A per-region manifest out/v2/landsat_manifest/<R>.json lists overpasses expected, read, empty and failed.

Usage: .venv/bin/python scripts/landsat_c2.py R04 [R05 ...] | all   [--threads 8]
"""
import argparse
import json
import os
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import planetary_computer
import pystac_client
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import Affine
from rasterio.vrt import WarpedVRT

for _k, _v in {"GDAL_HTTP_MAX_RETRY": "8", "GDAL_HTTP_RETRY_DELAY": "3", "GDAL_HTTP_TIMEOUT": "120",
               "GDAL_HTTP_CONNECTTIMEOUT": "30", "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
               "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.TIF"}.items():
    os.environ.setdefault(_k, _v)

ROOT = Path(__file__).resolve().parents[1]
PC_STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
SEASON = "2025-08-01/2026-11-15"     # 15.5 months: crop cycles that start before November are seen whole
S = 3
MAX_CLOUD = 60
LS_TAG = "c2l2_v4"
SINGLE_SCENE_OK = ("c2l2_v3",)   # v3 mosaicked rows wrongly (fill pixels, qa bit 0, counted as data); single-scene overpasses are unaffected
NODATA = -32768
DEFAULT_SCALE = {"lwir11": (0.00341802, 149.0), "red": (0.0000275, -0.2), "nir08": (0.0000275, -0.2),
                 "emis": (0.0001, 0.0), "drad": (0.001, 0.0)}


def grids(rid):
    with rasterio.open(ROOT / "data" / "regions" / rid / "fields_labels.tif") as src:
        tf, crs, h, w = src.transform, src.crs, src.height, src.width
    t120 = Affine(tf.a * S, tf.b, tf.c, tf.d, tf.e * S, tf.f)
    return crs, (tf, w, h), (t120, -(-w // S), -(-h // S))


def search(bbox):
    cat = pystac_client.Client.open(PC_STAC)
    items = cat.search(collections=["landsat-c2-l2"], bbox=bbox, datetime=SEASON,
                       query={"platform": {"in": ["landsat-8", "landsat-9"]}, "eo:cloud_cover": {"lt": MAX_CLOUD}}).items()
    groups = defaultdict(list)
    for it in items:
        if it.properties.get("landsat:correction", "L2SP") != "L2SP" or "lwir11" not in it.assets:
            continue
        groups[(it.datetime.strftime("%Y%m%d"), it.properties["platform"], int(it.properties["landsat:wrs_path"]))].append(it)
    return groups


def scale_of(it, asset):
    rb = (it.assets[asset].extra_fields.get("raster:bands") or [{}])[0]
    d = DEFAULT_SCALE.get(asset, (1.0, 0.0))
    return float(rb.get("scale", d[0])), float(rb.get("offset", d[1]))


def warp(it, asset, crs, g, resampling, overview=None):
    """Warp one asset onto a grid. overview=0 reads the COG's first overview (60 m): used for the 100 m thermal
    band and emissivity, which are averaged onto 120 m anyway, so it only saves bytes."""
    tf, w, h = g
    href = planetary_computer.sign(it.assets[asset].href)   # sign just before reading: tokens expire
    kw = {} if overview is None else {"overview_level": overview}
    try:
        src = rasterio.open(href, **kw)
    except Exception:
        src = rasterio.open(href)
    with src, WarpedVRT(src, crs=crs, transform=tf, width=w, height=h, resampling=resampling, src_nodata=0, nodata=0) as vrt:
        return vrt.read(1)


def scene_median(it, asset):
    href = planetary_computer.sign(it.assets[asset].href)
    with rasterio.open(href) as src:
        a = src.read(1, out_shape=(max(1, src.height // 64), max(1, src.width // 64)), resampling=Resampling.nearest)
    v = a[a > 0].astype(np.float64)
    sc, off = scale_of(it, asset)
    return float(np.median(v) * sc + off) if v.size else np.nan


def block_all(a):
    h, w = a.shape
    H, W = -(-h // S), -(-w // S)
    p = np.zeros((H * S, W * S), bool)
    p[:h, :w] = a
    return p.reshape(H, S, W, S).all(axis=(1, 3))


def block_mean(a):
    h, w = a.shape
    H, W = -(-h // S), -(-w // S)
    p = np.full((H * S, W * S), np.nan, np.float32)
    p[:h, :w] = a
    with np.errstate(all="ignore"):
        return np.nanmean(p.reshape(H, S, W, S), axis=(1, 3))


def overpass(items, crs, g40, g120):
    tf40, w40, h40 = g40
    tf120, w120, h120 = g120
    red = np.full((h40, w40), np.nan, np.float32); nir = red.copy()
    clear40 = np.full((h40, w40), -1, np.int16)
    aerhi = np.zeros((h40, w40), np.int16)
    st = np.full((h120, w120), np.nan, np.float32); em = st.copy()
    drads = []
    for it in items:
        qa = warp(it, "qa_pixel", crs, g40, Resampling.nearest).astype(np.uint16)
        has = (qa > 0) & ((qa & 1) == 0) & (clear40 < 0)   # qa bit 0 = fill: outside this scene's footprint
        if not has.any():
            continue
        aer = warp(it, "qa_aerosol", crs, g40, Resampling.nearest).astype(np.uint8) if "qa_aerosol" in it.assets else np.zeros_like(qa, np.uint8)
        r = warp(it, "red", crs, g40, Resampling.average).astype(np.float32)
        n = warp(it, "nir08", crs, g40, Resampling.average).astype(np.float32)
        (rs, ro), (ns, no) = scale_of(it, "red"), scale_of(it, "nir08")
        ok = ((qa & 0b11111) == 0) & (((qa >> 6) & 1) == 1) & (r > 0) & (n > 0)
        aerhi[has] = (((aer[has] >> 6) & 3) == 3).astype(np.int16)
        red[has] = np.where(r[has] > 0, r[has] * rs + ro, np.nan)
        nir[has] = np.where(n[has] > 0, n[has] * ns + no, np.nan)
        clear40[has] = ok[has].astype(np.int16)
        lw = warp(it, "lwir11", crs, g120, Resampling.average, overview=0).astype(np.float32)
        e = warp(it, "emis", crs, g120, Resampling.average, overview=0).astype(np.float32)
        (ls, lo), (es, eo) = scale_of(it, "lwir11"), scale_of(it, "emis")
        new = (lw > 0) & ~np.isfinite(st)
        st[new] = lw[new] * ls + lo
        em[new] = np.where(e[new] > 0, e[new] * es + eo, np.nan)
        drads.append(scene_median(it, "drad"))
    if not (clear40 == 1).any():
        return None
    with np.errstate(all="ignore"):
        nd40 = (nir - red) / (nir + red)
        r120, n120 = block_mean(red), block_mean(nir)
        nd120 = (n120 - r120) / (n120 + r120)
    c120 = np.where(block_all(clear40 == 1) & np.isfinite(st), 1, np.where(block_all(clear40 < 0), -1, 0)).astype(np.int16)
    opt = np.full((3, h40, w40), NODATA, np.int16)
    fin = np.isfinite(nd40)
    opt[0][fin] = np.clip(np.round(nd40[fin] * 10000), -10000, 10000)
    opt[1] = clear40
    opt[2] = aerhi
    th = np.full((4, h120, w120), NODATA, np.int16)
    g = np.isfinite(st) & (st > 200)
    th[0][g] = np.clip(np.round((st[g] - 200.0) * 100), -32767, 32767)
    g = np.isfinite(em)
    th[1][g] = np.clip(np.round(em[g] * 10000), 0, 10000)
    g = np.isfinite(nd120)
    th[2][g] = np.clip(np.round(nd120[g] * 10000), -10000, 10000)
    th[3] = c120
    return opt, th, float(np.nanmedian(drads)) if drads else np.nan


def write(path, arr, crs, tf, tags):
    prof = dict(driver="GTiff", dtype="int16", count=arr.shape[0], width=arr.shape[2], height=arr.shape[1], crs=crs,
                transform=tf, nodata=NODATA, compress="deflate", predictor=2, tiled=True, blockxsize=256, blockysize=256)
    tmp = path.with_suffix(".tmp.tif")
    with rasterio.open(tmp, "w", **prof) as dst:
        dst.write(arr)
        dst.update_tags(**tags)
    os.replace(tmp, path)


def cached(path, w, h, n_items=1):
    try:
        with rasterio.open(path) as src:
            tag = src.tags().get("landsat")
            ok_tag = tag == LS_TAG or (tag in SINGLE_SCENE_OK and n_items == 1)
            return ok_tag and (src.width, src.height) == (w, h)
    except Exception:
        return False


def run(rid, threads):
    R = ROOT / "data" / "regions" / rid
    if not (R / "fields_labels.tif").exists():
        print(rid, "no fields grid; skipped", flush=True)
        return
    meta = json.loads((R / "meta.json").read_text())
    crs, g40, g120 = grids(rid)
    D = ROOT / "data" / "landsat" / rid
    D.mkdir(parents=True, exist_ok=True)
    groups = search(meta["bbox"])
    todo = []
    for (d, plat, path), items in sorted(groups.items()):
        stem = f"{d}_{plat.replace('landsat-', 'L')}_{path:03d}"
        if not (cached(D / f"{stem}_o.tif", g40[1], g40[2], len(items)) and cached(D / f"{stem}_t.tif", g120[1], g120[2], len(items))):
            todo.append((stem, items))
    t0, done, empty, failed = time.time(), 0, 0, []
    with ThreadPoolExecutor(threads) as ex:
        futs = {ex.submit(overpass, items, crs, g40, g120): (stem, items) for stem, items in todo}
        for fu in as_completed(futs):
            stem, items = futs[fu]
            try:
                res = fu.result()
            except Exception as e:
                failed.append(stem)
                print(rid, stem, "FAILED", repr(e)[:200], flush=True)
                continue
            tags = {"landsat": LS_TAG, "items": ",".join(i.id for i in items), "sensor": stem.split("_")[1]}
            if res is None:
                empty += 1
                opt = np.full((3, g40[2], g40[1]), NODATA, np.int16); opt[1] = 0; opt[2] = 0
                th = np.full((4, g120[2], g120[1]), NODATA, np.int16); th[3] = 0
                drad = np.nan
            else:
                opt, th, drad = res
            write(D / f"{stem}_o.tif", opt, crs, g40[0], tags)
            write(D / f"{stem}_t.tif", th, crs, g120[0], {**tags, "drad": f"{drad:.4f}"})
            done += 1
    man = {"region": rid, "season": SEASON, "tag": LS_TAG, "overpasses": len(groups), "read": done, "empty": empty,
           "failed": failed, "cached_before": len(groups) - len(todo), "seconds": round(time.time() - t0)}
    (ROOT / "out" / "v2" / "landsat_manifest").mkdir(parents=True, exist_ok=True)
    (ROOT / "out" / "v2" / "landsat_manifest" / f"{rid}.json").write_text(json.dumps(man, indent=1))
    print(rid, json.dumps(man), flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("regions", nargs="+")
    ap.add_argument("--threads", type=int, default=8)
    a = ap.parse_args()
    rids = a.regions
    if rids == ["all"]:
        rids = sorted(p.parent.name for p in (ROOT / "data" / "regions").glob("R*/fields_labels.tif"))
    for rid in rids:
        try:
            run(rid, a.threads)
        except Exception as e:
            print(rid, "ERROR", repr(e)[:300], flush=True)
