"""Blind-check cards for the v2 crop-type map (a stratified random sample, Olofsson et al. 2014 design).

Draws a random sample of fields stratified by mapped crop type (fields of 3 ha or more, i.e. the 'reliable' and
'provisional' label tiers), and renders one card per field that does NOT show the mapped label:
  - the field's raw Landsat 8/9 NDVI looks (Aug 2025 - Nov 2026), no smoothing, no detected cycles;
  - six Sentinel-2 true-colour chips (1.6 x 1.6 km, 10 m) from the clearest scene in Dec, Feb, Apr, Jun, Aug and Oct,
    with the field outline drawn in.
The mapped labels go to a separate key file, read only when the check is scored.

Outputs (scratch folder given as the first argument):
  <dir>/cards/<sample_id>.png, <dir>/sample.csv (sample_id, region, id, uid, area_ha, lat, lon, stratum weight),
  <dir>/key.csv (sample_id, mapped crop_type)  -- keep away from the interpreters
Usage: .venv/bin/python scripts/v2_check_cards.py <dir> [per_class=35] [seed=2026] [exclude_sample.csv]
"""
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import planetary_computer
import pystac_client
import rasterio
from rasterio.vrt import WarpedVRT
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from pyproj import Transformer
from skimage.segmentation import find_boundaries

matplotlib.use("Agg")
import matplotlib.pyplot as plt

for _k, _v in {"GDAL_HTTP_MAX_RETRY": "6", "GDAL_HTTP_RETRY_DELAY": "3", "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
               "GDAL_HTTP_TIMEOUT": "60", "GDAL_HTTP_CONNECTTIMEOUT": "20",
               "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.TIF"}.items():
    os.environ.setdefault(_k, _v)
ROOT = Path(__file__).resolve().parents[1]
MONTHS = [("2025-12-01", "2025-12-31", "Dec 2025"), ("2026-02-01", "2026-02-28", "Feb 2026"), ("2026-04-01", "2026-04-30", "Apr 2026"),
          ("2026-06-01", "2026-06-30", "Jun 2026"), ("2026-08-01", "2026-08-31", "Aug 2026"), ("2026-10-01", "2026-10-31", "Oct 2026")]
HALF = 800      # m: chip half-width
RES = 10


def sample(per_class, seed, exclude=None):
    ct = pd.read_csv(ROOT / "data" / "national" / "v2" / "crop_types.csv", low_memory=False)
    fn = pd.read_csv(ROOT / "data" / "national" / "fields_national.csv", low_memory=False)[["region", "id", "lon", "lat"]]
    t = ct.merge(fn, on=["region", "id"])
    t = t[t.tier.isin(["reliable", "provisional"]) & (t.crop_type != "insufficient_data")]
    if exclude:   # a test sample must not reuse fields from the calibration sample
        t = t[~t.uid.isin(set(pd.read_csv(exclude).uid))]
    rng = np.random.default_rng(seed)
    rows = []
    for k, g in t.groupby("crop_type"):
        n = min(per_class, len(g))
        pick = g.iloc[rng.choice(len(g), n, replace=False)]
        pick = pick.assign(stratum=k, stratum_n=len(g), stratum_ha=float(g.area_ha.sum()))
        rows.append(pick)
    s = pd.concat(rows).sample(frac=1, random_state=seed).reset_index(drop=True)
    s["sample_id"] = [f"S{i:03d}" for i in range(len(s))]
    return s


def search_retry(cat, lon, lat, a, b, tries=8):
    """STAC search with exponential backoff: the API rate-limits bursts of searches (6 per card)."""
    import time
    for k in range(tries):
        try:
            return list(cat.search(collections=["sentinel-2-l2a"], intersects={"type": "Point", "coordinates": [lon, lat]},
                                   datetime=f"{a}/{b}", query={"eo:cloud_cover": {"lt": 20}}, max_items=20).items())
        except Exception:
            time.sleep(min(60, 3 * 2 ** k))
    return []


def chips(lon, lat, labels_info):
    try:
        cat = pystac_client.Client.open("https://planetarycomputer.microsoft.com/api/stac/v1", timeout=30)
    except TypeError:
        cat = pystac_client.Client.open("https://planetarycomputer.microsoft.com/api/stac/v1")
    epsg = 32600 + int((lon + 180) // 6) + 1
    x, y = Transformer.from_crs(4326, epsg, always_xy=True).transform(lon, lat)
    tf = from_origin(x - HALF, y + HALF, RES, RES)
    n = 2 * HALF // RES
    out = []
    for a, b, name in MONTHS:
        items = search_retry(cat, lon, lat, a, b)
        items.sort(key=lambda i: i.properties["eo:cloud_cover"])
        img = None
        for it in items[:3]:
            try:
                with rasterio.open(planetary_computer.sign(it.assets["visual"].href)) as src, \
                        WarpedVRT(src, crs=f"EPSG:{epsg}", transform=tf, width=n, height=n, resampling=Resampling.bilinear) as v:
                    arr = v.read()
                if (arr.sum(0) > 0).mean() > 0.9:
                    img = (np.transpose(arr, (1, 2, 0)), it.datetime.strftime("%d %b %Y"))
                    break
            except Exception:
                continue
        out.append((name, img))
    # field outline on the chip grid, from the 40 m labels
    rid, fid = labels_info
    with rasterio.open(ROOT / "data" / "regions" / rid / "fields_labels.tif") as src, \
            WarpedVRT(src, crs=f"EPSG:{epsg}", transform=tf, width=n, height=n, resampling=Resampling.nearest) as v:
        lab = v.read(1)
    edge = find_boundaries(lab == fid, mode="inner")
    return out, edge


def card(row, outdir):
    nd = pd.read_csv(ROOT / "data" / "regions" / row.region / "landsat_ndvi.csv.gz")
    s = nd[nd.id == row.id].copy()
    s["date"] = pd.to_datetime(s.date)
    ch, edge = chips(row.lon, row.lat, (row.region, row.id))
    fig = plt.figure(figsize=(12, 6.4), dpi=90)
    ax = fig.add_axes([0.06, 0.58, 0.9, 0.36])
    ax.plot(s.date, s.ndvi, "o", ms=4, color="#1d56a8")
    ax.set_ylim(-0.05, 1.0); ax.set_ylabel("NDVI (raw Landsat looks)")
    ax.set_xlim(pd.Timestamp("2025-08-01"), pd.Timestamp("2026-11-15"))
    for yv in (0.25, 0.4):
        ax.axhline(yv, color="#c3ccd6", lw=0.8)
    ax.grid(axis="x", color="#eef1f4")
    ax.set_title(f"{row.sample_id}   {row.area_ha:.1f} ha   lat {row.lat:.2f}", loc="left", fontsize=10)
    for i, (name, img) in enumerate(ch):
        a = fig.add_axes([0.02 + i * 0.163, 0.03, 0.155, 0.46])
        if img is not None:
            rgb = img[0].copy()
            rgb[edge] = [255, 255, 0]
            a.imshow(rgb)
            a.set_title(img[1], fontsize=8)
        else:
            a.text(0.5, 0.5, f"{name}\nno clear scene", ha="center", va="center", fontsize=8)
        a.set_xticks([]); a.set_yticks([])
    fig.savefig(outdir / "cards" / f"{row.sample_id}.png")
    plt.close(fig)
    return row.sample_id


def main(d, per_class=35, seed=2026, exclude=None):
    d = Path(d)
    (d / "cards").mkdir(parents=True, exist_ok=True)
    s = sample(per_class, seed, exclude)
    s[["sample_id", "region", "id", "uid", "area_ha", "lat", "lon", "stratum", "stratum_n", "stratum_ha"]] \
        .rename(columns={"stratum": "stratum_key"}).drop(columns=["stratum_key"]).to_csv(d / "sample.csv", index=False)
    s[["sample_id", "crop_type", "stratum_n", "stratum_ha"]].to_csv(d / "key.csv", index=False)
    todo = [r for r in s.itertuples() if not (d / "cards" / f"{r.sample_id}.png").exists()]
    def safe(r):
        try:
            return card(r, d)
        except Exception as e:
            print(r.sample_id, "FAILED", repr(e)[:160], flush=True)
            return None
    with ThreadPoolExecutor(3) as ex:
        for i, sid in enumerate(ex.map(safe, todo)):
            if i % 25 == 0:
                print(i, sid, flush=True)
    print(f"{len(s)} cards in {d / 'cards'}; strata: {s.crop_type.value_counts().to_dict()}")


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0], int(a[1]) if len(a) > 1 else 35, int(a[2]) if len(a) > 2 else 2026, a[3] if len(a) > 3 else None)
