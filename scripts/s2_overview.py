"""Sentinel-2 overview of the Qassim study area.

Builds two NDVI composites (winter 2025/26 and summer 2026) from ESA Sentinel-2 L2A
via Microsoft Planetary Computer (anonymous access) and saves a quick-look PNG,
so we can choose the radar crop window and see the centre-pivot circles.

Run:  .venv/bin/python scripts/s2_overview.py
"""
import sys
from pathlib import Path

import numpy as np
import planetary_computer
import pystac_client
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import transform_bounds
from rasterio.windows import from_bounds
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "s2"
OUT.mkdir(parents=True, exist_ok=True)

# Wide first look around Buraydah / Unayzah and the pivot schemes to the east.
BBOX = [float(v) for v in (sys.argv[1].split(",") if len(sys.argv) > 1 else "43.4,25.8,44.6,26.8".split(","))]
SEASONS = {"winter": "2025-12-01/2026-02-28", "summer": "2026-07-01/2026-09-30"}
RES = 60  # metres, overview only


def ndvi_composite(datetime_range):
    cat = pystac_client.Client.open(
        "https://planetarycomputer.microsoft.com/api/stac/v1",
        modifier=planetary_computer.sign_inplace,
    )
    items = list(
        cat.search(
            collections=["sentinel-2-l2a"],
            bbox=BBOX,
            datetime=datetime_range,
            query={"eo:cloud_cover": {"lt": 10}},
        ).items()
    )
    print(f"  {len(items)} scenes")
    # Common output grid in EPSG:4326 at ~RES m
    width = int((BBOX[2] - BBOX[0]) * 111320 * np.cos(np.radians(26.3)) / RES)
    height = int((BBOX[3] - BBOX[1]) * 110540 / RES)
    stack = []
    for it in sorted(items, key=lambda i: i.properties["eo:cloud_cover"])[:int(sys.argv[2]) if len(sys.argv) > 2 else 40]:
        bands = {}
        for b in ("B04", "B08"):
            href = it.assets[b].href
            with rasterio.open(href) as src:
                b_utm = transform_bounds("EPSG:4326", src.crs, *BBOX)
                win = from_bounds(*b_utm, transform=src.transform)
                arr = src.read(
                    1,
                    window=win,
                    out_shape=(height, width),
                    boundless=True,
                    fill_value=0,
                    resampling=Resampling.average,
                ).astype("float32")
            bands[b] = arr
        red, nir = bands["B04"], bands["B08"]
        valid = (red > 0) & (nir > 0)
        nd = np.where(valid, (nir - red) / (nir + red + 1e-6), np.nan)
        stack.append(nd)
    # Maximum NDVI over the season: a field farmed at any time shows up.
    return np.nanmax(np.stack(stack), axis=0)


def main():
    results = {}
    for name, rng in SEASONS.items():
        print(name, rng)
        results[name] = ndvi_composite(rng)
        np.save(OUT / f"ndvi_max_{name}.npy", results[name])
    fig, axes = plt.subplots(1, 2, figsize=(16, 7))
    for ax, (name, arr) in zip(axes, results.items()):
        ax.imshow(arr, vmin=0, vmax=0.8, cmap="YlGn", extent=[BBOX[0], BBOX[2], BBOX[1], BBOX[3]])
        ax.set_title(f"Max NDVI, {name} ({SEASONS[name]})")
        ax.set_xlabel("lon")
        ax.set_ylabel("lat")
        ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT / f"ndvi_overview_{len(sys.argv)}.png", dpi=110)
    print("saved", OUT / f"ndvi_overview_{len(sys.argv)}.png")


if __name__ == "__main__":
    sys.exit(main())
