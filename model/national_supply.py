"""National supply: combine every region's radar field table into one table and totals.

Classes per field (radar): palm_grove, winter_only (wheat), summer_only, wheat_rotation, year_round,
idle (radar saw both seasons and neither was above the desert threshold), partly_seen_active /
partly_seen_inactive (the radar observed only one season, active or not), radar_unusable (covered but no
season classifiable, e.g. rejected by --qc), unseen (outside the radar swath).
Per field (low/central/high): irrigation water pumped, pumping electricity, CO2 (grid/diesel),
collectable wheat straw, palm fronds. Manure points are added by model/manure.py if present.

A season counts as observed for a field only if the region has radar dates and a desert threshold for
it and the field had valid backscatter on one of those dates; an unobserved season is unknown, never
'not farmed'. By default (quality check; --no-qc turns it off) a region's season is also left unobserved when its desert background is bright
on every date (radio interference, or non-sand ground) or its threshold exceeds 6 dB.

Output: data/national/fields_national.csv, out/national_summary.json
Usage:  .venv/bin/python model/national_supply.py [--no-qc]   (the quality check is on by default)
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import shapely
from shapely.geometry import Point, box, shape

ROOT = Path(__file__).resolve().parents[1]
RHO_G = 1000 * 9.81
LV = ("low", "central", "high")
SEASONS = ("winter", "summer")
BG_MAX_DB, THR_MAX_DB = -21.0, 6.0  # --qc: sand desert is about -23 to -27 dB in HV
CLASSES = ("winter_only", "wheat_rotation", "summer_only", "year_round", "palm_grove", "idle",
           "partly_seen_active", "partly_seen_inactive", "radar_unusable", "unseen")
QC_REJECTED = {}  # season -> regions whose season the quality check left unobserved (filled by load_fields)


def P():
    raw = json.loads((ROOT / "model" / "params.json").read_text())
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def tri(s):
    """A True/False column that may have gaps, as object dtype: True, False or NaN."""
    return s.map({True: True, False: False, "True": True, "False": False}).astype(object)


def season_ok(meta, se, qc):
    """Can this region's radar classify the season? (threshold exists; with qc, also the quality check)"""
    thr = meta.get("validation", {}).get("thresholds_db", {})
    if se not in thr:
        return False
    if not qc:
        return True
    bg = [v for d, v in meta.get("bg_median_db", {}).items() if (d < "2026-03") == (se == "winter")]
    return any(v <= BG_MAX_DB for v in bg) and thr[se] <= THR_MAX_DB


def load_fields(qc=False):
    frames, skipped = [], {}
    for f in sorted((ROOT / "data" / "regions").glob("R*/fields_radar.csv")):
        d = pd.read_csv(f, low_memory=False)
        if not len(d):
            continue
        meta = json.loads((f.parent / "meta.json").read_text())
        for se in SEASONS:
            ok = season_ok(meta, se, qc)
            if not ok and se in meta.get("validation", {}).get("thresholds_db", {}):
                skipped.setdefault(se, []).append(f.parent.name)
            # observed = classifiable season and a valid radar value on the field; otherwise unknown (NaN)
            seen = d[f"hv_above_desert_{se}"].notna() & ok
            d[f"{se}_active"] = tri(d[f"{se}_active"]).where(seen, np.nan)
        for c in ("s2_winter_active", "s2_summer_active", "s2_winter_check", "spring_brown"):
            if c in d:
                d[c] = tri(d[c])
        frames.append(d)
    QC_REJECTED.clear()
    QC_REJECTED.update(skipped)
    for se, rids in skipped.items():
        print(f"quality check: {se} left unobserved in {len(rids)} regions: {' '.join(rids)}")
    df = pd.concat(frames, ignore_index=True)
    wa, sa = df.winter_active, df.summer_active
    # palms are evergreen: tree cover and active in every season the radar observed (at least one)
    df["palm_grove"] = ((df.tree_frac >= 0.3) & (wa.notna() | sa.notna())
                        & (wa.isna() | wa.eq(True)) & (sa.isna() | sa.eq(True)))
    # Neighbouring boxes share edges and boxes from different clusters can overlap, so a field near an
    # edge can be mapped by two regions. Each field belongs to the first processed region (by rank) whose
    # box contains its centre; copies held by any other region are dropped. Fields whose centre is in no
    # box stay with the region that mapped them.
    bbox = {r["id"]: r["bbox"] for r in json.loads((ROOT / "data" / "national" / "regions.json").read_text())}
    owner = df.region.copy()
    found = np.zeros(len(df), dtype=bool)
    for rid in sorted(df.region.unique(), key=lambda r: int(r[1:])):
        x0, y0, x1, y1 = bbox[rid]
        inside = ~found & df.lon.between(x0, x1).values & df.lat.between(y0, y1).values
        owner[inside] = rid
        found |= inside
    dup = owner != df.region
    if dup.any():
        print(f"dropped {int(dup.sum())} fields ({df[dup].area_ha.sum():,.0f} ha) mapped by two regions")
    df = df.loc[~dup].reset_index(drop=True)
    df["uid"] = df.region + "_" + df.id.astype(str)
    return df


def admin_regions(df):
    """Saudi ADM1 region of each field centre (geoBoundaries). Centres in no ADM1 polygon: 'abroad' if inside a
    neighbouring country (Natural Earth 1:50m) and more than 1 km from Saudi ADM1 land, else the nearest ADM1
    region (coastline and boundary simplification)."""
    gj = json.loads((ROOT / "data" / "national" / "sau_adm1.geojson").read_text())
    df["admin"] = "outside"
    polys = []
    for f in gj["features"]:
        g = shape(f["geometry"])
        polys.append((f["properties"]["shapeName"], g))
        inside = shapely.contains_xy(g, df.lon.values, df.lat.values)
        df.loc[inside, "admin"] = f["properties"]["shapeName"]
    out = df.index[df.admin == "outside"]
    if len(out):
        ne = json.loads((ROOT / "data" / "national" / "ne_50m_countries.geojson").read_text())
        near = [(f["properties"].get("ADM0_A3"), shape(f["geometry"])) for f in ne["features"]
                if f["properties"].get("ADM0_A3") != "SAU" and shape(f["geometry"]).intersects(box(33, 15, 57, 34))]
        ksa = shapely.unary_union([g for _, g in polys])
        df["country"] = "SAU"
        for i in out:
            pt = Point(df.at[i, "lon"], df.at[i, "lat"])
            other = next((c for c, g in near if g.contains(pt)), None)
            if other and ksa.distance(pt) * 108 > 1.0:  # ~km at these latitudes
                df.at[i, "admin"], df.at[i, "country"] = "abroad", other
            else:
                df.at[i, "admin"] = min(polys, key=lambda p: p[1].distance(pt))[0]
    return df


def classify(r):
    w, s = r.winter_active, r.summer_active  # True / False / NaN (season not observed)
    if not r.radar_seen:
        return "unseen"  # outside the radar swath (no valid backscatter on any date)
    if pd.isna(w) and pd.isna(s):
        return "radar_unusable"  # covered, but no season classifiable (no threshold, or rejected by --qc)
    if r.palm_grove:
        return "palm_grove"
    if pd.isna(w) or pd.isna(s):
        # one season unknown: not idle, and not split into wheat or fodder
        return "partly_seen_active" if (w == True or s == True) else "partly_seen_inactive"  # noqa: E712
    if w and s:
        # brown in late spring (Sentinel-2) = wheat harvested, then a summer crop
        return "wheat_rotation" if r.get("spring_brown") == True else "year_round"  # noqa: E712 (NaN-safe)
    if w:
        return "winter_only"
    if s:
        return "summer_only"
    return "idle"


def flows(df, p, eff_override=None, off=None):
    """Per-field irrigation water, pumping electricity, CO2 (grid/diesel), summer pumping energy, wheat straw and
    palm fronds at low/central/high, added as columns (water_m3_<lvl>, ...); needs df['class'] and df['admin'].
    eff_override: pivot application efficiency to use instead of params (a number, or a {low, central, high} dict;
    the low estimate uses the high efficiency, as in params). Returns df."""
    if off is None:
        off = json.loads((ROOT / "data" / "national" / "official_2024.json").read_text())
    if eff_override is not None:
        p = p | {"pivot_application_efficiency": eff_override if isinstance(eff_override, dict)
                 else {lv: eff_override for lv in LV}}
    key = df.admin.map({k: v["key"] for k, v in off["regions"].items()}).fillna("_fallback")
    key = np.where((key == "Riyadh") & (df.lat < 21.5), "WadiDawasir", key)
    shield = pd.Series(key).isin(["Makkah", "Madinah", "Asir", "Jazan", "Najran", "Al-Baha"]).values
    lifts = off["lift_m"]
    df["lift_key"] = [k if k in lifts else "_fallback" for k in key]
    df["shield"] = shield
    m2 = df.area_ha * 1e4
    cls = df["class"]
    # partly_seen fields: water for the season the radar saw active only (a lower bound)
    part_s = (cls == "partly_seen_active") & df.summer_active.eq(True)
    part_w = (cls == "partly_seen_active") & df.winter_active.eq(True)
    for lvl, eff, lift in (("low", "high", "low"), ("central", "central", "central"), ("high", "low", "high")):
        win, smr, yr = (p["irrigation_mm_winter_only"][lvl], p["irrigation_mm_summer_crop"][lvl],
                        p["irrigation_mm_year_round"][lvl])
        conds = [cls == "winter_only", cls == "summer_only", cls == "wheat_rotation",
                 cls.isin(["year_round", "palm_grove"]), part_s, part_w]
        mm = pd.Series(np.select(conds, [win, smr, win + smr, yr, smr, win], 0.0), index=df.index)
        # summer share of pumping energy (Jun-Sep coincides with the grid's air-conditioning peak)
        summer_share = pd.Series(np.select(conds, [0.0, 1.0, smr / (win + smr), 0.5, 1.0, 0.0], 0.0), index=df.index)
        water = mm / 1000 * m2 / p["pivot_application_efficiency"][eff]
        lift_m = df.lift_key.map(lambda k: lifts[k][lift])
        work = np.where(df.shield, np.nan, water * RHO_G * lift_m / 3.6e6)
        df[f"water_m3_{lvl}"] = water.round()
        df[f"elec_kwh_{lvl}"] = (work / p["pump_wire_to_water_eff"][lvl]).round()
        df[f"co2_t_grid_{lvl}"] = (df[f"elec_kwh_{lvl}"] * p["grid_kgco2e_per_kwh"][lvl] / 1000).round(2)
        df[f"co2_t_diesel_{lvl}"] = (work / p["diesel_water_kwh_per_litre"][lvl] * p["diesel_kgco2e_per_litre"][lvl] / 1000).round(2)
        df[f"elec_kwh_summer_{lvl}"] = (df[f"elec_kwh_{lvl}"] * summer_share).round()
        df[f"straw_t_dry_{lvl}"] = (df["class"].isin(["winter_only", "wheat_rotation"]) * df.area_ha * p["straw_t_dry_per_ha"][lvl]).round(1)
        if "palms_per_ha" in p and p["palms_per_ha"][lvl] is not None:
            df[f"fronds_t_dry_{lvl}"] = ((df["class"] == "palm_grove") * df.area_ha * p["palms_per_ha"][lvl]
                                         * p["palm_residue_kg_dry_per_palm"][lvl] / 1000).round(1)
        else:
            df[f"fronds_t_dry_{lvl}"] = 0.0
    return df


def main():
    p = P()
    qc = "--no-qc" not in sys.argv[1:]
    df = admin_regions(load_fields(qc))
    out_ = df.admin == "abroad"
    outside_ha = float(df[out_].area_ha.sum())
    if out_.any():
        by_c = df[out_].groupby("country").area_ha.sum().round().to_dict()
        print(f"dropped {int(out_.sum())} fields ({outside_ha:,.0f} ha) in neighbouring countries: {by_c}")
        df = df.loc[~out_].reset_index(drop=True)
    df = df.drop(columns=["country"], errors="ignore")
    df["class"] = df.apply(classify, axis=1)
    both = df.winter_active.eq(True) & df.summer_active.eq(True) & ~df.palm_grove
    nosp = both & (df.spring_brown.isna() if "spring_brown" in df else True)
    if nosp.any():
        print(f"spring check missing for {int(nosp.sum())} two-season fields ({df[nosp].area_ha.sum():,.0f} ha), counted as year-round")
    off = json.loads((ROOT / "data" / "national" / "official_2024.json").read_text())
    df = flows(df, p, off=off)
    out = ROOT / "data" / "national"
    df.to_csv(out / "fields_national.csv", index=False)

    part = df["class"].str.startswith("partly_seen")
    farmed = df.winter_active.eq(True) | df.summer_active.eq(True)
    summ = {"regions_done": int(df.region.nunique()), "fields": int(len(df)), "quality_check": qc,
            "quality_check_rule": f"season left unobserved if the desert background is above {BG_MAX_DB} dB on every "
                                  f"date or the threshold exceeds {THR_MAX_DB} dB" if qc else None,
            "quality_check_rejected": {se: sorted(r, key=lambda x: int(x[1:])) for se, r in QC_REJECTED.items()},
            "field_ha": round(float(df.area_ha.sum())),
            "farmed_ha": round(float(df[farmed].area_ha.sum())),
            "area_ha_by_class": df.groupby("class").area_ha.sum().round().to_dict(),
            # farmed by season = radar active; fields where that season was not observed are counted apart
            "active_ha": {se: round(float(df[df[f"{se}_active"].eq(True)].area_ha.sum())) for se in SEASONS},
            "season_not_observed_ha": {se: round(float(df[part & df[f"{se}_active"].isna()].area_ha.sum())) for se in SEASONS},
            "outside_saudi_dropped_ha": round(outside_ha)}
    for k in ("water_m3", "elec_kwh", "elec_kwh_summer", "co2_t_grid", "co2_t_diesel", "straw_t_dry", "fronds_t_dry"):
        summ[k] = {l: float(np.nansum(df[f"{k}_{l}"])) for l in LV}
    # peak-season pumping load, averaged over Jun-Sep (122 days)
    summ["summer_pumping_avg_mw"] = {l: round(summ["elec_kwh_summer"][l] / (122 * 24) / 1000, 1) for l in LV}
    by = df.groupby("region").agg(lon=("lon", "mean"), lat=("lat", "mean"), fields=("uid", "count"), field_ha=("area_ha", "sum"),
                                  water_m3=("water_m3_central", "sum"), elec_kwh=("elec_kwh_central", "sum"),
                                  straw_t=("straw_t_dry_central", "sum"), fronds_t=("fronds_t_dry_central", "sum"))
    for c in CLASSES:
        by[f"{c}_ha"] = df[df["class"] == c].groupby("region").area_ha.sum()
    by["farmed_ha"] = df[farmed].groupby("region").area_ha.sum()
    for se in SEASONS:
        by[f"active_{se}_ha"] = df[df[f"{se}_active"].eq(True)].groupby("region").area_ha.sum()
    by = by.fillna(0).round(1)
    by.to_csv(ROOT / "out" / "national_by_region.csv")
    # Comparison with official 2024 statistics by administrative region
    rows = []
    for name, o in off["regions"].items():
        d = df[df.admin == name]
        palms = {l: float((d["class"] == "palm_grove").mul(d.area_ha).sum() * json.loads((ROOT / "model" / "params.json").read_text())["palms_per_ha"][l]) for l in LV}
        rows.append({"region": o["key"], "fields": int(len(d)), "radar_seen_ha": round(d[d["class"] != "unseen"].area_ha.sum()),
                     "radar_partly_seen_ha": round(d[d["class"].str.startswith("partly_seen")].area_ha.sum()),
                     "radar_unusable_ha": round(d[d["class"] == "radar_unusable"].area_ha.sum()),
                     "radar_winter_only_ha": round(d[d["class"] == "winter_only"].area_ha.sum()),
                     "radar_wheat_ha": round(d[d["class"].isin(["winter_only", "wheat_rotation"])].area_ha.sum()), "gastat_wheat_ha": o["wheat_ha"],
                     "radar_year_round_ha": round(d[d["class"] == "year_round"].area_ha.sum()), "gastat_fodder_ha": o["fodder_ha"],
                     "radar_palm_ha": round(d[d["class"] == "palm_grove"].area_ha.sum()), "palms_est_low": round(palms["low"]),
                     "palms_est_high": round(palms["high"]), "gastat_palms": o["date_palms"],
                     "water_m3_central": round(float(d.water_m3_central.sum())), "water_m3_low": round(float(d.water_m3_low.sum())),
                     "water_m3_high": round(float(d.water_m3_high.sum())), "mewa_agri_groundwater_m3": o["agri_groundwater_m3"]})
    cmp_ = pd.DataFrame(rows)
    cmp_.to_csv(ROOT / "out" / "national_vs_official.csv", index=False)
    summ["vs_official"] = {"radar_winter_only_ha": int(cmp_.radar_winter_only_ha.sum()), "radar_wheat_ha": int(cmp_.radar_wheat_ha.sum()),
                           "gastat_wheat_ha": off["national"]["wheat_ha"],
                           "radar_year_round_ha": int(cmp_.radar_year_round_ha.sum()), "gastat_fodder_ha": off["national"]["fodder_ha"],
                           "palms_est": [int(cmp_.palms_est_low.sum()), int(cmp_.palms_est_high.sum())], "gastat_palms": off["national"]["date_palms"],
                           "water_m3": [int(cmp_.water_m3_low.sum()), int(cmp_.water_m3_central.sum()), int(cmp_.water_m3_high.sum())],
                           "mewa_agri_groundwater_m3": off["national"]["agri_groundwater_m3"]}
    (ROOT / "out" / "national_summary.json").write_text(json.dumps(summ, indent=1))
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main()
