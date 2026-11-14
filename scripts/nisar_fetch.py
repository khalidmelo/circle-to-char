"""Fetch NISAR layers over a small box and save them as GeoTIFFs.

Reads only the needed part of each HDF5 file over HTTPS (range requests),
so a 2 GB granule costs tens of MB. Needs a NASA Earthdata login in ~/.netrc.

Products and layers saved:
  GCOV  HHHH, HVHV backscatter (linear power), 20 m
  GUNW  coherenceMagnitude (12-day pair), unwrappedPhase
  SME2  soil moisture (any layer whose name contains 'soilMoisture')

Usage:
  .venv/bin/python scripts/nisar_fetch.py GCOV --track 42 --frame 15
  .venv/bin/python scripts/nisar_fetch.py --inspect GCOV --track 42 --frame 15 --max 1
"""
import argparse
import json
import re
from pathlib import Path

import earthaccess
import h5py
import numpy as np
import rasterio
import requests
from pyproj import Transformer
from rasterio.transform import from_origin

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "config.json").read_text())
ASF = "https://api.daac.asf.alaska.edu/services/search/param"

WANTED = {
    "GCOV": re.compile(r"/frequencyA/(HHHH|HVHV)$"),
    "GUNW": re.compile(r"/frequencyA/(unwrappedInterferogram|wrappedInterferogram)/HH/(coherenceMagnitude|unwrappedPhase)$"),
    "SME2": re.compile(r"SME2/grids/(soilMoisture|soilMoistureUncertainty|retrievalQualityFlag)$"),
}


def list_granules(product, track, frame):
    lon0, lat0, lon1, lat1 = CFG["bbox"]
    params = {
        "dataset": "NISAR",
        "processingLevel": product,
        "intersectsWith": f"POLYGON(({lon0} {lat0},{lon1} {lat0},{lon1} {lat1},{lon0} {lat1},{lon0} {lat0}))",
        "maxResults": 500,
        "output": "geojson",
    }
    feats = requests.get(ASF, params=params, timeout=120).json()["features"]
    out = []
    for f in feats:
        p = f["properties"]
        if track and p.get("pathNumber") != track:
            continue
        if frame and p.get("frameNumber") != frame:
            continue
        out.append({"url": p["url"], "file": p["fileName"], "start": p["startTime"]})
    # One granule per acquisition: prefer the newest processing version (last in name order)
    best = {}
    for g in sorted(out, key=lambda g: g["file"]):
        key = re.sub(r"_P\d{5}_.*$", "", g["file"])
        key = re.sub(r"_(BETA|PROVISIONAL)", "", key)
        best[key] = g
    return sorted(best.values(), key=lambda g: g["start"])


def find_layers(h5, pattern):
    hits = []
    h5.visititems(lambda name, obj: hits.append(name) if isinstance(obj, h5py.Dataset) and pattern.search("/" + name) else None)
    return hits


def sibling(h5, path, names):
    """Walk up from a dataset to find coordinate/projection datasets."""
    parts = path.split("/")
    for i in range(len(parts) - 1, 0, -1):
        grp = "/".join(parts[:i])
        for n in names:
            cand = f"{grp}/{n}"
            if cand in h5:
                return cand
    return None


def epsg_of(h5, path):
    proj = sibling(h5, path, ["projection"])
    if proj is None:
        return None
    ds = h5[proj]
    for key in ("epsg_code", "epsg"):
        if key in ds.attrs:
            return int(np.squeeze(ds.attrs[key]))
    try:
        return int(np.squeeze(ds[()]))
    except Exception:
        return None


def crop(h5, path):
    xs_p = sibling(h5, path, ["xCoordinates"])
    ys_p = sibling(h5, path, ["yCoordinates"])
    epsg = epsg_of(h5, path)
    xs, ys = h5[xs_p][()], h5[ys_p][()]
    lon0, lat0, lon1, lat1 = CFG["bbox"]
    tr = Transformer.from_crs(4326, epsg, always_xy=True)
    cx, cy = tr.transform([lon0, lon1, lon0, lon1], [lat0, lat0, lat1, lat1])
    xi = np.where((xs >= min(cx)) & (xs <= max(cx)))[0]
    yi = np.where((ys >= min(cy)) & (ys <= max(cy)))[0]
    if xi.size == 0 or yi.size == 0:
        return None
    r0, r1, c0, c1 = yi.min(), yi.max() + 1, xi.min(), xi.max() + 1
    arr = h5[path][r0:r1, c0:c1]
    if np.iscomplexobj(arr):
        arr = np.abs(arr)
    dx = float(xs[1] - xs[0])
    dy = float(ys[1] - ys[0])
    # Coordinates mark pixel centres; GeoTIFF origin is the top-left corner.
    x_left = xs[c0] - dx / 2
    y_top = ys[r0] - dy / 2 if dy < 0 else ys[r1 - 1] + dy / 2
    if dy > 0:
        arr = arr[::-1]
    transform = from_origin(x_left, y_top, abs(dx), abs(dy))
    return arr.astype("float32"), transform, epsg


def save(arr, transform, epsg, out):
    out.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        out, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1,
        dtype="float32", crs=f"EPSG:{epsg}", transform=transform, nodata=np.nan,
        compress="deflate", tiled=True,
    ) as dst:
        dst.write(arr, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("product", choices=list(WANTED))
    ap.add_argument("--track", type=int)
    ap.add_argument("--frame", type=int)
    ap.add_argument("--max", type=int, default=0)
    ap.add_argument("--inspect", action="store_true", help="print the file tree of the first granule and stop")
    a = ap.parse_args()

    grans = list_granules(a.product, a.track, a.frame)
    if a.max:
        grans = grans[: a.max]
    print(f"{len(grans)} {a.product} granules")
    earthaccess.login(strategy="netrc")
    files = earthaccess.open([g["url"] for g in grans])

    for g, fobj in zip(grans, files):
        with h5py.File(fobj, "r") as h5:
            if a.inspect:
                h5.visititems(lambda n, o: print(n, getattr(o, "shape", ""), getattr(o, "dtype", "")))
                return
            for path in find_layers(h5, WANTED[a.product]):
                res = crop(h5, path)
                if res is None:
                    print("  outside box:", path)
                    continue
                arr, tf, epsg = res
                tag = path.split("frequencyA/")[-1].replace("/", "_") if "frequencyA" in path else path.split("/")[-1]
                out = ROOT / "data" / "nisar" / a.product / f"{g['start'][:10]}_{g['file'][:40]}_{tag}.tif"
                save(arr, tf, epsg, out)
                print(f"  {g['start'][:10]} {tag} {arr.shape} -> {out.name}")


if __name__ == "__main__":
    main()
