"""Find every agricultural region in Saudi Arabia from ESA WorldCover 2021 (10 m land cover).

WorldCover cropland (class 40) and tree cover (class 10, mostly date palm oases in the arid
interior) are sampled at ~200 m, clipped to Saudi Arabia, grouped into clusters, and each
cluster is cut into processing boxes of at most ~0.6 x 0.6 degrees.

Output: data/national/regions.json  (one entry per box: id, name hint, bbox, cropland_ha, tree_ha)
        data/national/regions_preview.png

Run:  .venv/bin/python scripts/national_regions.py
"""
import json
from pathlib import Path

import matplotlib
import numpy as np
import planetary_computer
import pystac_client
import rasterio
import requests
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT
from scipy import ndimage as ndi
from shapely.geometry import shape

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "national"
OUT.mkdir(parents=True, exist_ok=True)

KSA = [34.4, 16.3, 55.8, 32.3]
STEP = 0.002  # degrees, ~200 m
MIN_CROP_HA = 1500
MAX_BOX = 0.6

NE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson"


def saudi_shape():
    p = OUT / "ne_50m_countries.geojson"
    if not p.exists():
        p.write_bytes(requests.get(NE, timeout=120).content)
    for f in json.loads(p.read_text())["features"]:
        if f["properties"].get("ADM0_A3") == "SAU":
            return shape(f["geometry"])
    raise SystemExit("Saudi Arabia not found in Natural Earth file")


def main():
    w = int((KSA[2] - KSA[0]) / STEP)
    h = int((KSA[3] - KSA[1]) / STEP)
    tf = from_origin(KSA[0], KSA[3], STEP, STEP)
    lc = np.zeros((h, w), dtype="uint8")
    cat = pystac_client.Client.open("https://planetarycomputer.microsoft.com/api/stac/v1",
                                    modifier=planetary_computer.sign_inplace)
    items = list(cat.search(collections=["esa-worldcover"], bbox=KSA,
                            query={"esa_worldcover:product_version": {"eq": "2.0.0"}}).items())
    print(len(items), "WorldCover tiles")
    for it in items:
        with rasterio.open(it.assets["map"].href) as src:
            with WarpedVRT(src, crs="EPSG:4326", transform=tf, width=w, height=h,
                           resampling=Resampling.nearest) as vrt:
                a = vrt.read(1)
        lc = np.where(a > 0, a, lc)
    ksa = rasterize([(saudi_shape(), 1)], out_shape=(h, w), transform=tf, dtype="uint8").astype(bool)
    crop = (lc == 40) & ksa
    tree = (lc == 10) & ksa
    # Trees in the arid interior are mostly palm oases; exclude the southwest highlands and coasts later by inspection.
    px_ha = (STEP * 111.32) * (STEP * 110.57) * 100 * np.cos(np.radians(24))
    farm = crop | tree
    grown = ndi.binary_dilation(farm, iterations=5)  # ~1 km
    lab, n = ndi.label(grown)
    boxes = []
    for i, sl in enumerate(ndi.find_objects(lab), start=1):
        m = (lab[sl] == i)
        c_ha = float((crop[sl] & m).sum() * px_ha)
        t_ha = float((tree[sl] & m).sum() * px_ha)
        if c_ha + t_ha < MIN_CROP_HA:
            continue
        r0, r1, c0, c1 = sl[0].start, sl[0].stop, sl[1].start, sl[1].stop
        lon0, lat1 = tf * (c0, r0)
        lon1, lat0 = tf * (c1, r1)
        # Cut large clusters into tiles of at most MAX_BOX degrees
        nx = int(np.ceil((lon1 - lon0) / MAX_BOX))
        ny = int(np.ceil((lat1 - lat0) / MAX_BOX))
        for ix in range(nx):
            for iy in range(ny):
                b = [lon0 + ix * (lon1 - lon0) / nx, lat0 + iy * (lat1 - lat0) / ny,
                     lon0 + (ix + 1) * (lon1 - lon0) / nx, lat0 + (iy + 1) * (lat1 - lat0) / ny]
                cc0, rr1 = ~tf * (b[0], b[1])
                cc1, rr0 = ~tf * (b[2], b[3])
                sub = (slice(int(rr0), int(np.ceil(rr1))), slice(int(cc0), int(np.ceil(cc1))))
                cs = float(crop[sub].sum() * px_ha)
                ts_ = float(tree[sub].sum() * px_ha)
                if cs + ts_ < MIN_CROP_HA / 2:
                    continue
                boxes.append({"bbox": [round(v, 3) for v in b], "cropland_ha": round(cs), "tree_ha": round(ts_)})
    boxes.sort(key=lambda b: -(b["cropland_ha"] + b["tree_ha"]))
    for k, b in enumerate(boxes, start=1):
        b["id"] = f"R{k:02d}"
        b["center"] = [round((b["bbox"][1] + b["bbox"][3]) / 2, 3), round((b["bbox"][0] + b["bbox"][2]) / 2, 3)]
    (OUT / "regions.json").write_text(json.dumps(boxes, indent=1))
    tot_c = sum(b["cropland_ha"] for b in boxes)
    tot_t = sum(b["tree_ha"] for b in boxes)
    print(f"{len(boxes)} boxes; cropland {tot_c:,.0f} ha, tree cover {tot_t:,.0f} ha inside boxes; "
          f"national cropland {crop.sum() * px_ha:,.0f} ha, tree {tree.sum() * px_ha:,.0f} ha")
    for b in boxes:
        print(b["id"], b["center"], b["bbox"], b["cropland_ha"], b["tree_ha"])

    fig, ax = plt.subplots(figsize=(12, 10))
    show = np.zeros((h, w, 3)) + 0.96
    show[crop] = [0.85, 0.55, 0.1]
    show[tree] = [0.1, 0.55, 0.25]
    ax.imshow(show, extent=[KSA[0], KSA[2], KSA[1], KSA[3]])
    for b in boxes:
        x0, y0, x1, y1 = b["bbox"]
        ax.add_patch(plt.Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, color="k", lw=0.8))
        ax.text(x0, y1, b["id"], fontsize=7)
    ax.set_title("ESA WorldCover 2021: cropland (orange), tree cover (green), processing boxes")
    fig.tight_layout()
    fig.savefig(OUT / "regions_preview.png", dpi=110)


if __name__ == "__main__":
    main()
