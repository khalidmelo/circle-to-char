"""Export everything the web app needs into docs/data/.

  fields.geojson        field outlines (WGS84) with class, water, energy, straw, fronds, pivot flag, plant, each
                        field's own WorldCover tree cover, and the national run's spring check where a national field
                        matches (data/fields/national_flags.csv)
  overlays/*.png        NISAR HV per date, coherence per pair, soil moisture, Sentinel-2 NDVI,
                        reprojected to Web Mercator so they sit correctly on the map
  overlays.json         list of overlays with dates and lat/lon bounds
  timeseries.json       per-field HV, coherence, soil moisture over time
  summary.json          supply (out/supply_summary.json: totals low/central/high, pumping head, classification range,
                        radar + Sentinel-2 tier), validation, params (the deep dive's factors), soil_use (the straw
                        and fronds entries of model/params.json _soil_use: each char's soil-use status against
                        Puro.earth 2025 v2 Table 3.3; frond char is unmeasured, yet the siting credits fronds char
                        spread on fields), siting (one record per plant, with its feed mix: feed_straw, feed_fronds)
  cement.geojson

Checks, before anything is written: the gitignored label raster data/fields/fields_labels.tif must belong to
data/fields/fields_radar.csv (every id present, pixel count x pixel area = area_ha within 0.005 ha; the export
stops otherwise), and data/supply.csv must hold the same fields. timeseries.json is written only when the field ids
of data/fields/radar_timeseries.csv are a subset of the field ids; a stale time series is skipped with a warning and
the published timeseries.json is kept.

Overlays are rebuilt only from complete, current inputs: data/nisar (GCOV, GUNW, SME2) and the Sentinel-2
composites data/fields/ndvi_max_<season>.tif tagged ndvi=offset_corrected (older composites made from raw DNs
lack the tag). Otherwise the export stops before writing anything; --skip-overlays leaves the published
overlays and overlays.json as they are.

Run:  .venv/bin/python scripts/export_web.py [--skip-overlays]
"""
import argparse
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
NDVI_TAG = "offset_corrected"  # the tag scripts/s2_fields.py writes into composites from offset-corrected reflectance

sys.path.insert(0, str(ROOT / "model"))
sys.path.insert(0, str(ROOT / "scripts"))
from national_siting import persistence  # noqa: E402
from transfer_national_flags import check_labels  # noqa: E402  (label raster against the field table)

# Factors the deep dive uses (params.json also holds the national feedstocks), in the order the page lists them.
DEEP_DIVE_PARAMS = ("plant_sizes_t_dry", "min_load_fraction", "wheat_grain_yield_t_ha", "straw_t_dry_per_ha",
                    "collectable_fraction", "straw_dry_matter", "alfalfa_collectable_residue_t_ha",
                    "palms_per_ha", "palm_residue_kg_dry_per_palm", "palm_frond_dry_matter",
                    "irrigation_mm_winter_only", "irrigation_mm_summer_crop", "irrigation_mm_year_round",
                    "pivot_application_efficiency", "pumping_lift_m", "drawdown_m", "pivot_pressure_head_m",
                    "pump_wire_to_water_eff", "grid_kgco2e_per_kwh",
                    "diesel_water_kwh_per_litre", "diesel_kgco2e_per_litre", "road_circuity", "truck_kgco2e_per_tkm",
                    "char_yield_dry", "char_c_org", "h_c_org_straw", "palm_char_yield_dry", "palm_char_c_org",
                    "h_c_org_fronds", "soil_temp_c", "cement_retention")
PERSISTENCE = (("straw", "straw_char_persistence"), ("fronds", "fronds_char_persistence"))
SOIL_USE_FEEDS = ("straw", "fronds")  # the deep dive's feeds (model/params.json _soil_use also covers the national ones)


def deep_dive_params():
    """The deep dive's factors, plus the char persistence each feed's factors give (the factor that credits removal)."""
    raw = json.loads((ROOT / "model" / "params.json").read_text())
    out = {k: raw[k] for k in DEEP_DIVE_PARAMS if k in raw}
    by_level = {lv: {k: v[lv] for k, v in raw.items() if isinstance(v, dict) and lv in v} for lv in ("low", "central", "high")}
    keys = list(out)
    at = keys.index("soil_temp_c") + 1
    for feed, name in PERSISTENCE:
        pf = {lv: round(persistence(p, feed), 3) for lv, p in by_level.items()}
        pf["source"] = (f"derived: Puro.earth 2025 v2 Table 6.1, persistence = (M - a x H/C_org) / 100 with h_c_org_{feed} "
                        "at the soil temperature above (200 years); credited for char spread on fields and for char in "
                        "cement alike (rule 6.2.4)")
        out[name] = pf
        keys.insert(at, name)
        at += 1
    return {k: out[k] for k in keys}


def soil_use():
    """The straw and fronds entries of model/params.json _soil_use (stream, status, outlet, note): each char's soil-use
    status against Puro.earth 2025 v2 Table 3.3 (WBC-Agro limits). The page can say that the fronds share of the credit
    rests on a char not yet measured against them."""
    su = json.loads((ROOT / "model" / "params.json").read_text()).get("_soil_use") or {}
    return {f: su[f] for f in SOIL_USE_FEEDS if f in su}


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


def check_overlay_inputs():
    """Stop before anything is written if the overlays would be rebuilt from missing or stale inputs."""
    nd = ROOT / "data" / "nisar"
    problems = [f"data/nisar/{d} not found" for d in ("GCOV", "GUNW", "SME2") if not (nd / d).is_dir()]
    for season in CFG["seasons"]:
        p = ROOT / "data" / "fields" / f"ndvi_max_{season}.tif"
        if not p.exists():
            problems.append(f"{p.relative_to(ROOT)} not found")
            continue
        with rasterio.open(p) as src:
            if src.tags().get("ndvi") != NDVI_TAG:
                problems.append(f"{p.relative_to(ROOT)} is not tagged ndvi={NDVI_TAG} (an older composite from raw DNs)")
    if problems:
        raise SystemExit("Nothing exported: " + "; ".join(problems) + ". Provide current inputs, or pass "
                         "--skip-overlays to keep the published overlays.")


def export_overlays():
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
        overlays.append({"group": "Sentinel-2 greenness (ESA)", "date": season, "file": f"ndvi_{season}.png",
                         "bounds": png_overlay(p, f"ndvi_{season}.png", 0, 0.8, "YlGn"),
                         "legend": f"Maximum NDVI, {season} season"})
    (WEB / "overlays.json").write_text(json.dumps(overlays))
    print(len(overlays), "overlays")


def load_checked():
    """Read the field table, label raster, supply and time series, and check that they belong together. Stops before
    anything is written if the label raster or data/supply.csv does not match the field table; a time series with
    unknown field ids is dropped (timeseries.json is then left as published). Returns (labels, transform, crs,
    attrs, time series or None)."""
    fd = ROOT / "data" / "fields"
    radar = fd / "fields_radar.csv"
    table_path = radar if radar.exists() else fd / "fields.csv"
    table = pd.read_csv(table_path, usecols=["id", "area_ha"])
    with rasterio.open(fd / "fields_labels.tif") as src:
        lab, tf, crs = src.read(1), src.transform, src.crs
    check_labels(lab, tf, table, table_name=str(table_path.relative_to(ROOT)))
    attrs = pd.read_csv(ROOT / "data" / "supply.csv").set_index("id")
    chk = table.merge(attrs.area_ha.rename("area_supply"), left_on="id", right_index=True, how="outer")
    if len(chk) != len(table) or len(attrs) != len(table) or not np.allclose(chk.area_ha, chk.area_supply):
        raise SystemExit(f"data/supply.csv does not hold the fields of {table_path.relative_to(ROOT)}: re-run "
                         "model/supply.py. Nothing exported.")
    ts = None
    ts_p = fd / "radar_timeseries.csv"
    if ts_p.exists():
        ts = pd.read_csv(ts_p)
        unknown = np.setdiff1d(ts.field_id.unique(), table.id.values)
        if len(unknown):
            print(f"WARNING: {ts_p.relative_to(ROOT)} has {len(unknown)} field ids that are not in "
                  f"{table_path.relative_to(ROOT)} (e.g. {[int(i) for i in unknown[:5]]}): a stale time series. timeseries.json is "
                  "left as published.")
            ts = None
    return lab, tf, crs, attrs, ts


def main(skip_overlays=False):
    lab, lab_tf, lab_crs, attrs, ts = load_checked()
    if skip_overlays:
        print("overlays left as published (--skip-overlays)")
    else:
        check_overlay_inputs()
        export_overlays()

    # Field outlines
    fd = ROOT / "data" / "fields"
    radar = fd / "fields_radar.csv"
    if radar.exists():
        r = pd.read_csv(radar).set_index("id")
        attrs = attrs.join(r[[c for c in r.columns if c.startswith(("hv_peak", "coh_min", "sm_max", "s2_"))]], how="left")
    flags = fd / "national_flags.csv"
    if flags.exists():
        fl = pd.read_csv(flags).set_index("id")
        attrs = attrs.join(fl[["tree_frac"]], how="left")  # each field's own WorldCover tree cover
        # the national field's spring check, where one covers >= half the field
        fl = fl[fl.matched.astype(bool)]
        fl["spring_brown"] = fl.spring_brown.map({True: True, False: False, "True": True, "False": False}).astype(object)
        attrs = attrs.join(fl[["national_uid", "spring_brown", "ndvi_spring_median"]], how="left")
    assign = ROOT / "out" / "assignments_central_10kt.csv"
    if assign.exists():
        try:
            a = pd.read_csv(assign)
        except pd.errors.EmptyDataError:
            a = pd.DataFrame(columns=["field_id", "plant"])
        if "feed_t_dry" in a:  # a field split between two plants shows the one taking more of its feed
            a = a.sort_values(["feed_t_dry", "plant"], ascending=[False, True])
        a = a.drop_duplicates("field_id").set_index("field_id")[["plant"]]
        attrs = attrs.join(a.rename(columns={"plant": "plant_10kt"}), how="left")
    tr = Transformer.from_crs(lab_crs, 4326, always_xy=True).transform
    feats = []
    for geom, val in shapes(lab, mask=lab > 0, transform=lab_tf):
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

    # Time series (only when it belongs to the field table: load_checked)
    if ts is not None:
        ts = ts.dropna()
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
    summ["soil_use"] = soil_use()
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-overlays", action="store_true", help="keep docs/data/overlays.json and overlays/*.png as they are")
    main(ap.parse_args().skip_overlays)
