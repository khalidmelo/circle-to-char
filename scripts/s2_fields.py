"""Map farm fields (centre pivots and others) in the study box from ESA Sentinel-2.

Steps
  1. Seasonal maximum NDVI (winter, summer) on a 20 m UTM grid shared with the radar.
  2. Fields = pixels green in either season; touching circles split by watershed.
  3. Per field: area, centroid, circularity (1 = perfect circle), and whether it was
     green in winter and/or summer (the optical reference the radar is checked against).

Outputs (data/fields/)
  ndvi_max_<season>.tif, fields_labels.tif, fields.csv, fields_preview.png

Run:  .venv/bin/python scripts/s2_fields.py
"""
import json
import os
import time
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import planetary_computer
import pystac_client
import rasterio
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT
from scipy import ndimage as ndi
from skimage.feature import peak_local_max
from skimage.measure import regionprops
from skimage.morphology import binary_opening, disk, remove_small_objects
from skimage.segmentation import watershed

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Remote reads: retry transient HTTP errors, never hang on a dead connection, skip directory listings.
for _k, _v in {"GDAL_HTTP_MAX_RETRY": "6", "GDAL_HTTP_RETRY_DELAY": "3", "GDAL_HTTP_TIMEOUT": "120",
               "GDAL_HTTP_CONNECTTIMEOUT": "30", "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
               "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.TIF"}.items():
    os.environ.setdefault(_k, _v)

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "config.json").read_text())
PC_STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
OUT = ROOT / "data" / "fields"
OUT.mkdir(parents=True, exist_ok=True)

GREEN = 0.40        # NDVI above this = actively growing crop (common threshold for irrigated crops)
MIN_HA = 3.0        # ignore patches smaller than 3 ha
MAX_SCENES = 30     # per Sentinel-2 tile and relative orbit
USE_OVERVIEWS = False  # national runs: read the coarsest overview no finer than the grid (far fewer requests)
NDVI_TAG = "offset_corrected"  # written into cached composites; older caches (raw DNs) lack it and are rebuilt
LAST_SKIPPED = 0  # scenes the last season_max_ndvi call could not read (after retries)


def dn_offset(it):
    """L2A processing baseline 04.00 and later (from 25 Jan 2022) store DN = 10000 x reflectance + 1000."""
    try:
        return 1000.0 if float(it.properties.get("s2:processing_baseline", "99")) >= 4.0 else 0.0
    except ValueError:
        return 1000.0


def ndvi(b, off):
    """NDVI from L2A digital numbers: remove the offset, clip negative reflectance (over-correction) at 0."""
    r = np.clip(b["B04"] - off, 0, None)
    n = np.clip(b["B08"] - off, 0, None)
    return (n - r) / (n + r + 1e-6)


def pick_items(items, k):
    """Up to k scenes per Sentinel-2 tile AND relative orbit: the window split into k equal runs of dates,
    clearest scene of each. A tile at a swath edge is only partly imaged by each orbit, so choosing per tile
    alone can take every scene from the orbit that misses part of it (holes); spreading the dates over the
    window catches each crop near its peak."""
    groups = {}
    for it in items:
        key = (it.properties.get("s2:mgrs_tile", "?"), it.properties.get("sat:relative_orbit"))
        groups.setdefault(key, []).append(it)
    out = []
    for lst in groups.values():
        lst.sort(key=lambda i: i.datetime)
        if len(lst) > k:
            lst = [min((lst[j] for j in run), key=lambda i: i.properties.get("eo:cloud_cover", 0))
                   for run in np.array_split(np.arange(len(lst)), k)]
        out += lst
    return out


def search_items(**kw):
    """Planetary Computer STAC search, retried: the API sometimes drops connections mid-response."""
    from pystac_client.stac_api_io import StacApiIO
    from urllib3.util.retry import Retry
    for k in range(5):
        try:
            io = StacApiIO(timeout=(30, 180), max_retries=Retry(total=5, backoff_factor=2, allowed_methods=None,
                                                                status_forcelist=[429, 500, 502, 503, 504]))
            cat = pystac_client.Client.open(PC_STAC, modifier=planetary_computer.sign_inplace, stac_io=io)
            return list(cat.search(**kw).items())
        except Exception as e:
            if k == 4:
                raise
            print(f"  STAC search failed ({repr(e)[:80]}), retry {k + 1}", flush=True)
            time.sleep(15 * (k + 1))


def open_cog(href, res):
    """Open a COG; with USE_OVERVIEWS, at the coarsest overview whose pixels are no larger than res metres."""
    src = rasterio.open(href)
    if USE_OVERVIEWS:
        lvl = sum(1 for f in src.overviews(1) if src.res[0] * f <= res + 1e-6) - 1
        if lvl >= 0:
            src.close()
            src = rasterio.open(href, overview_level=lvl)
    return src


def grid():
    lon0, lat0, lon1, lat1 = CFG["bbox"]
    tr = Transformer.from_crs(4326, CFG["crs"], always_xy=True)
    xs, ys = tr.transform([lon0, lon1, lon0, lon1], [lat0, lat0, lat1, lat1])
    r = CFG["res_m"]
    x0, x1 = np.floor(min(xs) / r) * r, np.ceil(max(xs) / r) * r
    y0, y1 = np.floor(min(ys) / r) * r, np.ceil(max(ys) / r) * r
    w, h = int((x1 - x0) / r), int((y1 - y0) / r)
    return from_origin(x0, y1, r, r), w, h


def read_bands(it, crs, transform, w, h, bands=("B04", "B08", "SCL"), tries=3):
    """Read bands of one Sentinel-2 item onto the grid; retry, then skip the scene (returns None)."""
    for k in range(tries):
        try:
            b = {}
            for band in bands:
                # sign at read time from the bare URL: the token signed at search time expires within the hour
                href = planetary_computer.sign(it.assets[band].href.split("?")[0])
                with open_cog(href, abs(transform.a)) as src:
                    with WarpedVRT(src, crs=crs, transform=transform, width=w, height=h,
                                   resampling=Resampling.nearest if band == "SCL" else Resampling.average) as vrt:
                        b[band] = vrt.read(1).astype("float32")
            return b
        except Exception as e:  # network hiccup: wait and retry
            if k == tries - 1:
                print("  skipped scene", it.id, repr(e)[:80], flush=True)
                return None
            time.sleep(5 * (k + 1))


def season_max_ndvi(start, end, transform, w, h, return_count=False):
    """Seasonal maximum NDVI; with return_count, also the number of clear looks per pixel (0 = hole).
    Sets LAST_SKIPPED to the number of scenes that could not be read."""
    global LAST_SKIPPED
    items = search_items(collections=["sentinel-2-l2a"], bbox=CFG["bbox"], datetime=f"{start}/{end}",
                         query={"eo:cloud_cover": {"lt": 20}})
    items = pick_items(items, MAX_SCENES)
    print(f"  {len(items)} scenes {start}..{end}")
    best = np.full((h, w), np.nan, dtype="float32")
    count = np.zeros((h, w), dtype="uint8")
    LAST_SKIPPED = 0
    for it in items:
        b = read_bands(it, CFG["crs"], transform, w, h)
        if b is None:
            LAST_SKIPPED += 1
            continue
        # Scene classification: keep vegetation (4), bare soil (5), water (6); drop cloud/shadow/no data
        ok = np.isin(b["SCL"], [4, 5, 6]) & (b["B04"] > 0) & (b["B08"] > 0)
        nd = np.where(ok, ndvi(b, dn_offset(it)), np.nan)
        best = np.fmax(best, nd)
        count += ok.astype("uint8")
    return (best, count) if return_count else best


def save_tif(arr, transform, path, dtype="float32", nodata=np.nan, tags=None):
    with rasterio.open(path, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1,
                       dtype=dtype, crs=CFG["crs"], transform=transform, nodata=nodata,
                       compress="deflate", tiled=True) as dst:
        dst.write(arr.astype(dtype), 1)
        if tags:
            dst.update_tags(**tags)


def main():
    transform, w, h = grid()
    print(f"grid {w} x {h} at {CFG['res_m']} m")
    nd = {}
    for name, (s, e) in CFG["seasons"].items():
        p = OUT / f"ndvi_max_{name}.tif"
        cached = None
        if p.exists():
            with rasterio.open(p) as src:
                if src.tags().get("ndvi") == NDVI_TAG:  # older composites were made from raw DNs: rebuild
                    cached = src.read(1)
        if cached is not None:
            nd[name] = cached
        else:
            nd[name] = season_max_ndvi(s, e, transform, w, h)
            save_tif(nd[name], transform, p, tags={"ndvi": NDVI_TAG})

    green_w = np.nan_to_num(nd["winter"]) > GREEN
    green_s = np.nan_to_num(nd["summer"]) > GREEN
    mask = binary_opening(green_w | green_s, disk(1))
    px_ha = (CFG["res_m"] ** 2) / 1e4
    mask = remove_small_objects(mask, min_size=int(MIN_HA / px_ha))

    # Split touching circles: peaks of the distance-to-edge map seed a watershed.
    dist = ndi.distance_transform_edt(mask)
    peaks = peak_local_max(dist, min_distance=8, labels=ndi.label(mask)[0], exclude_border=False)
    markers = np.zeros_like(dist, dtype="int32")
    markers[tuple(peaks.T)] = np.arange(1, len(peaks) + 1)
    labels = watershed(-dist, markers, mask=mask)
    save_tif(labels, transform, OUT / "fields_labels.tif", dtype="int32", nodata=0)

    to_ll = Transformer.from_crs(CFG["crs"], 4326, always_xy=True)
    rows = []
    for rp in regionprops(labels):
        area_ha = rp.area * px_ha
        if area_ha < MIN_HA:
            continue
        r, c = rp.centroid
        x, y = transform * (c + 0.5, r + 0.5)
        lon, lat = to_ll.transform(x, y)
        circ = 4 * np.pi * rp.area / (rp.perimeter ** 2) if rp.perimeter > 0 else 0
        sl = labels[rp.slice] == rp.label
        fw = np.nanmedian(np.where(sl, nd["winter"][rp.slice], np.nan))
        fs = np.nanmedian(np.where(sl, nd["summer"][rp.slice], np.nan))
        rows.append({
            "id": rp.label, "lon": round(lon, 5), "lat": round(lat, 5), "area_ha": round(area_ha, 2),
            "circularity": round(min(circ, 1.0), 3), "radius_m": round(np.sqrt(rp.area * CFG["res_m"] ** 2 / np.pi)),
            "ndvi_winter": round(float(fw), 3), "ndvi_summer": round(float(fs), 3),
            "s2_winter_active": bool(fw > GREEN), "s2_summer_active": bool(fs > GREEN),
        })
    df = pd.DataFrame(rows)
    df["is_pivot"] = (df.circularity > 0.75) & (df.area_ha >= 10)
    df.to_csv(OUT / "fields.csv", index=False)

    print(f"{len(df)} fields, {df.area_ha.sum():,.0f} ha; pivots {df.is_pivot.sum()} ({df[df.is_pivot].area_ha.sum():,.0f} ha)")
    print("active area (ha): winter", round(df[df.s2_winter_active].area_ha.sum()), "summer", round(df[df.s2_summer_active].area_ha.sum()),
          "both", round(df[df.s2_winter_active & df.s2_summer_active].area_ha.sum()))

    fig, ax = plt.subplots(1, 3, figsize=(18, 6))
    ax[0].imshow(nd["winter"], vmin=0, vmax=0.8, cmap="YlGn"); ax[0].set_title("Max NDVI winter 2025/26")
    ax[1].imshow(nd["summer"], vmin=0, vmax=0.8, cmap="YlGn"); ax[1].set_title("Max NDVI summer 2026")
    cls = np.zeros_like(labels, dtype="uint8")
    for _, r in df.iterrows():
        cls[labels == r.id] = 1 + int(r.s2_winter_active) + 2 * int(r.s2_summer_active)
    ax[2].imshow(cls, cmap=matplotlib.colors.ListedColormap(["white", "lightgrey", "tab:orange", "tab:blue", "tab:green"]),
                 vmin=0, vmax=4, interpolation="nearest")
    ax[2].set_title("Fields: grey idle, orange winter only, blue summer only, green both")
    for a in ax:
        a.set_xticks([]); a.set_yticks([])
    fig.tight_layout()
    fig.savefig(OUT / "fields_preview.png", dpi=100)


if __name__ == "__main__":
    main()
