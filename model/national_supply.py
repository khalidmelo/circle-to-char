"""National supply: combine every region's radar field table into one table and totals.

Classes per field (radar): palm_grove, winter_only (wheat), summer_only, wheat_rotation, year_round,
idle (radar saw both seasons and neither was above the desert threshold), partly_seen_active /
partly_seen_inactive (the radar observed only one season, active or not), radar_unusable (covered but no
season classifiable, e.g. rejected by --qc), unseen (outside the radar swath).
Per field (low/central/high): irrigation water pumped, pumping electricity, CO2 (grid/diesel),
collectable wheat straw, palm fronds. Manure points are added by model/manure.py if present.

Pumping energy: electricity = pumped water x rho g x head / pump wire-to-water efficiency, with
head = static depth to water + drawdown + pivot pressure (pivots only): the static depth of the field's lift region
(lift_m in data/national/official_2024.json), drawdown_m and, on centre pivots that are not palm groves,
pivot_pressure_head_m (model/params.json), each at the same low/central/high level as the rest of the field's
estimate (column head_m_<level> in the field table). Centre pivot = circularity above 0.75 and at least 10 ha, the
rule of scripts/region_pipeline.py and scripts/s2_fields.py (column is_pivot, geometric: palm groves included). Palm
groves are not sprinkler pivots (model/national_scenarios.py's pivot retrofit leaves them out too), so a pivot-shaped
palm grove gets no pivot pressure (pressure_pivots); on the radar + Sentinel-2 tier the tier's own class decides.
Arabian Shield fields get water but no energy: there is no regional depth for them (summary key shield_no_energy
sizes what that leaves out).

A season counts as observed for a field only if the region has radar dates and a desert threshold for
it and the field had valid backscatter on one of those dates; an unobserved season is unknown, never
'not farmed'. By default (quality check; --no-qc turns it off) a region's season is also left unobserved when its desert background is bright
on every date (radio interference, or non-sand ground) or its threshold exceeds 6 dB.

Fields whose ESA WorldCover majority class is mangrove (95), herbaceous wetland (90) or open water (80) are dropped:
coastal mangroves, wetland and lake patches pass the NDVI test but are not farms.

Also in out/national_summary.json, next to the radar-only totals (never replacing them):
  pumping_head          the head rule, its parameters and notes, the pivots that carry pivot pressure and their
                        share of pumped water, the pivot-shaped palm groves left without it, and the electricity split
                        into static depth, drawdown and pivot pressure
  classification_range  the same totals with every region's threshold shifted by -1 dB and +1 dB on the stored
                        per-field HV above the desert median (factor ranges as in the main totals)
  s2_filled             radar + Sentinel-2 tier: winter fill of radar-idle fields, unobserved seasons filled from
                        Sentinel-2, Sentinel-2-only fields, wheat straw on Sentinel-2-filled fields capped per region
                        by GASTAT wheat (each tier carries a one-line 'scope')
  worldcover_filter, field_size, shield_no_energy (what the totals leave out or how they are built)
  national_supply_sha256  SHA-256 of this file; scripts/overlap_agreement.py records the same hash.
                        scripts/export_national.py stops when the summary's hash is not this file's, and leaves the
                        overlap block out when its hash is not the summary's

Output: data/national/fields_national.csv, out/national_summary.json, out/national_by_region.csv,
        out/national_vs_official.csv
Usage:  .venv/bin/python model/national_supply.py [--no-qc]   (the quality check is on by default)
"""
import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import shapely
from shapely.geometry import Point, box, shape

ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve()
RHO_G = 1000 * 9.81
LV = ("low", "central", "high")
SEASONS = ("winter", "summer")
BG_MAX_DB, THR_MAX_DB = -21.0, 6.0  # --qc: sand desert is about -23 to -27 dB in HV
CLASSES = ("winter_only", "wheat_rotation", "summer_only", "year_round", "palm_grove", "idle",
           "partly_seen_active", "partly_seen_inactive", "radar_unusable", "unseen")
WHEAT = ("winter_only", "wheat_rotation")  # the wheat pattern: farmed in winter, harvested in spring
FLOW_KEYS = ("water_m3", "elec_kwh", "elec_kwh_summer", "co2_t_grid", "co2_t_diesel", "straw_t_dry", "fronds_t_dry")
WC_DROP = {95: "mangrove", 90: "herbaceous_wetland", 80: "open_water"}  # ESA WorldCover v200 classes that are not farms
SHIELD_KEYS = ("Makkah", "Madinah", "Asir", "Jazan", "Najran", "Al-Baha")
# region_pipeline.py: patches below MIN_HA = 3.0 ha are removed at 40 m (0.16 ha pixels) BEFORE the watershed split
PX_HA_40M = 0.16
MIN_PATCH_PX = int(3.0 / PX_HA_40M)
QC_REJECTED = {}  # season -> regions whose season the quality check left unobserved (filled by load_fields)
WC_DROPPED = {}   # fields dropped by the WorldCover rule (filled by load_fields)
HEAD_RULE = "head = static depth to water + drawdown + pivot pressure (pivots only)"
PIVOT_RULE = ("centre pivot = circularity above 0.75 and at least 10 ha (the rule of scripts/region_pipeline.py and "
              "scripts/s2_fields.py); pivot pressure goes to centre pivots that are not palm groves, since palm groves "
              "are not sprinkler pivots")
HEAD_DETAIL = ("Pumping electricity per field = pumped water x rho g x head / pump wire-to-water efficiency "
               "(pump_wire_to_water_eff). Head = the static depth to water of the field's lift region (lift_m in "
               "data/national/official_2024.json; Riyadh fields south of 21.5 N use Wadi Dawasir, regions without a "
               "depth source the fallback) + drawdown_m + pivot_pressure_head_m on centre pivots that are not palm "
               "groves (model/params.json), all at the same level (low, central, high). Pivot-shaped palm groves get "
               "no pivot pressure: palm groves are not sprinkler pivots (the scenarios' pivot retrofit leaves them out "
               "too); on the radar + Sentinel-2 tier the tier's own class decides. Arabian Shield fields get water but "
               "no energy.")


def P():
    raw = json.loads((ROOT / "model" / "params.json").read_text())
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def file_sha256(path):
    """SHA-256 of a file's bytes (scripts/overlap_agreement.py records this module's; scripts/export_national.py compares)."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


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


def palm_rule(d):
    """Palms are evergreen: tree cover and active in every season observed (at least one)."""
    wa, sa = d.winter_active, d.summer_active
    return ((d.tree_frac >= 0.3) & (wa.notna() | sa.notna())
            & (wa.isna() | wa.eq(True)) & (sa.isna() | sa.eq(True)))


def is_pivot(df):
    """Centre pivots: circularity above 0.75 and at least 10 ha (scripts/region_pipeline.py land-cover filter,
    scripts/s2_fields.py is_pivot). Geometric: palm groves included (pressure_pivots leaves them out). Boolean Series."""
    return (df.circularity > 0.75) & (df.area_ha >= 10)


def pressure_pivots(df):
    """Fields that carry the pivot pressure head (PIVOT_RULE): centre pivots (is_pivot) that are not palm groves, by
    df['class'], the class of the table at hand (on the radar + Sentinel-2 tier, the tier's own class). Palm groves
    are not sprinkler pivots; model/national_scenarios.py's pivot retrofit leaves them out too. Boolean Series."""
    return is_pivot(df) & df["class"].ne("palm_grove")


def pump_head_m(df, p, lifts, lvl, key=None):
    """Total pumping head per field (m) at level lvl ('low', 'central' or 'high'), HEAD_RULE: the static depth to water
    of the field's lift region (lifts = lift_m of official_2024.json, rows picked by df.lift_key, or by key: one row
    name or a sequence per field) + drawdown_m[lvl] + pivot_pressure_head_m[lvl] on centre pivots that are not palm
    groves (pressure_pivots, so df needs its 'class')."""
    k = pd.Series(df.lift_key.values if key is None else key, index=df.index)
    static = k.map(lambda r: lifts[r][lvl]).astype(float)
    return (static + float(p["drawdown_m"][lvl])
            + np.where(pressure_pivots(df), float(p["pivot_pressure_head_m"][lvl]), 0.0))


def worldcover_majority(rdir):
    """Majority ESA WorldCover v200 class of each field of a region (fields_labels.tif against worldcover.tif, same
    grid); ties go to the lower class code, as in region_pipeline's land-cover filter. DataFrame indexed by field id
    (wc_major, wc_major_frac), or None when a raster is missing."""
    lp, wp = rdir / "fields_labels.tif", rdir / "worldcover.tif"
    if not (lp.exists() and wp.exists()):
        return None
    with rasterio.open(lp) as src:
        lab = src.read(1)
    with rasterio.open(wp) as src:
        wc = src.read(1)
    if lab.shape != wc.shape:
        return None
    m = lab > 0
    u, n = np.unique(lab[m].astype(np.int64) * 256 + wc[m], return_counts=True)
    t = pd.DataFrame({"id": u // 256, "wc": u % 256, "n": n})
    tot = t.groupby("id").n.sum()
    top = t.sort_values(["id", "n", "wc"], ascending=[True, False, True]).drop_duplicates("id").set_index("id")
    return pd.DataFrame({"wc_major": top.wc.astype(int), "wc_major_frac": (top.n / tot).round(3)})


def load_region(f, qc=False):
    """One region's field table (data/regions/<R>/fields_radar.csv) under the national season rule: season flags NaN
    where the season is not observed, the region's desert threshold per season (thr_<season>_db; NaN where the season
    is not classifiable, so re-flagging hv_above_desert_<season> > thr reproduces the flags) and each field's WorldCover
    majority. Returns (table or None when the region has no fields, meta)."""
    d = pd.read_csv(f, low_memory=False)
    meta = json.loads((f.parent / "meta.json").read_text())
    if not len(d):
        return None, meta
    thr = meta.get("validation", {}).get("thresholds_db", {})
    for se in SEASONS:
        ok = season_ok(meta, se, qc)
        # observed = classifiable season and a valid radar value on the field; otherwise unknown (NaN)
        seen = d[f"hv_above_desert_{se}"].notna() & ok
        d[f"{se}_active"] = tri(d[f"{se}_active"]).where(seen, np.nan)
        d[f"thr_{se}_db"] = float(thr[se]) if ok else np.nan
    for c in ("s2_winter_active", "s2_summer_active", "s2_winter_check", "spring_brown"):
        if c in d:
            d[c] = tri(d[c])
    wc = worldcover_majority(f.parent)
    d["wc_major"] = d.id.map(wc.wc_major) if wc is not None else np.nan
    d["wc_major_frac"] = d.id.map(wc.wc_major_frac) if wc is not None else np.nan
    return d, meta


def load_fields(qc=False):
    frames, skipped = [], {}
    for f in sorted((ROOT / "data" / "regions").glob("R*/fields_radar.csv")):
        d, meta = load_region(f, qc)
        if d is None:
            continue
        for se in SEASONS:
            if not season_ok(meta, se, qc) and se in meta.get("validation", {}).get("thresholds_db", {}):
                skipped.setdefault(se, []).append(f.parent.name)
        frames.append(d)
    QC_REJECTED.clear()
    QC_REJECTED.update(skipped)
    for se, rids in skipped.items():
        print(f"quality check: {se} left unobserved in {len(rids)} regions: {' '.join(rids)}")
    df = pd.concat(frames, ignore_index=True)
    df["palm_grove"] = palm_rule(df)
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
    # Not farms: coastal mangroves, wetland and lake patches pass the NDVI test (audit nd-7); built-up (50) is kept
    wet = df.wc_major.isin(list(WC_DROP))
    z = df[wet]
    WC_DROPPED.clear()
    WC_DROPPED.update({"fields": int(len(z)), "ha": round(float(z.area_ha.sum())),
                       "by_class": {WC_DROP[c]: {"fields": int((z.wc_major == c).sum()),
                                                 "ha": round(float(z[z.wc_major == c].area_ha.sum()))} for c in WC_DROP},
                       "by_region": {k: round(float(v)) for k, v in z.groupby("region").area_ha.sum().sort_values(ascending=False).items()},
                       "majority_unknown_fields": int(df.wc_major.isna().sum())})
    if wet.any():
        print(f"dropped {len(z)} fields ({z.area_ha.sum():,.0f} ha) whose WorldCover majority is mangrove, wetland or water")
    df = df.loc[~wet].reset_index(drop=True)
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
    Pumping energy uses HEAD_RULE (pump_head_m): static depth + drawdown + pivot pressure on centre pivots that are not
    palm groves (pressure_pivots, by this table's class); the head is kept as head_m_<lvl> (NaN on Arabian Shield
    fields, which get no energy) and the geometric pivot flag (palm groves included) as is_pivot.
    eff_override: pivot application efficiency to use instead of params (a number, or a {low, central, high} dict;
    the low estimate uses the high efficiency, as in params). Returns df."""
    if off is None:
        off = json.loads((ROOT / "data" / "national" / "official_2024.json").read_text())
    if eff_override is not None:
        p = p | {"pivot_application_efficiency": eff_override if isinstance(eff_override, dict)
                 else {lv: eff_override for lv in LV}}
    key = df.admin.map({k: v["key"] for k, v in off["regions"].items()}).fillna("_fallback")
    key = np.where((key == "Riyadh") & (df.lat < 21.5), "WadiDawasir", key)
    shield = pd.Series(key).isin(SHIELD_KEYS).values
    lifts = off["lift_m"]
    df["lift_key"] = [k if k in lifts else "_fallback" for k in key]
    df["shield"] = shield
    df["is_pivot"] = is_pivot(df)
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
        head = pump_head_m(df, p, lifts, lift)  # static depth + drawdown + pivot pressure (not on palm groves), same level
        work = np.where(df.shield, np.nan, water * RHO_G * head / 3.6e6)
        df[f"head_m_{lvl}"] = head.where(~df["shield"]).round(1)
        df[f"water_m3_{lvl}"] = water.round()
        df[f"elec_kwh_{lvl}"] = (work / p["pump_wire_to_water_eff"][lvl]).round()
        df[f"co2_t_grid_{lvl}"] = (df[f"elec_kwh_{lvl}"] * p["grid_kgco2e_per_kwh"][lvl] / 1000).round(2)
        df[f"co2_t_diesel_{lvl}"] = (work / p["diesel_water_kwh_per_litre"][lvl] * p["diesel_kgco2e_per_litre"][lvl] / 1000).round(2)
        df[f"elec_kwh_summer_{lvl}"] = (df[f"elec_kwh_{lvl}"] * summer_share).round()
        df[f"straw_t_dry_{lvl}"] = (df["class"].isin(WHEAT) * df.area_ha * p["straw_t_dry_per_ha"][lvl]).round(1)
        if "palms_per_ha" in p and p["palms_per_ha"][lvl] is not None:
            df[f"fronds_t_dry_{lvl}"] = ((df["class"] == "palm_grove") * df.area_ha * p["palms_per_ha"][lvl]
                                         * p["palm_residue_kg_dry_per_palm"][lvl] / 1000).round(1)
        else:
            df[f"fronds_t_dry_{lvl}"] = 0.0
    return df


def totals(df):
    """National totals of a classified, accounted field table. The same names in the radar-only summary, the
    classification range and the radar + Sentinel-2 tier."""
    part = df["class"].str.startswith("partly_seen")
    farmed = df.winter_active.eq(True) | df.summer_active.eq(True)
    t = {"fields": int(len(df)), "field_ha": round(float(df.area_ha.sum())),
         "farmed_ha": round(float(df[farmed].area_ha.sum())),
         "area_ha_by_class": {k: float(v) for k, v in df.groupby("class").area_ha.sum().round().items()},
         # farmed by season = active; fields where that season was not observed are counted apart
         "active_ha": {se: round(float(df[df[f"{se}_active"].eq(True)].area_ha.sum())) for se in SEASONS},
         "season_not_observed_ha": {se: round(float(df[part & df[f"{se}_active"].isna()].area_ha.sum())) for se in SEASONS},
         "wheat_ha": round(float(df[df["class"].isin(WHEAT)].area_ha.sum())),
         "year_round_ha": round(float(df[df["class"] == "year_round"].area_ha.sum()))}
    for k in FLOW_KEYS:
        t[k] = {lv: round(float(np.nansum(df[f"{k}_{lv}"])), 1) for lv in LV}
    # peak-season pumping load, averaged over Jun-Sep (122 days)
    t["summer_pumping_avg_mw"] = {lv: round(t["elec_kwh_summer"][lv] / (122 * 24) / 1000, 1) for lv in LV}
    return t


def pumping_head(df, p, off):
    """The head behind the radar-only electricity, CO2 and MW totals: the rule and its notes, the parameters, the
    pivots that carry pivot pressure (pressure_pivots) and their share of pumped water, the pivot-shaped palm groves
    left without it, and the electricity split into static depth, drawdown and pivot pressure."""
    lifts = off["lift_m"]
    piv, en = pressure_pivots(df), ~df.shield.astype(bool)
    palm = is_pivot(df) & ~piv  # pivot-shaped palm groves: no pivot pressure
    comp = {c: {} for c in ("static_depth", "drawdown", "pivot_pressure")}
    mean_head, piv_share, palm_kwh = {}, {}, {}
    for lv in LV:
        w = df[f"water_m3_{lv}"].where(en, 0.0)
        k = RHO_G / 3.6e6 / p["pump_wire_to_water_eff"][lv]
        static = df.lift_key.map(lambda r: lifts[r][lv]).astype(float)
        comp["static_depth"][lv] = round(float((w * static).sum()) * k)
        comp["drawdown"][lv] = round(float(w.sum()) * p["drawdown_m"][lv] * k)
        comp["pivot_pressure"][lv] = round(float(w[piv].sum()) * p["pivot_pressure_head_m"][lv] * k)
        palm_kwh[lv] = round(float(w[palm].sum()) * p["pivot_pressure_head_m"][lv] * k)
        tot = float(w.sum())
        mean_head[lv] = round(float((w * df[f"head_m_{lv}"].fillna(0.0)).sum()) / tot, 1) if tot else None
        piv_share[lv] = round(float(w[piv].sum()) / tot, 4) if tot else None
    return {"rule": HEAD_RULE, "detail": HEAD_DETAIL, "pivot_rule": PIVOT_RULE,
            "drawdown_m": {lv: p["drawdown_m"][lv] for lv in LV},
            "pivot_pressure_head_m": {lv: p["pivot_pressure_head_m"][lv] for lv in LV},
            # the lift table's text notes: '_age' (depths measured 1979-2009, levels have fallen since) and '_shield'
            "notes": {k: v for k, v in lifts.items() if isinstance(v, str)},
            "pivot_fields": int(piv.sum()), "pivot_ha": round(float(df[piv].area_ha.sum())),
            "pivot_share_of_pumped_water": piv_share, "mean_head_m": mean_head,
            "palm_grove_pivots": {"rule": "pivot-shaped palm groves (is_pivot, class palm_grove) get no pivot pressure; "
                                          "pressure_elec_kwh_not_charged is what the pivot pressure head would add on "
                                          "their water outside the Arabian Shield (in no total)",
                                  "fields": int(palm.sum()), "ha": round(float(df[palm].area_ha.sum())),
                                  "pressure_elec_kwh_not_charged": palm_kwh},
            "elec_kwh_by_component": comp,
            "components_rule": "the radar-only electricity split by head component (fields outside the Arabian Shield; "
                               "the three add up to elec_kwh); pivot_fields, pivot_ha and pivot_share_of_pumped_water "
                               "count the pivots that carry pivot pressure (pivot_rule: palm groves left out); "
                               "mean_head_m and pivot_share_of_pumped_water are weighted by the water pumped outside "
                               "the Shield"}


# ---------------------------------------------------------------- classification range (audit nd-2)
def reflag(df, shift_db=0.0):
    """Season flags re-derived from the stored per-field HV above the desert median against each region's threshold
    shifted by shift_db (positive = stricter), with the same tri-state (NaN where the season is not observed, incl.
    seasons the quality check rejects) and palm rule. Returns a copy without classes or flows."""
    d = df.copy()
    for se in SEASONS:
        v, thr = d[f"hv_above_desert_{se}"], d[f"thr_{se}_db"]
        d[f"{se}_active"] = (v > thr + shift_db).astype(object).where(v.notna() & thr.notna(), np.nan)
    d["palm_grove"] = palm_rule(d)
    return d


def classification_range(df, p, off, base_totals):
    """Totals with every region-season threshold shifted by -1 dB and +1 dB, the zero-shift check, and the corners
    of the combined factor x classification range."""
    z = reflag(df, 0.0)
    same = pd.Series(True, index=df.index)
    zero = {}
    for se in SEASONS:
        a, b = z[f"{se}_active"], tri(df[f"{se}_active"])
        eq = (a.isna() & b.isna()) | (a.notna() & b.notna() & (a == b))
        same &= eq
        zero[se] = {"share_identical": round(float(eq.mean()), 5), "fields_differ": int((~eq).sum()),
                    "ha_differ": round(float(df[~eq].area_ha.sum()), 1)}
    z["class"] = z.apply(classify, axis=1)
    z = flows(z, p, off=off)
    zt = totals(z)
    out = {"rule": "Every region's desert threshold shifted by -1 dB (looser: more fields active) and +1 dB (stricter: "
                   "fewer) on the stored per-field HV above the desert median, in every season the quality check "
                   "accepts; the same season, palm, class and accounting rules as the radar-only totals (including "
                   f"the pumping head: {HEAD_RULE}), at the same low/central/high factors. Shifting by 0 dB "
                   "reproduces the published flags.",
           "shift_db": {"minus_1db": -1.0, "plus_1db": 1.0},
           "zero_shift_check": {"fields": int(len(df)), "fields_identical": int(same.sum()),
                                "share_identical": round(float(same.mean()), 5), "by_season": zero,
                                "farmed_ha": zt["farmed_ha"], "published_farmed_ha": base_totals["farmed_ha"],
                                "water_m3_central": zt["water_m3"]["central"],
                                "published_water_m3_central": base_totals["water_m3"]["central"],
                                "why_not_100": "thresholds and HV values are stored rounded to 0.01 dB"}}
    states = [base_totals]
    for name, sh in (("minus_1db", -1.0), ("plus_1db", 1.0)):
        d = reflag(df, sh)
        d["class"] = d.apply(classify, axis=1)
        d = flows(d, p, off=off)
        out[name] = totals(d)
        states.append(out[name])
    # combined range: lowest factor level in the classification state giving the least, highest in the most
    out["corners"] = {k: {"low": min(s[k]["low"] for s in states), "high": max(s[k]["high"] for s in states)}
                      for k in (*FLOW_KEYS, "summer_pumping_avg_mw")}
    out["corners_rule"] = ("low = minimum over {-1 dB, published, +1 dB} of the low-factor total; high = maximum of the "
                           "high-factor total")
    return out


# ---------------------------------------------------------------- radar + Sentinel-2 tier (audits nd-8, nd-9)
S2_RULE = (
    "Radar + Sentinel-2 tier, published next to the radar-only totals and never replacing them; the area it adds is "
    "measured by Sentinel-2, not by the radar. Green = the field's median seasonal-maximum NDVI above 0.40 "
    "(s2_winter_active over 1 Nov-15 Mar, s2_summer_active over 10 Jun-31 Oct). "
    "(a) Winter fill: a field the radar calls not farmed in any season it observed (radar idle: winter observed and "
    "not active, summer not active or not observed) that Sentinel-2 sees green over 1 Nov-15 Mar and not green over "
    "10 Jun-31 Oct counts as winter-farmed (audit nd-8). Fields the radar sees farmed in summer are not filled. "
    "(b) Outside the Arabian Shield, the season the radar did not observe on a partly-seen field takes the Sentinel-2 "
    "flag for that season. "
    "(c) Outside the Shield, fields with no usable radar season (radar not usable, or outside the swath) are classified "
    "from the two Sentinel-2 flags alone, a separate tier. Every mapped field is green in at least one window (the "
    "field mask is Sentinel-2 green), so (c) counts all of its fields as farmed: an upper bound for them. "
    "(d) A filled field farmed in both seasons gets the year-round (perennial) depth only if the spring check marks it "
    "perennial (not brown over 20 Apr-5 Jun) and Sentinel-2 sees it green in both windows; otherwise it is a rotation "
    "(winter plus summer depth). Palm groves among the filled fields: tree cover of 30% or more, farmed in every known "
    "season and not brown in spring; radar palm groves are never refilled. "
    "(e) Wheat straw on fields that are wheat-pattern only through Sentinel-2 is capped per administrative region at "
    "GASTAT 2024 wheat area minus the radar wheat already there: the cap goes first to (a)/(b) fields, then to (c) "
    "fields, pro rata by area. Water, energy and CO2 are not capped; energy uses the same pumping head as the "
    "radar-only totals, with pivot pressure decided by the tier's own class (none on its palm groves).")


def s2_tier(df, p, off):
    """Radar + Sentinel-2 tier on a copy of the classified, accounted national table df.
    Returns (comb, seasons, masks, caps): comb = every fill applied (a, b, c), seasons = fills (a) and (b) only (the
    Sentinel-2-only fields keep their radar class), both with the tier's flags, classes and flows (wheat straw on
    Sentinel-2-filled fields capped); masks = {'a', 'bw', 'bs', 'c'} boolean Series of the fills, plus the diagnostics
    'a_summer_active' (radar summer-active fields the winter fill leaves alone) and 'palm_spring_brown' (filled fields
    that the palm rule would take but that are brown in spring); caps = per-region cap table (straw factors None where
    no Sentinel-2 wheat exists)."""
    t = df.copy()
    w0, s0 = tri(t.winter_active), tri(t.summer_active)
    s2w, s2s = tri(t.s2_winter_active), tri(t.s2_summer_active)
    sb = tri(t.spring_brown) if "spring_brown" in t else pd.Series(np.nan, index=t.index, dtype=object)
    base, shield = t["class"], t["shield"].astype(bool)
    s2_winter_only = s2w.eq(True) & s2s.eq(False)
    fa = w0.eq(False) & ~s0.eq(True) & s2_winter_only                                  # (a) radar idle only
    fa_left = w0.eq(False) & s0.eq(True) & s2_winter_only                              # summer-active: not filled
    part = base.isin(["partly_seen_active", "partly_seen_inactive"]) & ~shield
    fbw, fbs = part & w0.isna() & s2w.notna(), part & s0.isna() & s2s.notna()          # (b)
    fc = base.isin(["radar_unusable", "unseen"]) & ~shield & (s2w.notna() | s2s.notna())  # (c)
    w, s = w0.copy(), s0.copy()
    w[fa] = True
    w[fbw] = s2w[fbw]
    s[fbs] = s2s[fbs]
    w[fc], s[fc] = s2w[fc], s2s[fc]
    filled = fa | fbw | fbs | fc
    kw, ks, wt, st = w.notna(), s.notna(), w.eq(True), s.eq(True)
    palm0 = (t.tree_frac >= 0.3) & (kw | ks) & (~kw | wt) & (~ks | st)
    palm = palm0 & ~sb.eq(True)  # filled palm groves must not be brown in spring
    perennial = sb.eq(False) & s2w.eq(True) & s2s.eq(True)  # (d)
    new = pd.Series(np.select(
        [palm, kw & ks & wt & st & perennial, kw & ks & wt & st, kw & ks & wt, kw & ks & st, kw & ks,
         (kw | ks) & (wt | st), kw | ks],
        ["palm_grove", "year_round", "wheat_rotation", "winter_only", "summer_only", "idle",
         "partly_seen_active", "partly_seen_inactive"], "keep"), index=t.index)
    t["class"] = np.where(filled & (new != "keep"), new, base)
    t["winter_active"], t["summer_active"] = w.values, s.values
    t["palm_grove"] = t["class"].eq("palm_grove")
    t["s2_fill"] = np.select([fc, fa & (fbw | fbs), fa, fbw | fbs], ["s2_only", "winter_fill+season_fill",
                                                                    "winter_fill", "season_fill"], "")
    t = flows(t, p, off=off)
    for lv in LV:
        t[f"straw_t_dry_uncapped_{lv}"] = t[f"straw_t_dry_{lv}"]
    # (e) wheat straw cap per administrative region
    s2wheat = t["class"].isin(WHEAT) & ~base.isin(WHEAT)  # wheat-pattern only through Sentinel-2 (all filled)
    t1, t2 = s2wheat & ~fc, s2wheat & fc
    radar_wheat = df.area_ha.where(base.isin(WHEAT), 0).groupby(df.admin).sum()
    a1, a2 = (t.area_ha.where(m, 0).groupby(t.admin).sum() for m in (t1, t2))
    factor = pd.Series(1.0, index=t.index)
    caps = {}
    for adm in sorted(set(t.admin)):
        o = off["regions"].get(adm)
        g = float(o["wheat_ha"]) if o else 0.0
        cap = max(0.0, g - float(radar_wheat.get(adm, 0.0)))
        c1 = min(float(a1[adm]), cap)
        c2 = min(float(a2[adm]), cap - c1)
        f1 = c1 / a1[adm] if a1[adm] > 0 else 1.0
        f2 = c2 / a2[adm] if a2[adm] > 0 else 1.0
        factor[t1 & (t.admin == adm)] = f1
        factor[t2 & (t.admin == adm)] = f2
        caps[o["key"] if o else adm] = {
            "gastat_wheat_ha": round(g), "radar_wheat_ha": round(float(radar_wheat.get(adm, 0.0))), "cap_ha": round(cap),
            "s2_wheat_ha_seasons": round(float(a1[adm])), "credited_ha_seasons": round(c1),
            "straw_factor_seasons": round(f1, 4) if a1[adm] > 0 else None,  # None: no Sentinel-2 wheat to credit
            "s2_wheat_ha_s2_only": round(float(a2[adm])), "credited_ha_s2_only": round(c2),
            "straw_factor_s2_only": round(f2, 4) if a2[adm] > 0 else None}
    t["straw_cap_factor"] = factor.where(s2wheat, np.nan)
    for lv in LV:
        t[f"straw_t_dry_{lv}"] = (t[f"straw_t_dry_uncapped_{lv}"] * factor).round(1)
    # tier (a)+(b) only: the Sentinel-2-only fields keep their radar-only class, flags and flows
    seasons = t.copy()
    for c in ["class", "winter_active", "summer_active", "palm_grove"] + [f"{k}_{lv}" for k in FLOW_KEYS for lv in LV]:
        seasons[c] = seasons[c].where(~fc, df[c])
    for lv in LV:
        seasons[f"straw_t_dry_uncapped_{lv}"] = seasons[f"straw_t_dry_uncapped_{lv}"].where(~fc, df[f"straw_t_dry_{lv}"])
    seasons["straw_cap_factor"] = seasons.straw_cap_factor.where(~fc, np.nan)
    seasons["s2_fill"] = seasons.s2_fill.where(~fc, "")
    masks = {"a": fa, "bw": fbw, "bs": fbs, "c": fc, "a_summer_active": fa_left,
             "palm_spring_brown": filled & palm0 & sb.eq(True)}
    return t, seasons, masks, caps


def s2_summary(df, comb, seasons, masks, caps, off, p):
    """The 's2_filled' block of the summary: tier totals (each with a one-line scope), the fills, the straw cap and the
    check against official statistics per administrative region."""
    fa, fbw, fbs, fc = masks["a"], masks["bw"], masks["bs"], masks["c"]
    filled = comb.s2_fill.ne("")
    yr2, rot2 = filled & comb["class"].eq("year_round"), filled & comb["class"].eq("wheat_rotation")
    # rotations that the radar rule would call year-round (spring not brown) but Sentinel-2 does not see green in both
    s2w, s2s = tri(df.s2_winter_active), tri(df.s2_summer_active)
    strict = rot2 & tri(df.spring_brown).eq(False) & ~(s2w.eq(True) & s2s.eq(True))

    def extra_mm(lv):  # perennial depth over rotation depth (winter + summer crop)
        return (p["irrigation_mm_year_round"][lv] - p["irrigation_mm_winter_only"][lv] - p["irrigation_mm_summer_crop"][lv])
    eff = {"low": "high", "central": "central", "high": "low"}

    def tier(d, scope, sub=None):
        x = d if sub is None else d[sub]
        t = {"scope": scope, **totals(x)}
        filled = x.s2_fill.ne("")
        t["s2_filled_fields"], t["s2_filled_ha"] = int(filled.sum()), round(float(x[filled].area_ha.sum()))
        t["straw_t_dry_uncapped"] = {lv: round(float(x[f"straw_t_dry_uncapped_{lv}"].sum()), 1) for lv in LV}
        s2w = x["class"].isin(WHEAT) & x.straw_cap_factor.notna()
        t["wheat_ha_straw_credited"] = round(float(x[x["class"].isin(WHEAT) & ~s2w].area_ha.sum()
                                                   + (x.area_ha * x.straw_cap_factor)[s2w].sum()))
        return t

    def cls_ha(m):
        return {k: round(float(v)) for k, v in df[m].groupby("class").area_ha.sum().items()}

    piv = is_pivot(df)
    pb = masks.get("palm_spring_brown", pd.Series(False, index=df.index))
    fl = masks.get("a_summer_active", pd.Series(False, index=df.index))
    fills = {"winter_fill": {"rule": "radar idle only: winter observed and not active, summer not active or not "
                                     "observed; Sentinel-2 green over 1 Nov-15 Mar and not over 10 Jun-31 Oct",
                             "fields": int(fa.sum()), "ha": round(float(df[fa].area_ha.sum())), "by_radar_class": cls_ha(fa),
                             "in_shield_ha": round(float(df[fa & df.shield.astype(bool)].area_ha.sum())),
                             "pivots_ha": round(float(df[fa & piv].area_ha.sum())),
                             "radar_summer_active_not_filled": {"fields": int(fl.sum()), "ha": round(float(df[fl].area_ha.sum())),
                                                                "by_radar_class": cls_ha(fl)}},
             "season_fill": {se: {"fields": int(m.sum()), "ha": round(float(df[m].area_ha.sum())),
                                  "s2_green_ha": round(float(df[m & tri(df[f"s2_{se}_active"]).eq(True)].area_ha.sum()))}
                             for se, m in (("winter", fbw), ("summer", fbs))},
             "s2_only": {"fields": int(fc.sum()), "ha": round(float(df[fc].area_ha.sum())), "by_radar_class": cls_ha(fc),
                         "by_region": {k: round(float(v)) for k, v in df[fc].groupby("region").area_ha.sum().sort_values(ascending=False).items()}},
             "palm_spring_check": {"rule": "filled and Sentinel-2-only fields become palm groves only if not brown in "
                                           "spring; these fields met the other palm conditions but are brown in spring",
                                   "fields": int(pb.sum()), "ha": round(float(df[pb].area_ha.sum())),
                                   "palm_ha_filled": round(float(comb[filled & comb["class"].eq("palm_grove") & ~fc].area_ha.sum())),
                                   "palm_ha_s2_only": round(float(comb[fc & comb["class"].eq("palm_grove")].area_ha.sum()))},
             "filled_two_season": {
                 "year_round_ha": round(float(comb[yr2].area_ha.sum())),
                 "year_round_ha_by_fill": {k: round(float(v)) for k, v in comb[yr2].groupby("s2_fill").area_ha.sum().items()},
                 "wheat_rotation_ha": round(float(comb[rot2].area_ha.sum())),
                 "spring_not_brown_but_not_green_in_both_windows_ha": round(float(comb[strict].area_ha.sum())),
                 "year_round_extra_water_m3_over_rotation": {
                     lv: round(float(comb[yr2].area_ha.sum()) * 1e4 * extra_mm(lv) / 1000 / p["pivot_application_efficiency"][eff[lv]])
                     for lv in LV},
                 "note": "filled fields farmed in both seasons: year-round (perennial) depth where the spring check "
                         "marks them perennial and Sentinel-2 sees them green in both windows, rotation depth "
                         "otherwise; year_round_extra_water_m3_over_rotation is what the perennial depth adds over "
                         "treating every one of them as a rotation"}}
    cap_tot = {"rule": "per administrative region: cap = max(0, GASTAT 2024 wheat area - radar wheat-pattern area "
                       "(winter-only + rotation)); Sentinel-2-filled wheat-pattern area is credited with straw up to "
                       "the cap, first fills (a)/(b), then Sentinel-2-only fields, pro rata by area; a straw factor is "
                       "null where the region has no such area",
               "by_region": caps,
               "effect": {tier_name: {"straw_t_dry_uncapped": {lv: round(float(d[f"straw_t_dry_uncapped_{lv}"].sum()), 1) for lv in LV},
                                      "straw_t_dry_capped": {lv: round(float(d[f"straw_t_dry_{lv}"].sum()), 1) for lv in LV},
                                      "s2_wheat_ha": round(float(d[d.straw_cap_factor.notna()].area_ha.sum())),
                                      "s2_wheat_ha_credited": round(float((d.area_ha * d.straw_cap_factor).sum()))}
                          for tier_name, d in (("radar_plus_s2_seasons", seasons), ("combined", comb))},
               "regions_capped": sorted(k for k, v in caps.items() if (v["s2_wheat_ha_seasons"] + v["s2_wheat_ha_s2_only"])
                                        > v["credited_ha_seasons"] + v["credited_ha_s2_only"] + 0.5)}
    # (g) each administrative region against MEWA water and GASTAT wheat and fodder
    rows, over = [], []
    for adm, o in off["regions"].items():
        r = {"region": o["key"], "gastat_wheat_ha": o["wheat_ha"], "gastat_fodder_ha": o["fodder_ha"],
             "mewa_agri_groundwater_m3": o["agri_groundwater_m3"]}
        for tag, d in (("radar", df), ("seasons", seasons), ("combined", comb)):
            x = d[d.admin == adm]
            r[f"{tag}_wheat_ha"] = round(float(x[x["class"].isin(WHEAT)].area_ha.sum()))
            if tag != "radar":
                s2w = x["class"].isin(WHEAT) & x.straw_cap_factor.notna()
                r[f"{tag}_wheat_credited_ha"] = round(float(x[x["class"].isin(WHEAT) & ~s2w].area_ha.sum()
                                                            + (x.area_ha * x.straw_cap_factor)[s2w].sum()))
            r[f"{tag}_year_round_ha"] = round(float(x[x["class"] == "year_round"].area_ha.sum()))
            r[f"{tag}_water_m3"] = [round(float(x[f"water_m3_{lv}"].sum())) for lv in LV]
            if tag == "radar":
                continue
            for metric, val, ref in (("wheat_ha", r[f"{tag}_wheat_ha"], o["wheat_ha"]),
                                     ("year_round_ha", r[f"{tag}_year_round_ha"], o["fodder_ha"]),
                                     ("water_m3_central", r[f"{tag}_water_m3"][1], o["agri_groundwater_m3"])):
                if ref and val > ref:
                    over.append({"region": o["key"], "tier": "radar_plus_s2_seasons" if tag == "seasons" else "combined",
                                 "metric": metric, "value": val, "official": ref, "ratio": round(val / ref, 2),
                                 "radar_only": r[{"wheat_ha": "radar_wheat_ha", "year_round_ha": "radar_year_round_ha"}[metric]]
                                 if metric != "water_m3_central" else r["radar_water_m3"][1]})
        rows.append(r)
    n, nc = len(comb), int(fc.sum())
    return {"rule": S2_RULE,
            "radar_plus_s2_seasons": tier(seasons, f"all {n:,} mapped fields: radar classes with fills (a) and (b); the "
                                                   f"{nc:,} fields of fill (c) keep their radar class (no water)"),
            "s2_only_fields": tier(comb, f"only the {nc:,} fields of fill (c): no usable radar season, outside the "
                                         "Arabian Shield, classified from Sentinel-2 alone", fc),
            "combined": tier(comb, f"all {n:,} mapped fields with fills (a), (b) and (c): water, energy, CO2, straw, "
                                   "fronds and farmed area = radar_plus_s2_seasons + s2_only_fields (fields, field area "
                                   "and class areas do not add up)"),
            "caps": cap_tot,
            "fills": fills,
            "vs_official": {"rule": "each administrative region's tier totals against GASTAT 2024 wheat and fodder "
                                    "(year-round fields) and MEWA 2024 agricultural groundwater; an overshoot is a tier "
                                    "total above the official whole-region figure although the boxes cover only part "
                                    "of each region's farmland. wheat_ha is the uncapped wheat pattern; "
                                    "*_wheat_credited_ha is the area credited with straw after the cap. Water: "
                                    "[low, central, high]",
                            "regions": rows, "overshoots": over}}


# ---------------------------------------------------------------- what the totals leave out or how they are built
def field_size(df):
    """Audit nd-5: the 3 ha minimum applies to green patches before the watershed split, not to fields."""
    small, tiny = df.area_ha < 3.0, df.area_ha < MIN_PATCH_PX * PX_HA_40M - 1e-9
    return {"rule": f"Green patches (seasonal maximum NDVI above 0.40 in winter or summer, after a one-pixel opening) "
                    f"of at least {MIN_PATCH_PX} pixels ({MIN_PATCH_PX * PX_HA_40M:.2f} ha at 40 m) are kept, then a "
                    f"watershed cuts touching fields apart; the cut pieces can be smaller (the smallest field is "
                    f"{df.area_ha.min():.2f} ha). Fields under 3 ha are kept: they are parts of real patches, so "
                    f"dropping them would remove farmed area.",
            "min_patch_px": MIN_PATCH_PX, "min_patch_ha": round(MIN_PATCH_PX * PX_HA_40M, 2),
            "smallest_field_ha": round(float(df.area_ha.min()), 2),
            "fields_under_3ha": int(small.sum()), "ha_under_3ha": round(float(df[small].area_ha.sum())),
            "share_of_field_area_under_3ha": round(float(df[small].area_ha.sum() / df.area_ha.sum()), 4),
            "share_of_fields_under_3ha": round(float(small.mean()), 4),
            "fields_under_min_patch": int(tiny.sum()), "ha_under_min_patch": round(float(df[tiny].area_ha.sum())),
            "water_m3_central_under_3ha": round(float(df[small].water_m3_central.sum())),
            "area_ha_by_class_under_3ha": {k: round(float(v)) for k, v in df[small].groupby("class").area_ha.sum().items()}}


def shield_no_energy(df, p, off):
    """Gap-3: Arabian Shield fields get water but no pumping energy or CO2 (no regional depth). The indicative figure
    pumps the same water against the fallback head (fallback static depth + drawdown + pivot pressure on pivots that
    are not palm groves)."""
    sh = df.shield.astype(bool)
    wet = sh & (df.water_m3_central > 0)
    key = df.admin.map({k: v["key"] for k, v in off["regions"].items()})
    lifts = off["lift_m"]
    fb = lifts["_fallback"]
    ind = {}
    for lv in LV:
        head = pump_head_m(df[sh], p, lifts, lv, key="_fallback")
        ind[lv] = round(float((df.loc[sh, f"water_m3_{lv}"] * RHO_G * head / 3.6e6 / p["pump_wire_to_water_eff"][lv]).sum()))
    by = {}
    for k in SHIELD_KEYS:
        m = sh & (key == k)
        if m.any():
            by[k] = {"fields": int(m.sum()), "field_ha": round(float(df[m].area_ha.sum())),
                     "fields_with_water": int((m & wet).sum()), "water_m3_central": round(float(df[m].water_m3_central.sum()))}
    tot_w = {lv: float(df[f"water_m3_{lv}"].sum()) for lv in LV}
    dd, pp = p["drawdown_m"], p["pivot_pressure_head_m"]
    return {"note": lifts.get("_shield"),
            "fields": int(sh.sum()), "field_ha": round(float(df[sh].area_ha.sum())),
            "fields_with_water": int(wet.sum()), "field_ha_with_water": round(float(df[wet].area_ha.sum())),
            "water_m3": {lv: round(float(df.loc[sh, f"water_m3_{lv}"].sum())) for lv in LV},
            "share_of_water": {lv: round(float(df.loc[sh, f"water_m3_{lv}"].sum()) / tot_w[lv], 4) if tot_w[lv] else None for lv in LV},
            "by_admin": by,
            "indicative_elec_kwh_at_fallback_lift": ind,
            "indicative_rule": "not in any total: the same water pumped against the fallback head "
                               f"({HEAD_RULE}): fallback static depth {fb['low']}/{fb['central']}/{fb['high']} m (the "
                               f"Qassim range) + drawdown {dd['low']}/{dd['central']}/{dd['high']} m + pivot pressure "
                               f"{pp['low']}/{pp['central']}/{pp['high']} m on pivots that are not palm groves, to "
                               "size what the electricity, CO2 and MW totals leave out"}


def _write(path, write):
    """Write through a temporary file and rename, so a reader never sees a half-written output."""
    tmp = path.with_name(f".{path.name}.tmp")
    write(tmp)
    os.replace(tmp, path)


def main():
    code_hash = file_sha256(SELF)  # hashed before the run: the code these outputs come from
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
    comb, seasons, masks, caps = s2_tier(df, p, off)
    out = ROOT / "data" / "national"
    # the radar + Sentinel-2 tier per field (class, the fill that changed it, capped straw and fronds), next to the base
    pub = df.copy()
    pub["class_s2"], pub["s2_fill"] = comb["class"], comb["s2_fill"]
    for k in ("straw_t_dry", "fronds_t_dry"):
        for lv in LV:
            pub[f"{k}_s2_{lv}"] = comb[f"{k}_{lv}"]
    _write(out / "fields_national.csv", lambda t: pub.to_csv(t, index=False))

    base = totals(df)
    summ = {"regions_done": int(df.region.nunique()), "fields": int(len(df)), "quality_check": qc,
            "quality_check_rule": f"season left unobserved if the desert background is above {BG_MAX_DB} dB on every "
                                  f"date or the threshold exceeds {THR_MAX_DB} dB" if qc else None,
            "quality_check_rejected": {se: sorted(r, key=lambda x: int(x[1:])) for se, r in QC_REJECTED.items()},
            "field_ha": base["field_ha"], "farmed_ha": base["farmed_ha"], "area_ha_by_class": base["area_ha_by_class"],
            "active_ha": base["active_ha"], "season_not_observed_ha": base["season_not_observed_ha"],
            "outside_saudi_dropped_ha": round(outside_ha)}
    for k in (*FLOW_KEYS, "summer_pumping_avg_mw"):
        summ[k] = base[k]
    summ["wheat_ha"], summ["year_round_ha"] = base["wheat_ha"], base["year_round_ha"]
    summ["pumping_head"] = pumping_head(df, p, off)
    by = df.groupby("region").agg(lon=("lon", "mean"), lat=("lat", "mean"), fields=("uid", "count"), field_ha=("area_ha", "sum"),
                                  water_m3=("water_m3_central", "sum"), elec_kwh=("elec_kwh_central", "sum"),
                                  straw_t=("straw_t_dry_central", "sum"), fronds_t=("fronds_t_dry_central", "sum"))
    for c in CLASSES:
        by[f"{c}_ha"] = df[df["class"] == c].groupby("region").area_ha.sum()
    farmed = df.winter_active.eq(True) | df.summer_active.eq(True)
    by["farmed_ha"] = df[farmed].groupby("region").area_ha.sum()
    for se in SEASONS:
        by[f"active_{se}_ha"] = df[df[f"{se}_active"].eq(True)].groupby("region").area_ha.sum()
    by = by.fillna(0).round(1)
    _write(ROOT / "out" / "national_by_region.csv", lambda t: by.to_csv(t))
    # Comparison with official 2024 statistics by administrative region
    rows = []
    for name, o in off["regions"].items():
        d = df[df.admin == name]
        palms = {l: float((d["class"] == "palm_grove").mul(d.area_ha).sum() * p["palms_per_ha"][l]) for l in LV}
        rows.append({"region": o["key"], "fields": int(len(d)), "radar_seen_ha": round(d[d["class"] != "unseen"].area_ha.sum()),
                     "radar_partly_seen_ha": round(d[d["class"].str.startswith("partly_seen")].area_ha.sum()),
                     "radar_unusable_ha": round(d[d["class"] == "radar_unusable"].area_ha.sum()),
                     "radar_winter_only_ha": round(d[d["class"] == "winter_only"].area_ha.sum()),
                     "radar_wheat_ha": round(d[d["class"].isin(WHEAT)].area_ha.sum()), "gastat_wheat_ha": o["wheat_ha"],
                     "radar_year_round_ha": round(d[d["class"] == "year_round"].area_ha.sum()), "gastat_fodder_ha": o["fodder_ha"],
                     "radar_palm_ha": round(d[d["class"] == "palm_grove"].area_ha.sum()), "palms_est_low": round(palms["low"]),
                     "palms_est_high": round(palms["high"]), "gastat_palms": o["date_palms"],
                     "water_m3_central": round(float(d.water_m3_central.sum())), "water_m3_low": round(float(d.water_m3_low.sum())),
                     "water_m3_high": round(float(d.water_m3_high.sum())), "mewa_agri_groundwater_m3": o["agri_groundwater_m3"]})
    cmp_ = pd.DataFrame(rows)
    _write(ROOT / "out" / "national_vs_official.csv", lambda t: cmp_.to_csv(t, index=False))
    summ["vs_official"] = {"radar_winter_only_ha": int(cmp_.radar_winter_only_ha.sum()), "radar_wheat_ha": int(cmp_.radar_wheat_ha.sum()),
                           "gastat_wheat_ha": off["national"]["wheat_ha"],
                           "radar_year_round_ha": int(cmp_.radar_year_round_ha.sum()), "gastat_fodder_ha": off["national"]["fodder_ha"],
                           "palms_est": [int(cmp_.palms_est_low.sum()), int(cmp_.palms_est_high.sum())], "gastat_palms": off["national"]["date_palms"],
                           "water_m3": [int(cmp_.water_m3_low.sum()), int(cmp_.water_m3_central.sum()), int(cmp_.water_m3_high.sum())],
                           "mewa_agri_groundwater_m3": off["national"]["agri_groundwater_m3"]}
    summ["worldcover_filter"] = {"rule": "fields whose ESA WorldCover v200 majority class (fields_labels.tif against "
                                         "worldcover.tif, 40 m) is mangrove (95), herbaceous wetland (90) or open water "
                                         "(80) are dropped; built-up (50) is kept", **WC_DROPPED}
    summ["field_size"] = field_size(df)
    summ["shield_no_energy"] = shield_no_energy(df, p, off)
    summ["classification_range"] = classification_range(df, p, off, base)
    summ["s2_filled"] = s2_summary(df, comb, seasons, masks, caps, off, p)
    summ["national_supply_sha256"] = code_hash
    _write(ROOT / "out" / "national_summary.json", lambda t: t.write_text(json.dumps(summ, indent=1)))
    print(json.dumps({k: v for k, v in summ.items() if k not in ("classification_range", "s2_filled", "pumping_head")}, indent=1))
    ph = summ["pumping_head"]
    c = ph["elec_kwh_by_component"]
    print(f"pumping head ({HEAD_RULE}): mean {ph['mean_head_m']['central']} m central; pivots with pressure "
          f"{ph['pivot_ha']:,} ha, {ph['pivot_share_of_pumped_water']['central']:.1%} of pumped water (pivot-shaped palm "
          f"groves without it: {ph['palm_grove_pivots']['ha']:,} ha); electricity central "
          f"{base['elec_kwh']['central'] / 1e9:.3f} TWh = static {c['static_depth']['central'] / 1e9:.3f} + drawdown "
          f"{c['drawdown']['central'] / 1e9:.3f} + pivot pressure {c['pivot_pressure']['central'] / 1e9:.3f}")
    cr, s2 = summ["classification_range"], summ["s2_filled"]
    print("classification range (-1 dB / published / +1 dB): farmed ha", cr["minus_1db"]["farmed_ha"], base["farmed_ha"],
          cr["plus_1db"]["farmed_ha"], "| water bn m3 central", round(cr["minus_1db"]["water_m3"]["central"] / 1e9, 2),
          round(base["water_m3"]["central"] / 1e9, 2), round(cr["plus_1db"]["water_m3"]["central"] / 1e9, 2),
          "| zero-shift identical", cr["zero_shift_check"]["share_identical"])
    for k in ("radar_plus_s2_seasons", "s2_only_fields", "combined"):
        t = s2[k]
        print(f"s2 tier {k}: farmed {t['farmed_ha']:,} ha, wheat {t['wheat_ha']:,} ha (credited {t['wheat_ha_straw_credited']:,}), "
              f"water {t['water_m3']['central'] / 1e9:.2f} bn m3, electricity {t['elec_kwh']['central'] / 1e9:.2f} TWh, "
              f"straw {t['straw_t_dry']['central'] / 1e3:,.0f} kt (uncapped {t['straw_t_dry_uncapped']['central'] / 1e3:,.0f})")
    for o in s2["vs_official"]["overshoots"]:
        print("overshoot:", o)


if __name__ == "__main__":
    main()
