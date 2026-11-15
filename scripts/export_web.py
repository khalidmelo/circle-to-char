"""Export everything the web app needs into web/data/.

  fields.geojson        field outlines (WGS84) with class, water, energy, residue, plant
  overlays/*.png        NISAR HV per date, coherence per pair, soil moisture, Sentinel-2 NDVI,
                        reprojected to Web Mercator so they sit correctly on the map
  overlays.json         list of overlays with dates and lat/lon bounds
  timeseries.json       per-field HV, coherence, soil moisture over time
  summary.json          totals (low/central/high), validation, siting results, sources
  plants.geojson, cement.geojson

Run:  .venv/bin/python scripts/export_web.py
"""
import json
import sys
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import rasterio
from PIL import Image
from rasterio.features import shapes
from rasterio.warp import Resampling, calculate_default_transform, reproject, transform_bounds
from shapely.geometry import mapping, shape
from shapely.ops import transform as shp_transform
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "config.json").read_text())
WEB = ROOT / "docs" / "data"
(WEB / "overlays").mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT / "model"))
from national_siting import persistence  # noqa: E402

# Factors the deep dive uses (params.json also holds the national feedstocks), in the order the page lists them.
DEEP_DIVE_PARAMS = ("plant_sizes_t_dry", "min_load_fraction", "wheat_grain_yield_t_ha", "straw_t_dry_per_ha",
                    "collectable_fraction", "straw_dry_matter", "alfalfa_collectable_residue_t_ha",
                    "irrigation_mm_winter_only", "irrigation_mm_summer_crop", "irrigation_mm_year_round",
                    "pivot_application_efficiency", "pumping_lift_m", "pump_wire_to_water_eff", "grid_kgco2e_per_kwh",
                    "diesel_water_kwh_per_litre", "diesel_kgco2e_per_litre", "road_circuity", "truck_kgco2e_per_tkm",
                    "char_yield_dry", "char_c_org", "h_c_org_straw", "soil_temp_c", "cement_retention")


def deep_dive_params():
    """The deep dive's factors, plus the straw-char persistence they give (the factor that credits removal)."""
    raw = json.loads((ROOT / "model" / "params.json").read_text())
    out = {k: raw[k] for k in DEEP_DIVE_PARAMS if k in raw}
    by_level = {lv: {k: v[lv] for k, v in raw.items() if isinstance(v, dict) and lv in v} for lv in ("low", "central", "high")}
    pf = {lv: round(persistence(p, "straw"), 3) for lv, p in by_level.items()}
    pf["source"] = ("derived: Puro.earth 2025 v2 Table 6.1, persistence = (M - a x H/C_org) / 100 at the soil temperature "
                    "above (200 years); credited for char spread on fields and for char in cement alike (rule 6.2.4)")
    keys = list(out)
    keys.insert(keys.index("soil_temp_c") + 1, "straw_char_persistence")
    out["straw_char_persistence"] = pf
    return {k: out[k] for k in keys}


def png_overlay(src_path, out_name, vmin, vmax, cmap, to_db=False, max_px=1600, unit_range=False):
    with rasterio.open(src_path) as src:
        dst_crs = "EPSG:3857"
        tf, w, h = calculate_default_transform(src.crs, dst_crs, src.width, src.height, *src.bounds)
        scale = max(1, max(w, h) / max_px)
        w2, h2 = int(w / scale), int(h / scale)
        tf2 = tf * tf.scale(w / w2, h / h2)
        arr = np.full((h2, w2), np.nan, dtype="float32")
        reproject(rasterio.band(src, 1), arr, src_nodata=src.nodata, dst_transform=tf2, dst_crs=dst_crs,
                  dst_nodata=np.nan, resampling=Resampling.average)
        left, top = tf2 * (0, 0)
        right, bottom = tf2 * (w2, h2)
    if to_db:
        arr = 10 * np.log10(np.where(arr > 0, arr, np.nan))
    if unit_range:  # coherence / soil moisture: values outside 0..1 are fill
        arr = np.where((arr >= 0) & (arr <= 1), arr, np.nan)
    if np.isnan(arr).mean() > 0.6:
        return None
    norm = np.clip((arr - vmin) / (vmax - vmin), 0, 1)
    rgba = (matplotlib.colormaps[cmap](norm) * 255).astype("uint8")
    rgba[..., 3] = np.where(np.isfinite(arr), 255, 0)
    Image.fromarray(rgba).save(WEB / "overlays" / out_name, optimize=True)
    lon0, lat0, lon1, lat1 = transform_bounds("EPSG:3857", "EPSG:4326", left, bottom, right, top)
    return [[lat0, lon0], [lat1, lon1]]


def main():
    overlays = []
    nd = ROOT / "data" / "nisar"
    for p in sorted((nd / "GCOV").glob("*_HVHV.tif")):
        overlays.append({"group": "NISAR HV backscatter", "date": p.name[:10], "file": f"hv_{p.name[:10]}.png",
                         "bounds": png_overlay(p, f"hv_{p.name[:10]}.png", -28, -12, "gray", to_db=True),
                         "legend": "HV gamma0, -28 dB (dark, bare) to -12 dB (bright, crop canopy)"})
    for p in sorted((nd / "GUNW").glob("*_coherenceMagnitude.tif")):
        if "__wrappedInterferogram" not in p.name:  # keep the 20 m layer only
            continue
        d = p.name[:10]
        b = png_overlay(p, f"coh_{d}.png", 0, 1, "magma", max_px=1000, unit_range=True)
        if b:
            overlays.append({"group": "NISAR 12-day coherence", "date": d, "file": f"coh_{d}.png", "bounds": b,
                             "legend": "Coherence 0 (surface changed) to 1 (unchanged). Note: sand itself decorrelates here (desert median about 0.5)"})
    for p in sorted((nd / "SME2").glob("*_soilMoisture.tif")):
        d = p.name[:10]
        b = png_overlay(p, f"sm_{d}.png", 0, 0.4, "Blues", unit_range=True)
        if b:
            overlays.append({"group": "NISAR soil moisture", "date": d, "file": f"sm_{d}.png", "bounds": b,
                             "legend": "Volumetric soil moisture 0 to 0.4 m3/m3 (200 m)"})
    for season in CFG["seasons"]:
        p = ROOT / "data" / "fields" / f"ndvi_max_{season}.tif"
        if p.exists():
            overlays.append({"group": "Sentinel-2 greenness (ESA)", "date": season, "file": f"ndvi_{season}.png",
                             "bounds": png_overlay(p, f"ndvi_{season}.png", 0, 0.8, "YlGn"),
                             "legend": f"Maximum NDVI, {season} season"})
    (WEB / "overlays.json").write_text(json.dumps(overlays))
    print(len(overlays), "overlays")

    # Field outlines
    fd = ROOT / "data" / "fields"
    radar = fd / "fields_radar.csv"
    attrs = pd.read_csv(ROOT / "data" / "supply.csv").set_index("id")
    if radar.exists():
        r = pd.read_csv(radar).set_index("id")
        attrs = attrs.join(r[[c for c in r.columns if c.startswith(("hv_peak", "coh_min", "sm_max", "s2_"))]], how="left")
    assign = ROOT / "out" / "assignments_central_10kt.csv"
    if assign.exists():
        attrs = attrs.join(pd.read_csv(assign).set_index("field_id").rename(columns={"plant": "plant_10kt"}), how="left")
    with rasterio.open(fd / "fields_labels.tif") as src:
        lab = src.read(1)
        tr = Transformer.from_crs(src.crs, 4326, always_xy=True).transform
        feats = []
        for geom, val in shapes(lab, mask=lab > 0, transform=src.transform):
            val = int(val)
            if val not in attrs.index:
                continue
            g = shp_transform(tr, shape(geom).simplify(15))
            props = {k: (None if (isinstance(v, float) and np.isnan(v)) else (round(v, 3) if isinstance(v, float) else (bool(v) if isinstance(v, (np.bool_,)) else v)))
                     for k, v in attrs.loc[val].items()}
            props["id"] = val
            feats.append({"type": "Feature", "geometry": mapping(g), "properties": props})
    (WEB / "fields.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}, default=str))
    print(len(feats), "field polygons")

    # Time series
    ts_p = fd / "radar_timeseries.csv"
    if ts_p.exists():
        ts = pd.read_csv(ts_p).dropna()
        # Coherence appears twice per date (80 m and 20 m files, read in that order): keep the 20 m value.
        ts = ts.drop_duplicates(subset=["field_id", "date", "layer"], keep="last")
        key = {"HVHV": "hv", "HHHH": "hh", "coherenceMagnitude": "coh", "soilMoisture": "sm"}
        out = {}
        for (fid, layer), g in ts.groupby(["field_id", "layer"]):
            out.setdefault(str(fid), {})[key[layer]] = [[d, round(v, 3)] for d, v in zip(g.date, g.value)]
        (WEB / "timeseries.json").write_text(json.dumps(out, separators=(",", ":")))

    # Summary, validation, siting
    summ = {"supply": json.loads((ROOT / "out" / "supply_summary.json").read_text())}
    v = ROOT / "out" / "validation.json"
    summ["validation"] = json.loads(v.read_text()) if v.exists() else None
    summ["params"] = deep_dive_params()
    summ["siting"] = {}
    for f in sorted((ROOT / "out").glob("plants_*.csv")):
        tag = f.stem.replace("plants_", "")
        try:
            df = pd.read_csv(f)
        except pd.errors.EmptyDataError:
            df = pd.DataFrame()
        summ["siting"][tag] = json.loads(df.to_json(orient="records")) if len(df) else []
    (WEB / "summary.json").write_text(json.dumps(summ, indent=1, default=str))

    c = ROOT / "data" / "cement" / "saudi_cement.csv"
    if c.exists():
        df = pd.read_csv(c)
        if "status" in df:
            df = df[df.status != "Closed"]  # the map shows operating plants only
        feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [r.lon, r.lat]},
                  "properties": {k: (None if pd.isna(r[k]) else r[k]) for k in df.columns if k not in ("lon", "lat")}}
                 for _, r in df.iterrows()]
        (WEB / "cement.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}, default=str))
    print("done")


if __name__ == "__main__":
    main()
