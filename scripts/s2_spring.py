"""Spring check: separate wheat-then-summer-crop rotations from perennial fodder and palms.

Saudi wheat is harvested around April-May. A field green in winter AND summer that goes brown in
late spring (median NDVI < 0.30, 20 Apr - 5 Jun 2026) is a rotation that leaves wheat straw;
one that stays green is perennial (alfalfa) or trees. NISAR has no Feb-Jun 2026 scenes over
Saudi Arabia, so this uses ESA Sentinel-2.

Adds columns ndvi_spring_median and spring_brown to data/regions/<R>/fields_radar.csv.
Usage: .venv/bin/python scripts/s2_spring.py R04 [R05 ...]   (or "all")
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import planetary_computer
import pystac_client
import rasterio
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT
from scipy import ndimage as ndi

sys.path.insert(0, str(Path(__file__).resolve().parent))
import s2_fields as S2  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
WINDOW = "2026-04-20/2026-06-05"
BROWN = 0.30
PER_TILE = 6


def run(rid):
    D = ROOT / "data" / "regions" / rid
    meta = json.loads((D / "meta.json").read_text())
    if meta.get("status") != "ok":
        return
    df = pd.read_csv(D / "fields_radar.csv")
    if "spring_brown" in df:
        print(rid, "already done")
        return
    with rasterio.open(D / "fields_labels.tif") as src:
        labels, tf, crs = src.read(1), src.transform, src.crs
    h, w = labels.shape
    ids = df.id.values
    S2.USE_OVERVIEWS = True
    items = S2.search_items(collections=["sentinel-2-l2a"], bbox=meta["bbox"], datetime=WINDOW,
                            query={"eo:cloud_cover": {"lt": 20}})
    items = S2.pick_items(items, PER_TILE)  # per tile and relative orbit, spread over the window
    per_scene = []
    for it in items:
        b = S2.read_bands(it, crs, tf, w, h)
        if b is None:
            continue
        ok = np.isin(b["SCL"], [4, 5, 6]) & (b["B04"] > 0) & (b["B08"] > 0) & (labels > 0)
        nd = np.where(ok, S2.ndvi(b, S2.dn_offset(it)), 0)  # offset-corrected reflectance
        s = ndi.sum(nd, labels, ids)
        n = ndi.sum(ok, labels, ids)
        with np.errstate(all="ignore"):
            # use a field's mean only if at least half of it was clear in this scene
            area = ndi.sum(labels > 0, labels, ids)
            per_scene.append(np.where(n >= 0.5 * area, s / np.maximum(n, 1), np.nan))
    arr = np.array(per_scene) if per_scene else np.full((1, len(ids)), np.nan)
    with np.errstate(all="ignore"):
        med = np.nanmedian(arr, axis=0)
    df["ndvi_spring_median"] = np.round(med, 3)
    df["spring_brown"] = pd.Series(np.where(np.isfinite(med), med < BROWN, None), dtype=object)  # None = no clear look
    df.to_csv(D / "fields_radar.csv", index=False)
    yr = df.winter_active.eq(True) & df.summer_active.eq(True) & ~df.palm_grove.eq(True)
    df["spring_brown"] = df.spring_brown.eq(True)  # for the printout only
    print(rid, f"{len(items)} scenes; year-round fields {yr.sum()}, of which brown in spring (wheat rotation) "
               f"{(yr & df.spring_brown).sum()} ({df[yr & df.spring_brown].area_ha.sum():,.0f} ha of {df[yr].area_ha.sum():,.0f} ha)", flush=True)


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["all"]:
        args = sorted(p.parent.name for p in (ROOT / "data" / "regions").glob("R*/meta.json"))
    for rid in args:
        try:
            run(rid)
        except Exception as e:
            print(rid, "ERROR", repr(e), flush=True)
