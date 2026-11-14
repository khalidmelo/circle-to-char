"""Sentinel-2 reference over the SAME date windows the radar covers, for a fair check.

NISAR's winter scenes over Qassim run 1 Nov to 31 Dec 2025 and summer 17 Jun to 27 Oct 2026.
Field outlines stay as mapped by s2_fields.py; this adds per-field reference columns:
  s2_winter_check, s2_summer_check  (field median of max NDVI in the radar window > 0.40)

Run:  .venv/bin/python scripts/s2_check.py
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from scipy import ndimage as ndi

import s2_fields as S

ROOT = Path(__file__).resolve().parents[1]
FD = ROOT / "data" / "fields"
WINDOWS = {"winter": ("2025-11-01", "2025-12-31"), "summer": ("2026-06-17", "2026-10-27")}


def main():
    with rasterio.open(FD / "fields_labels.tif") as src:
        labels, transform = src.read(1), src.transform
        h, w = labels.shape
    df = pd.read_csv(FD / "fields.csv")
    ids = df.id.values
    for season, (s, e) in WINDOWS.items():
        p = FD / f"ndvi_max_{season}_radarwindow.tif"
        if p.exists():
            with rasterio.open(p) as src:
                nd = src.read(1)
        else:
            nd = S.season_max_ndvi(s, e, transform, w, h)
            S.save_tif(nd, transform, p)
        med = ndi.median(np.nan_to_num(nd, nan=-1), labels, ids)
        df[f"ndvi_{season}_check"] = np.round(med, 3)
        df[f"s2_{season}_check"] = med > S.GREEN
        print(season, s, e, "S2 farmed ha:", round(df.loc[df[f"s2_{season}_check"], "area_ha"].sum()))
    df.to_csv(FD / "fields.csv", index=False)


if __name__ == "__main__":
    main()
