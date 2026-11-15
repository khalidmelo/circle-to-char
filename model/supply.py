"""Per-field water, pumping energy, CO2, collectable straw and palm fronds, with low/central/high ranges.

Input  data/fields/fields_radar.csv (--source radar: radar season flags, the stored seasonal peak HV above the desert
        median, the Sentinel-2 flags and circularity) or data/fields/fields.csv (default --source s2: the Sentinel-2
        flags as season flags)
       data/fields/national_flags.csv and national_flags.json (scripts/transfer_national_flags.py): each field's own
        WorldCover tree cover (tree_frac) and the national run's Sentinel-2 spring check (spring_brown) where a national
        field covers at least half of it; the json holds the md5 of the national table they came from, the match counts
        and the tree_frac_source codes. --source radar stops when the files are missing, and either source stops when
        the json is missing or does not describe the csv; --no-national-flags runs without them (the rule before the
        national flags: no palm class, and fields farmed in both seasons stay year-round)
       out/background.json (scripts/radar_fields.py): the unrounded desert thresholds, for the classification range
       data/national/official_2024.json: lift_m.Qassim, which must equal pumping_lift_m at every level (the run stops
        otherwise), and GASTAT 2024 wheat per region
       out/national_summary.json and data/national/fields_national.csv (model/national_supply.py; --source radar only):
        the national run's wheat-straw cap factor for the deep fields' administrative region (S2_RULE (e))
Output data/supply.csv  (one row per field; used by model/siting.py and scripts/export_web.py)
       out/supply_summary.json (scripts/export_web.py copies it to docs/data/summary.json "supply")
       Both are written only after every check below has passed.

Field classes: the national rule, model/national_supply.classify (irrigation depths and summer shares as in
model/national_supply.flows)
  palm_grove     -> tree cover >= 0.3 and farmed in both seasons (perennial depth; palm fronds, a second feed for
                    model/siting.py)
  winter_only    -> seasonal crop, treated as wheat (winter depth; straw collectable)
  wheat_rotation -> farmed in both seasons and brown in late spring: wheat, then a summer crop
                    (winter + summer depth; straw collectable)
  summer_only    -> seasonal summer crop (summer-crop depth; no sourced straw factor, so 0)
  year_round     -> farmed in both seasons and green in late spring: perennial fodder, mostly alfalfa (perennial
                    depth; residue not collectable). Fields without a spring flag stay here, as in the national run
  idle           -> radar detected farming in neither season
elec_kwh_summer_<lvl> is the June-September share of pumping electricity: all of a summer crop's,
summer / (winter + summer) of a rotation's, half of a perennial field's or palm grove's.

Pumping energy, as in the national run (model/national_supply.flows): electricity = water x 1000 x 9.81 x head / 3.6e6
/ pump_wire_to_water_eff, with
  head = pumping_lift_m + drawdown_m + pivot_pressure_head_m (centre pivots that are not palm groves)
each at the estimate's level (low / central / high; model/params.json). pumping_lift_m is the static depth to water
measured at Buraidah in 2006, the national run's Qassim lift: the run stops unless the two are equal at every level.
Centre pivot = circularity above 0.75 and at least 10 ha (model/national_supply.is_pivot, the rule of
scripts/s2_fields.py's is_pivot column; data/supply.csv keeps this geometric flag). Palm groves are not sprinkler
pivots, so a pivot-shaped palm grove gets no pivot pressure (model/national_supply.pressure_pivots, as in the national
run; model/national_scenarios.py's pivot retrofit leaves them out too).

Summary (out/supply_summary.json):
  source, fields, area_ha_by_class, fields_by_class, water_m3, elec_kwh, elec_kwh_summer, co2_t_electric,
    co2_t_diesel, residue_t_dry (straw), fronds_t_dry: the deep dive's keys, sums of data/supply.csv
  field_ha, farmed_ha, active_ha, season_not_observed_ha, wheat_ha, year_round_ha, co2_t_grid (= co2_t_electric),
    straw_t_dry (= residue_t_dry), summer_pumping_avg_mw: the same totals under the names of
    out/national_summary.json, so page code can share logic with the national page
  pumping_head          the head rule, its factors and notes, the pivots that carry pivot pressure and their share of
                        pumped water, the pivot-shaped palm groves left without it, the mean head and the electricity
                        split into static depth, drawdown and pivot pressure (the keys of the national summary's
                        pumping_head, plus pumping_lift_m); notes.depth_age and depth_age_sensitivity size what the
                        water-level decline since 2006 would add here, notes.national_lift_table_age is the national
                        lift table's note (national figures)
  national_flags        the flag files, the md5 of the national table they came from (national_flags.json) and whether
                        it is the current table, matches, tree-cover sources
  classification_range  (--source radar) the totals with both desert thresholds of out/background.json shifted by
                        -1 dB and +1 dB, at the low/central/high factors (as model/national_supply.classification_range)
  s2_filled             (--source radar) radar + Sentinel-2 tier: model/national_supply.s2_tier itself on the deep table,
                        with the national run's straw cap factor for the region (see S2_RULE); null for --source s2
Usage  .venv/bin/python model/supply.py [--source s2|radar] [--no-national-flags]
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "model"))
import national_supply as SUP  # noqa: E402  (the national radar + Sentinel-2 tier, called as it is)
from national_supply import (admin_regions, classify, is_pivot, palm_rule, pressure_pivots,  # noqa: E402
                             tri)  # the national rules, as they are (pressure_pivots: pivots that are not palm groves)

RHO_G = 1000 * 9.81  # N per m3 per m of head
LV = ("low", "central", "high")
SEASONS = ("winter", "summer")
WHEAT = ("winter_only", "wheat_rotation")
FLOW_KEYS = ("water_m3", "elec_kwh", "elec_kwh_summer", "co2_t_grid", "co2_t_diesel", "straw_t_dry", "fronds_t_dry")
DEEP_NAME = {"co2_t_grid": "co2_t_electric", "straw_t_dry": "residue_t_dry"}  # data/supply.csv names
ROUND = {"water_m3": 0, "elec_kwh": 0, "elec_kwh_summer": 0, "co2_t_grid": 2, "co2_t_diesel": 2, "straw_t_dry": 1,
         "fronds_t_dry": 1}
# check_same_rules: largest difference allowed between model/national_supply's flows and this module's on the same
# classes, one rounding unit (the national function rounds electricity before its summer share and grid CO2, and the
# head to 0.1 m)
TOL = {"water_m3": 1.0, "elec_kwh": 1.0, "elec_kwh_summer": 1.0, "co2_t_grid": 0.01, "co2_t_diesel": 0.01,
       "straw_t_dry": 0.1, "fronds_t_dry": 0.1, "head_m": 0.05}
FLAGS_FILE = "data/fields/national_flags.csv"
FLAGS = ROOT / FLAGS_FILE
FLAGS_META_FILE = "data/fields/national_flags.json"
FLAGS_META = ROOT / FLAGS_META_FILE
NATIONAL_TABLE = ROOT / "data" / "national" / "fields_national.csv"
NATIONAL_SUMMARY = ROOT / "out" / "national_summary.json"
OFFICIAL = ROOT / "data" / "national" / "official_2024.json"
LIFT_KEY = "Qassim"  # the deep box's row of lift_m in data/national/official_2024.json
DEPTH_YEAR, SEASON_YEAR = 2006, 2026  # pumping_lift_m was measured in 2006; the radar season is 2025/26
DECLINE_M_PER_YR = (0.5, 2.0)  # water-level decline today, m a year (depth_age_sensitivity)
DECLINE_SOURCE = ("Buscarlet et al. 2024 (Al Ula, Saq-Disi system; cited by Salem & Yihdego 2026, Discover Geoscience "
                  "4:203, ref 46), used as an analogue: no measured decline at Buraidah after 2006 was found")
HEAD_RULE = "head = static depth to water + drawdown + pivot pressure (pivots only)"
HEAD_DETAIL = ("Pumping electricity per field = pumped water x rho g x head / pump wire-to-water efficiency "
               "(pump_wire_to_water_eff), as in the national run. Head = pumping_lift_m (static depth to water, Buraidah "
               "2006; equal to the national run's Qassim lift, lift_m.Qassim of data/national/official_2024.json, at "
               "every level, or the run stops) + drawdown_m + pivot_pressure_head_m on centre pivots that are not palm "
               "groves (model/params.json), all at the same level (low, central, high). Pivot-shaped palm groves get no "
               "pivot pressure: palm groves are not sprinkler pivots (as in the national run, whose pivot retrofit "
               "scenario leaves them out too).")
PIVOT_RULE = ("centre pivot = circularity above 0.75 and at least 10 ha (model/national_supply.is_pivot; the rule of "
              "scripts/s2_fields.py's is_pivot column); pivot pressure goes to centre pivots that are not palm groves, "
              "since palm groves are not sprinkler pivots (model/national_supply.pressure_pivots)")
S2_RULE = (
    "Radar + Sentinel-2 tier, published next to the radar-only totals and never replacing them; the area it adds is "
    "measured by Sentinel-2, not by the radar. Classes and flows come from model/national_supply.s2_tier itself, run on "
    "the deep dive's own Sentinel-2 flags: green = the field's median seasonal-maximum NDVI above 0.40 (s2_winter_active "
    "over 1 Nov-31 Jan, s2_summer_active over 15 Jun-31 Oct; the national flags use 1 Nov-15 Mar and 10 Jun-31 Oct, so "
    "this winter window misses wheat that greens only in February-March). "
    "(a) Winter fill: a field the radar calls not farmed in either season (radar idle) that Sentinel-2 sees green in "
    "winter and not green in summer counts as winter-farmed. Fields the radar sees farmed in summer are not filled. "
    "(b) Season fill and (c) Sentinel-2-only fields fill nothing here: the radar observed both seasons on every deep "
    "field. "
    "(d) A filled field farmed in both seasons gets the year-round (perennial) depth only if the national spring check "
    "marks it perennial (not brown over 20 Apr-5 Jun) and Sentinel-2 sees it green in both windows; otherwise it is a "
    "rotation (winter plus summer depth). Palm groves among the filled fields: tree cover of 30% or more, farmed in "
    "every known season and not brown in spring; radar palm groves are never refilled. "
    "(e) Wheat straw on fields that are wheat-pattern only through Sentinel-2 is credited at the national run's straw "
    "factor for the field's administrative region (out/national_summary.json s2_filled.caps.by_region, Qassim), so the "
    "deep tier follows the national cap: the national cap (GASTAT 2024 wheat area minus the national radar wheat) goes "
    "first to the region's national fills (a)/(b), then to its fill (c), pro rata by area; straw_factor_seasons applies "
    "here to fills (a) and (b), straw_factor_s2_only to (c). The cap from the box's own radar wheat is kept as a "
    "diagnostic only. "
    "Water, energy and CO2 are not capped; energy uses the same pumping head as the radar-only totals. "
    "Checks (the run stops and writes nothing): the national function keeps the radar class of every field it does not "
    "fill, and its flows equal this module's on the same classes within one rounding unit; the cap entry's wheat areas "
    "equal those of data/national/fields_national.csv (the same national run), and the national flags were made from "
    "that table (its md5 in data/fields/national_flags.json).")


def load():
    raw = json.loads((ROOT / "model" / "params.json").read_text())
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def md5(path):
    return hashlib.md5(path.read_bytes()).hexdigest()


def check_lift(P, off):
    """Stop unless pumping_lift_m (model/params.json) equals the national run's lift for the deep box (lift_m.Qassim of
    data/national/official_2024.json) at every level: the same fields must get the same head on both pages."""
    nat = off["lift_m"][LIFT_KEY]
    bad = [f"{lv} {P['pumping_lift_m'][lv]} against {nat[lv]}" for lv in LV
           if float(P["pumping_lift_m"][lv]) != float(nat[lv])]
    if bad:
        raise SystemExit(f"model/params.json pumping_lift_m differs from data/national/official_2024.json "
                         f"lift_m.{LIFT_KEY} ({'; '.join(bad)} m): make them equal. Nothing written.")


def flags_meta():
    """data/fields/national_flags.json (scripts/transfer_national_flags.py): the md5 of the national table the flags came
    from, the match counts and the tree_frac_source codes. Stops unless it describes data/fields/national_flags.csv."""
    if not FLAGS_META.exists():
        raise SystemExit(f"{FLAGS_META_FILE} not found: re-run scripts/transfer_national_flags.py")
    meta = json.loads(FLAGS_META.read_text())
    if meta.get("csv_md5") != md5(FLAGS):
        raise SystemExit(f"{FLAGS_META_FILE} does not describe {FLAGS_FILE} (they come from different runs): re-run "
                         "scripts/transfer_national_flags.py")
    return meta


def add_classes(df, meta=None):
    """Add the national flags (meta = flags_meta(); None: run without them) and each field's class
    (model/national_supply.classify)."""
    if meta is not None:
        fl = pd.read_csv(FLAGS)
        chk = df[["id", "area_ha"]].merge(fl[["id", "area_ha"]], on="id", how="outer", suffixes=("", "_flags"))
        if len(chk) != len(df) or len(fl) != len(df) or not np.allclose(chk.area_ha, chk.area_ha_flags):
            raise SystemExit(f"{FLAGS_FILE} does not match the field table: run scripts/transfer_national_flags.py")
        codes = meta.get("tree_frac_source_codes", {})
        fl["tree_frac_source"] = fl.tree_frac_source.fillna("").map(lambda v: codes.get(v, v))  # short code -> name
        df = df.merge(fl[["id", "matched", "tree_frac", "tree_frac_source", "spring_brown"]], on="id", how="left")
    else:
        df["matched"], df["tree_frac"], df["tree_frac_source"], df["spring_brown"] = False, np.nan, "", np.nan
    df["tree_frac_source"] = df.tree_frac_source.fillna("")
    wa, sa = tri(df.winter_active), tri(df.summer_active)
    df["winter_active"], df["summer_active"], df["spring_brown"] = wa, sa, tri(df.spring_brown)
    df["radar_seen"] = wa.notna() | sa.notna()  # every deep-dive field has radar values in both seasons
    df["palm_grove"] = palm_rule(df)  # palms are evergreen: tree cover and active in every season observed
    df["class"] = df.apply(classify, axis=1)
    return df


def flows(df, P):
    """Per-field flows of a classified field table (class, area_ha, circularity) at low/central/high, under the national
    column names (water_m3_<lvl>, elec_kwh_<lvl>, elec_kwh_summer_<lvl>, co2_t_grid_<lvl>, co2_t_diesel_<lvl>,
    straw_t_dry_<lvl>, fronds_t_dry_<lvl>), each rounded as in data/supply.csv, the geometric pivot flag (is_pivot,
    palm groves included) and the pumping head (head_m_<lvl>, HEAD_RULE; no pivot pressure on palm groves). Returns df."""
    m2 = df.area_ha * 1e4
    cls = df["class"]
    df["is_pivot"] = is_pivot(df)
    pressured = pressure_pivots(df)  # model/national_supply.pressure_pivots: by this table's class
    conds = [cls == "winter_only", cls == "summer_only", cls == "wheat_rotation", cls.isin(["year_round", "palm_grove"])]
    for lvl, eff_lvl in (("low", "high"), ("central", "central"), ("high", "low")):
        win, smr, yr = (P["irrigation_mm_winter_only"][lvl], P["irrigation_mm_summer_crop"][lvl],
                        P["irrigation_mm_year_round"][lvl])
        mm = pd.Series(np.select(conds, [win, smr, win + smr, yr], 0.0), index=df.index)
        summer_share = pd.Series(np.select(conds, [0.0, 1.0, smr / (win + smr), 0.5], 0.0), index=df.index)
        water = mm / 1000 * m2 / P["pivot_application_efficiency"][eff_lvl]           # m3 pumped
        head = P["pumping_lift_m"][lvl] + P["drawdown_m"][lvl] + pressured * P["pivot_pressure_head_m"][lvl]
        work_kwh = water * RHO_G * head / 3.6e6                                         # water work
        elec_kwh = work_kwh / P["pump_wire_to_water_eff"][lvl]
        val = {"water_m3": water, "elec_kwh": elec_kwh, "elec_kwh_summer": elec_kwh * summer_share,
               "co2_t_grid": elec_kwh * P["grid_kgco2e_per_kwh"][lvl] / 1000,
               "co2_t_diesel": work_kwh / P["diesel_water_kwh_per_litre"][lvl] * P["diesel_kgco2e_per_litre"][lvl] / 1000,
               "straw_t_dry": cls.isin(WHEAT) * df.area_ha * P["straw_t_dry_per_ha"][lvl],
               "fronds_t_dry": (cls == "palm_grove") * df.area_ha * P["palms_per_ha"][lvl]
               * P["palm_residue_kg_dry_per_palm"][lvl] / 1000}
        for k, v in val.items():
            df[f"{k}_{lvl}"] = v.round(ROUND[k])
        df[f"head_m_{lvl}"] = head
    return df


def totals(df):
    """Totals of a classified, accounted field table under the names of model/national_supply.totals."""
    part = df["class"].str.startswith("partly_seen")
    farmed = df.winter_active.eq(True) | df.summer_active.eq(True)
    t = {"fields": int(len(df)), "field_ha": round(float(df.area_ha.sum())),
         "farmed_ha": round(float(df[farmed].area_ha.sum())),
         "area_ha_by_class": {k: float(v) for k, v in df.groupby("class").area_ha.sum().round().items()},
         "active_ha": {se: round(float(df[df[f"{se}_active"].eq(True)].area_ha.sum())) for se in SEASONS},
         "season_not_observed_ha": {se: round(float(df[part & df[f"{se}_active"].isna()].area_ha.sum())) for se in SEASONS},
         "wheat_ha": round(float(df[df["class"].isin(WHEAT)].area_ha.sum())),
         "year_round_ha": round(float(df[df["class"] == "year_round"].area_ha.sum()))}
    for k in FLOW_KEYS:
        t[k] = {lv: round(float(np.nansum(df[f"{k}_{lv}"])), 1) for lv in LV}
    # peak-season pumping load, averaged over Jun-Sep (122 days)
    t["summer_pumping_avg_mw"] = {lv: round(t["elec_kwh_summer"][lv] / (122 * 24) / 1000, 1) for lv in LV}
    return t


# ---------------------------------------------------------------- classification range (as national, audit nd-2)
def reflag(df, P, thr, shift_db):
    """Season flags re-derived from the stored seasonal peak HV above the desert median against each season's threshold
    shifted by shift_db (positive = stricter), with the palm and class rules, and the flows."""
    d = df.copy()
    for se in SEASONS:
        v = d[f"hv_above_desert_db_{se}"]
        d[f"{se}_active"] = (v > thr[se] + shift_db).astype(object).where(v.notna(), np.nan)
    d["radar_seen"] = d.winter_active.notna() | d.summer_active.notna()
    d["palm_grove"] = palm_rule(d)
    d["class"] = d.apply(classify, axis=1)
    return flows(d, P)


def classification_range(df, P, thr, base):
    """Totals with both desert thresholds shifted by -1 dB and +1 dB, the zero-shift check, and the corners of the
    combined factor x classification range (the keys of model/national_supply.classification_range)."""
    z = reflag(df, P, thr, 0.0)
    same = pd.Series(True, index=df.index)
    zero = {}
    for se in SEASONS:
        a, b = z[f"{se}_active"], tri(df[f"{se}_active"])
        eq = (a.isna() & b.isna()) | (a.notna() & b.notna() & (a == b))
        same &= eq
        zero[se] = {"share_identical": round(float(eq.mean()), 5), "fields_differ": int((~eq).sum()),
                    "ha_differ": round(float(df[~eq].area_ha.sum()), 1)}
    zt = totals(z)
    out = {"rule": "Both desert thresholds (out/background.json, unrounded) shifted by -1 dB (looser: more fields "
                   "active) and +1 dB (stricter: fewer) on the stored per-field seasonal peak HV above the desert "
                   "median; the same palm, class and accounting rules as the radar-only totals (including the pumping "
                   f"head: {HEAD_RULE}), at the same low/central/high factors. Shifting by 0 dB reproduces the "
                   "published flags.",
           "thresholds_db": {se: round(float(thr[se]), 4) for se in SEASONS},
           "shift_db": {"minus_1db": -1.0, "plus_1db": 1.0},
           "zero_shift_check": {"fields": int(len(df)), "fields_identical": int(same.sum()),
                                "share_identical": round(float(same.mean()), 5), "by_season": zero,
                                "farmed_ha": zt["farmed_ha"], "published_farmed_ha": base["farmed_ha"],
                                "water_m3_central": zt["water_m3"]["central"],
                                "published_water_m3_central": base["water_m3"]["central"]}}
    states = [base]
    for name, sh in (("minus_1db", -1.0), ("plus_1db", 1.0)):
        out[name] = totals(reflag(df, P, thr, sh))
        states.append(out[name])
    # combined range: lowest factor level in the classification state giving the least, highest in the most
    out["corners"] = {k: {"low": min(s[k]["low"] for s in states), "high": max(s[k]["high"] for s in states)}
                      for k in (*FLOW_KEYS, "summer_pumping_avg_mw")}
    out["corners_rule"] = ("low = minimum over {-1 dB, published, +1 dB} of the low-factor total; high = maximum of the "
                           "high-factor total")
    return out


# ---------------------------------------------------------------- radar + Sentinel-2 tier (national, audits nd-8, nd-9)
def region_key(admin, off):
    """official_2024.json's key of an administrative region (the key of the national summary's per-region tables)."""
    o = off["regions"].get(admin)
    return o["key"] if o else admin


def national_caps(df, off, table_md5, meta):
    """The national run's wheat-straw cap entry for each administrative region of the deep fields
    (out/national_summary.json s2_filled.caps.by_region[key]; Qassim here), for S2_RULE (e). Stops unless the entry's
    wheat areas (GASTAT, radar wheat, and the area that is wheat-pattern only through Sentinel-2, in fills (a)/(b) and
    in (c)) equal those of data/national/fields_national.csv, so the summary and the table come from the same national
    run, and, with the national flags (meta), unless the flags were made from that table. Returns {key: entry}."""
    for p in (NATIONAL_SUMMARY, NATIONAL_TABLE):
        if not p.exists():
            raise SystemExit(f"{p.relative_to(ROOT)} not found: run model/national_supply.py. Nothing written.")
    if meta is not None and meta["national_table_md5"] != table_md5:
        raise SystemExit(f"{FLAGS_FILE} was made from a national table (md5 {meta['national_table_md5']}) other than the "
                         f"current data/national/fields_national.csv (md5 {table_md5}), whose run gives the straw cap: "
                         "re-run scripts/transfer_national_flags.py. Nothing written.")
    by = json.loads(NATIONAL_SUMMARY.read_text()).get("s2_filled", {}).get("caps", {}).get("by_region", {})
    nat = pd.read_csv(NATIONAL_TABLE, usecols=["admin", "area_ha", "class", "class_s2", "s2_fill"], low_memory=False)
    s2w = nat.class_s2.isin(WHEAT) & ~nat["class"].isin(WHEAT)  # wheat-pattern only through Sentinel-2
    fc = nat.s2_fill.eq("s2_only")
    out = {}
    for adm in sorted(set(df.admin)):
        key, o = region_key(adm, off), off["regions"].get(adm)
        e = by.get(key)
        if e is None:
            raise SystemExit(f"out/national_summary.json has no s2_filled.caps.by_region.{key}: re-run "
                             "model/national_supply.py. Nothing written.")
        x = nat.admin.eq(adm)
        areas = {"gastat_wheat_ha": float(o["wheat_ha"]) if o else 0.0,
                 "radar_wheat_ha": float(nat.area_ha[x & nat["class"].isin(WHEAT)].sum()),
                 "s2_wheat_ha_seasons": float(nat.area_ha[x & s2w & ~fc].sum()),
                 "s2_wheat_ha_s2_only": float(nat.area_ha[x & s2w & fc].sum())}
        bad = [f"{k} {e.get(k)} in the summary, {v:,.0f} in the table" for k, v in areas.items()
               if not isinstance(e.get(k), (int, float)) or abs(e[k] - v) > 1.0]
        if bad:
            raise SystemExit(f"out/national_summary.json and data/national/fields_national.csv come from different "
                             f"national runs ({key}: {'; '.join(bad)}): re-run model/national_supply.py. Nothing written.")
        out[key] = e
    return out


def check_same_rules(df, comb, P):
    """Stop when model/national_supply.s2_tier, run on the deep table, disagrees with this module's rules: it must keep
    the radar-only class of every field it does not fill, and its flows for every field must equal this module's flows
    on the same classes within one rounding unit (TOL). A mismatch means the two modules' rules have drifted apart
    (pumping head, depths, pivot or palm rule), and the tier would no longer be comparable with the radar-only totals."""
    bad = []
    n = int((comb.s2_fill.eq("") & comb["class"].ne(df["class"])).sum())
    if n:
        bad.append(f"{n} fields it does not fill change class")
    ref = flows(comb[["class", "area_ha", "circularity"]].copy(), P)
    for k in (*FLOW_KEYS, "head_m"):
        for lv in LV:
            col = f"straw_t_dry_uncapped_{lv}" if k == "straw_t_dry" else f"{k}_{lv}"
            d = float((comb[col].astype(float) - ref[f"{k}_{lv}"]).abs().max())
            if not d <= TOL[k] + 1e-9:  # NaN fails too
                bad.append(f"{k}_{lv} differs by up to {d:g}")
    if bad:
        raise SystemExit("model/national_supply.s2_tier and model/supply.py disagree on the deep table (their rules have "
                         f"drifted apart): {'; '.join(bad)}. Nothing written.")


def s2_tier(df, P, off, nat_caps):
    """Radar + Sentinel-2 tier: model/national_supply.s2_tier itself on a copy of the classified, accounted deep table
    (no Arabian Shield fields; region tag 'deep'), checked against this module's rules (check_same_rules), with the
    national run's straw factors (nat_caps = national_caps()) in place of the cap the national function computes from
    the box's own radar wheat. Returns (comb, seasons, masks, caps, box_caps): the first three as the national function
    returns them; caps = the applied cap per region; box_caps = the national function's box-only cap (diagnostic)."""
    comb, seasons, masks, box_caps = SUP.s2_tier(df.assign(shield=False, region="deep"), P, off)
    check_same_rules(df, comb, P)
    base, fc = df["class"], masks["c"]
    key = df.admin.map(lambda a: region_key(a, off))
    for d in (comb, seasons):  # seasons: the fields of fill (c) keep their radar class, so get no factor
        s2w = d["class"].isin(WHEAT) & ~base.isin(WHEAT)  # wheat-pattern only through Sentinel-2
        factor = pd.Series(1.0, index=d.index)
        for k in sorted(set(key)):
            for m, f in ((s2w & ~fc & key.eq(k), "straw_factor_seasons"), (s2w & fc & key.eq(k), "straw_factor_s2_only")):
                if m.any():
                    if nat_caps[k][f] is None:
                        raise SystemExit(f"the deep tier has Sentinel-2 wheat where the national run has none to cap "
                                         f"({k} {f} is null in out/national_summary.json). Nothing written.")
                    factor[m] = float(nat_caps[k][f])
        d["straw_cap_factor"] = factor.where(s2w, np.nan)
        for lv in LV:
            d[f"straw_t_dry_{lv}"] = (d[f"straw_t_dry_uncapped_{lv}"] * factor).round(1)
    s2w = comb["class"].isin(WHEAT) & ~base.isin(WHEAT)
    caps = {}
    for k in sorted(set(key)):
        e = nat_caps[k]
        f1, f2 = e.get("straw_factor_seasons"), e.get("straw_factor_s2_only")
        a1 = float(comb.area_ha[s2w & ~fc & key.eq(k)].sum())
        a2 = float(comb.area_ha[s2w & fc & key.eq(k)].sum())
        caps[k] = {"factor_source": f"out/national_summary.json s2_filled.caps.by_region.{k}",
                   "straw_factor_seasons": f1, "straw_factor_s2_only": f2,
                   "s2_wheat_ha_seasons": round(a1), "credited_ha_seasons": round(a1 * f1) if a1 else 0,
                   "s2_wheat_ha_s2_only": round(a2), "credited_ha_s2_only": round(a2 * f2) if a2 else 0,
                   "national": e}
    return comb, seasons, masks, caps, box_caps


def s2_summary(df, comb, seasons, masks, caps, box_caps, off, P):
    """The 's2_filled' block, with the keys of model/national_supply.s2_summary (vs_official only for the regions the
    deep dive has fields in)."""
    fa, fbw, fbs, fc = masks["a"], masks["bw"], masks["bs"], masks["c"]
    filled = comb.s2_fill.ne("")
    yr2, rot2 = filled & comb["class"].eq("year_round"), filled & comb["class"].eq("wheat_rotation")
    # rotations that the radar rule would call year-round (spring not brown) but Sentinel-2 does not see green in both
    s2w, s2s = tri(df.s2_winter_active), tri(df.s2_summer_active)
    strict = rot2 & tri(df.spring_brown).eq(False) & ~(s2w.eq(True) & s2s.eq(True))
    eff = {"low": "high", "central": "central", "high": "low"}

    def extra_mm(lv):  # perennial depth over rotation depth (winter + summer crop)
        return P["irrigation_mm_year_round"][lv] - P["irrigation_mm_winter_only"][lv] - P["irrigation_mm_summer_crop"][lv]

    def credited(x):
        s2 = x["class"].isin(WHEAT) & x.straw_cap_factor.notna()
        return round(float(x[x["class"].isin(WHEAT) & ~s2].area_ha.sum() + (x.area_ha * x.straw_cap_factor)[s2].sum()))

    def tier(d, scope, sub=None):
        x = d if sub is None else d[sub]
        t = {"scope": scope, **totals(x)}
        f = x.s2_fill.ne("")
        t["s2_filled_fields"], t["s2_filled_ha"] = int(f.sum()), round(float(x[f].area_ha.sum()))
        t["straw_t_dry_uncapped"] = {lv: round(float(x[f"straw_t_dry_uncapped_{lv}"].sum()), 1) for lv in LV}
        t["wheat_ha_straw_credited"] = credited(x)
        return t

    def cls_ha(m):
        return {k: round(float(v)) for k, v in df[m].groupby("class").area_ha.sum().items()}

    piv = df.is_pivot.astype(bool)
    pb, fl = masks["palm_spring_brown"], masks["a_summer_active"]
    fills = {"winter_fill": {"rule": "radar idle only: winter and summer observed and not active; Sentinel-2 green over "
                                     "1 Nov-31 Jan and not over 15 Jun-31 Oct",
                             "fields": int(fa.sum()), "ha": round(float(df[fa].area_ha.sum())), "by_radar_class": cls_ha(fa),
                             "in_shield_ha": 0, "pivots_ha": round(float(df[fa & piv].area_ha.sum())),
                             "radar_summer_active_not_filled": {"fields": int(fl.sum()), "ha": round(float(df[fl].area_ha.sum())),
                                                                "by_radar_class": cls_ha(fl)}},
             "season_fill": {se: {"fields": int(m.sum()), "ha": round(float(df[m].area_ha.sum())),
                                  "s2_green_ha": round(float(df[m & tri(df[f"s2_{se}_active"]).eq(True)].area_ha.sum()))}
                             for se, m in (("winter", fbw), ("summer", fbs))},
             "s2_only": {"fields": int(fc.sum()), "ha": round(float(df[fc].area_ha.sum())), "by_radar_class": cls_ha(fc),
                         "by_region": {}},
             "palm_spring_check": {"rule": "filled fields become palm groves only if not brown in spring; these fields "
                                           "met the other palm conditions but are brown in spring",
                                   "fields": int(pb.sum()), "ha": round(float(df[pb].area_ha.sum())),
                                   "palm_ha_filled": round(float(comb[filled & comb["class"].eq("palm_grove") & ~fc].area_ha.sum())),
                                   "palm_ha_s2_only": round(float(comb[fc & comb["class"].eq("palm_grove")].area_ha.sum()))},
             "filled_two_season": {
                 "year_round_ha": round(float(comb[yr2].area_ha.sum())),
                 "year_round_ha_by_fill": {k: round(float(v)) for k, v in comb[yr2].groupby("s2_fill").area_ha.sum().items()},
                 "wheat_rotation_ha": round(float(comb[rot2].area_ha.sum())),
                 "spring_not_brown_but_not_green_in_both_windows_ha": round(float(comb[strict].area_ha.sum())),
                 "year_round_extra_water_m3_over_rotation": {
                     lv: round(float(comb[yr2].area_ha.sum()) * 1e4 * extra_mm(lv) / 1000 / P["pivot_application_efficiency"][eff[lv]])
                     for lv in LV},
                 "note": "filled fields farmed in both seasons: year-round (perennial) depth where the spring check "
                         "marks them perennial and Sentinel-2 sees them green in both windows, rotation depth "
                         "otherwise; year_round_extra_water_m3_over_rotation is what the perennial depth adds over "
                         "treating every one of them as a rotation"},
             "not_applicable": "season_fill and s2_only are empty: the radar observed both seasons on every deep field"}
    cap_tot = {"rule": "per administrative region, the national run's straw factors (out/national_summary.json "
                       "s2_filled.caps.by_region, as published to 4 decimals; 'national' is that entry for the whole "
                       "region): national cap = max(0, GASTAT 2024 wheat area - the national radar wheat-pattern area "
                       "(winter-only + rotation)), shared pro rata over the national Sentinel-2-filled wheat-pattern "
                       "area, first fills (a)/(b) (straw_factor_seasons), then Sentinel-2-only fields "
                       "(straw_factor_s2_only). The deep dive's Sentinel-2-filled wheat-pattern area is credited with "
                       "straw at those factors (credited_ha_*). Checked against data/national/fields_national.csv, the "
                       "table the national flags came from",
               "by_region": caps,
               "box_only_diagnostic": {"rule": "not applied: the cap model/national_supply.s2_tier computes on the deep "
                                               "table alone, GASTAT 2024 wheat of the whole region minus the deep dive's "
                                               "radar wheat-pattern area; the box is a small part of the region, so this "
                                               "cap barely binds",
                                       "by_region": box_caps},
               "effect": {name: {"straw_t_dry_uncapped": {lv: round(float(d[f"straw_t_dry_uncapped_{lv}"].sum()), 1) for lv in LV},
                                 "straw_t_dry_capped": {lv: round(float(d[f"straw_t_dry_{lv}"].sum()), 1) for lv in LV},
                                 "s2_wheat_ha": round(float(d[d.straw_cap_factor.notna()].area_ha.sum())),
                                 "s2_wheat_ha_credited": round(float((d.area_ha * d.straw_cap_factor).sum()))}
                          for name, d in (("radar_plus_s2_seasons", seasons), ("combined", comb))},
               "regions_capped": sorted(k for k, v in caps.items() if (v["s2_wheat_ha_seasons"] + v["s2_wheat_ha_s2_only"])
                                        > v["credited_ha_seasons"] + v["credited_ha_s2_only"] + 0.5)}
    rows, over = [], []
    for adm in sorted(set(df.admin)):
        o = off["regions"].get(adm)
        if not o:
            continue
        r = {"region": o["key"], "gastat_wheat_ha": o["wheat_ha"], "gastat_fodder_ha": o["fodder_ha"],
             "mewa_agri_groundwater_m3": o["agri_groundwater_m3"]}
        for tag, d in (("radar", df), ("seasons", seasons), ("combined", comb)):
            x = d[d.admin == adm]
            r[f"{tag}_wheat_ha"] = round(float(x[x["class"].isin(WHEAT)].area_ha.sum()))
            if tag != "radar":
                r[f"{tag}_wheat_credited_ha"] = credited(x)
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
    n = len(comb)
    return {"rule": S2_RULE,
            "radar_plus_s2_seasons": tier(seasons, f"all {n:,} deep-dive fields: radar classes with the winter fill (a); "
                                                   "fills (b) and (c) do not occur here"),
            "s2_only_fields": tier(comb, "only the fields of fill (c), classified from Sentinel-2 alone: none in the "
                                         "deep dive (every field has radar values in both seasons)", fc),
            "combined": tier(comb, f"all {n:,} deep-dive fields with every fill; equal to radar_plus_s2_seasons, as "
                                   "fill (c) is empty"),
            "caps": cap_tot,
            "fills": fills,
            "vs_official": {"rule": "each administrative region's tier totals against GASTAT 2024 wheat and fodder "
                                    "(year-round fields) and MEWA 2024 agricultural groundwater for the whole region; the "
                                    "deep-dive box covers a small part of it. wheat_ha is the uncapped wheat pattern; "
                                    "*_wheat_credited_ha is the area credited with straw after the cap. Water: "
                                    "[low, central, high]",
                            "regions": rows, "overshoots": over}}


def national_flags_block(df, meta, table_md5, nosp):
    """The national flags used: files, the md5 of the national table they came from (national_flags.json) and whether
    it is the current data/national/fields_national.csv, matches, tree-cover sources and palm groves."""
    matched = df.matched.fillna(False).astype(bool)
    out = {"file": FLAGS_FILE if meta else None, "meta_file": FLAGS_META_FILE if meta else None,
           "national_table_md5": meta["national_table_md5"] if meta else None, "national_table_current": None}
    if meta and table_md5:
        out["national_table_current"] = meta["national_table_md5"] == table_md5
        if not out["national_table_current"]:
            print(f"note: {FLAGS_FILE} was made from a national table (md5 {meta['national_table_md5']}) other than the "
                  "current data/national/fields_national.csv: re-run scripts/transfer_national_flags.py")
    src = df.tree_frac_source.replace("", "none")
    palm = df["class"] == "palm_grove"
    out |= {"matched_fields": int(matched.sum()), "matched_ha": round(float(df.loc[matched, "area_ha"].sum())),
            "unmatched_fields": int((~matched).sum()), "unmatched_ha": round(float(df.loc[~matched, "area_ha"].sum())),
            "two_season_no_spring_check": {"fields": int(nosp.sum()), "ha": round(float(df.loc[nosp, "area_ha"].sum()))},
            "tree_frac_source": {k: int(v) for k, v in src.value_counts().items()},
            "palm_grove": {"fields": int(palm.sum()), "ha": round(float(df.loc[palm, "area_ha"].sum())),
                           "unmatched_fields": int((palm & ~matched).sum()),
                           "unmatched_ha": round(float(df.loc[palm & ~matched, "area_ha"].sum()))}}
    return out


def depth_age_sensitivity(df, P):
    """What the water-level decline since pumping_lift_m was measured (DEPTH_YEAR) would add to the radar-only pumping
    electricity: DECLINE_M_PER_YR x the years to SEASON_YEAR of extra head on every field's pumped water, at each level's
    pump efficiency, in GWh a year and as a share of elec_kwh. In no total."""
    yrs = SEASON_YEAR - DEPTH_YEAR
    dh = [r * yrs for r in DECLINE_M_PER_YR]
    gwh, share = {}, {}
    for lv in LV:
        w, e = float(df[f"water_m3_{lv}"].sum()), float(df[f"elec_kwh_{lv}"].sum())
        kwh = [w * RHO_G * h / 3.6e6 / P["pump_wire_to_water_eff"][lv] for h in dh]
        gwh[lv] = [round(x / 1e6, 1) for x in kwh]
        share[lv] = [round(x / e, 4) if e else None for x in kwh]
    c, s = gwh["central"], share["central"]
    note = (f"This box's depth to water (pumping_lift_m) was measured at Buraidah in {DEPTH_YEAR}. At a decline of "
            f" {DECLINE_M_PER_YR[0]:g}-{DECLINE_M_PER_YR[1]:g} m a year ({DECLINE_SOURCE}) the water would be "
            f"{dh[0]:g}-{dh[1]:g} m deeper by {SEASON_YEAR}, which would add {c[0]:,.0f}-{c[1]:,.0f} GWh a year "
            f"(+{s[0]:.0%} to +{s[1]:.0%}) to the central pumping electricity; this is in no total")
    return {"rule": f"extra head = decline rate x {yrs} years ({DEPTH_YEAR}-{SEASON_YEAR}) on every field's pumped water, "
                    "electricity = water x rho g x extra head / pump_wire_to_water_eff at each level; share = that "
                    "electricity over the radar-only elec_kwh at the same level; [slow, fast] decline",
            "note": note, "depth_year": DEPTH_YEAR, "season_year": SEASON_YEAR,
            "decline_m_per_yr": list(DECLINE_M_PER_YR), "decline_source": DECLINE_SOURCE, "extra_head_m": dh,
            "extra_elec_gwh": gwh, "extra_share_of_elec_kwh": share}


def pumping_head_block(df, P, off):
    """The head behind the electricity, CO2 and MW totals, with the keys of the national summary's pumping_head, plus
    pumping_lift_m and the deep box's depth-age sensitivity."""
    piv = pressure_pivots(df)                      # pivots that carry pivot pressure
    palm = df.is_pivot.astype(bool) & ~piv         # pivot-shaped palm groves: no pivot pressure
    comp = {c: {} for c in ("static_depth", "drawdown", "pivot_pressure")}
    mean_head, piv_share, palm_kwh = {}, {}, {}
    for lv in LV:
        w = df[f"water_m3_{lv}"]
        k = RHO_G / 3.6e6 / P["pump_wire_to_water_eff"][lv]
        comp["static_depth"][lv] = round(float(w.sum()) * P["pumping_lift_m"][lv] * k)
        comp["drawdown"][lv] = round(float(w.sum()) * P["drawdown_m"][lv] * k)
        comp["pivot_pressure"][lv] = round(float(w[piv].sum()) * P["pivot_pressure_head_m"][lv] * k)
        palm_kwh[lv] = round(float(w[palm].sum()) * P["pivot_pressure_head_m"][lv] * k)
        tot = float(w.sum())
        mean_head[lv] = round(float((w * df[f"head_m_{lv}"]).sum()) / tot, 1) if tot else None
        piv_share[lv] = round(float(w[piv].sum()) / tot, 4) if tot else None
    age = depth_age_sensitivity(df, P)
    # depth_age: this box's own sensitivity; national_lift_table_age: the national lift table's note on the age of all
    # its depths (measured 1979-2009), with national figures
    notes = {"depth_age": age.pop("note")}
    if isinstance(off["lift_m"].get("_age"), str):
        notes["national_lift_table_age"] = "National lift table (all regions, national figures): " + off["lift_m"]["_age"]
    return {"rule": HEAD_RULE, "detail": HEAD_DETAIL, "pivot_rule": PIVOT_RULE,
            **{k: {lv: P[k][lv] for lv in LV} for k in ("pumping_lift_m", "drawdown_m", "pivot_pressure_head_m")},
            "notes": notes, "depth_age_sensitivity": age,
            "pivot_fields": int(piv.sum()), "pivot_ha": round(float(df[piv].area_ha.sum())),
            "pivot_share_of_pumped_water": piv_share,
            "palm_grove_pivots": {"rule": "pivot-shaped palm groves (is_pivot, class palm_grove) get no pivot pressure; "
                                          "pressure_elec_kwh_not_charged is what the pivot pressure head would add on "
                                          "their water (in no total)",
                                  "fields": int(palm.sum()), "ha": round(float(df[palm].area_ha.sum())),
                                  "pressure_elec_kwh_not_charged": palm_kwh},
            "mean_head_m": mean_head,
            "elec_kwh_by_component": comp,
            "components_rule": "the electricity split by head component (the three add up to elec_kwh, up to the "
                               "rounding of each field's electricity); pivot_fields, pivot_ha and "
                               "pivot_share_of_pumped_water count the pivots that carry pivot pressure (pivot_rule: palm "
                               "groves left out); mean_head_m and pivot_share_of_pumped_water are weighted by pumped water"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["s2", "radar"], default="s2")
    ap.add_argument("--no-national-flags", action="store_true",
                    help=f"run without {FLAGS_FILE}: no palm class, and fields farmed in both seasons stay year-round "
                         "(the rule before the national flags)")
    a = ap.parse_args()
    P = load()
    off = json.loads(OFFICIAL.read_text())
    check_lift(P, off)
    if a.source == "s2":
        df = pd.read_csv(ROOT / "data" / "fields" / "fields.csv")
        df["winter_active"], df["summer_active"] = df.s2_winter_active, df.s2_summer_active
    else:
        df = pd.read_csv(ROOT / "data" / "fields" / "fields_radar.csv")
    use_flags = FLAGS.exists() and not a.no_national_flags
    if not FLAGS.exists() and not a.no_national_flags:
        if a.source == "radar":
            raise SystemExit(f"{FLAGS_FILE} not found: run scripts/transfer_national_flags.py first, or pass "
                             "--no-national-flags for the rule without the national flags (no palm class; fields "
                             "farmed in both seasons stay year-round)")
        print(f"{FLAGS_FILE} not found (scripts/transfer_national_flags.py): no palm class, and fields farmed in "
              "both seasons stay year-round")
    elif a.no_national_flags:
        print("--no-national-flags: no palm class, and fields farmed in both seasons stay year-round")
    meta = flags_meta() if use_flags else None
    df = add_classes(df, meta)
    both = df.winter_active.eq(True) & df.summer_active.eq(True) & ~df.palm_grove
    nosp = both & df.spring_brown.isna()
    if nosp.any():
        print(f"spring check missing for {int(nosp.sum())} two-season fields ({df[nosp].area_ha.sum():,.0f} ha), "
              "counted as year-round")
    df = flows(df, P)

    out = df[["id", "lon", "lat", "area_ha", "class"]].copy()
    for lvl in LV:
        for k in ("water_m3", "elec_kwh", "elec_kwh_summer", "co2_t_grid", "co2_t_diesel", "straw_t_dry"):
            out[f"{DEEP_NAME.get(k, k)}_{lvl}"] = df[f"{k}_{lvl}"]
    out["residue_t_dry"] = out["residue_t_dry_central"]
    for lvl in LV:  # palm fronds, as model/national_supply.flows; a second feed in model/siting.py
        out[f"fronds_t_dry_{lvl}"] = df[f"fronds_t_dry_{lvl}"]
    out["is_pivot"] = df.is_pivot.astype(bool)

    base = totals(df)
    summ = {"source": a.source, "fields": int(len(out)),
            "area_ha_by_class": out.groupby("class").area_ha.sum().round(0).to_dict(),
            "fields_by_class": {k: int(v) for k, v in out.groupby("class").size().items()}}
    for k in ("water_m3", "elec_kwh", "elec_kwh_summer", "co2_t_electric", "co2_t_diesel", "residue_t_dry", "fronds_t_dry"):
        summ[k] = {lvl: float(out[f"{k}_{lvl}"].sum()) for lvl in LV}
    # the same totals under the national names (out/national_summary.json)
    for k in ("field_ha", "farmed_ha", "active_ha", "season_not_observed_ha", "wheat_ha", "year_round_ha", "co2_t_grid",
              "straw_t_dry", "summer_pumping_avg_mw"):
        summ[k] = base[k]
    table_md5 = md5(NATIONAL_TABLE) if NATIONAL_TABLE.exists() else None
    summ["pumping_head"] = pumping_head_block(df, P, off)
    summ["national_flags"] = national_flags_block(df, meta, table_md5, nosp)
    summ["classification_range"] = summ["s2_filled"] = None
    if a.source == "radar":
        thr = json.loads((ROOT / "out" / "background.json").read_text())["hv_threshold_db"]
        summ["classification_range"] = classification_range(df, P, thr, base)
        df = admin_regions(df)
        nat_caps = national_caps(df, off, table_md5, meta)
        comb, seasons, masks, caps, box_caps = s2_tier(df, P, off, nat_caps)
        summ["s2_filled"] = s2_summary(df, comb, seasons, masks, caps, box_caps, off, P)
    # every check has passed: write both outputs
    out.to_csv(ROOT / "data" / "supply.csv", index=False)
    (ROOT / "out").mkdir(exist_ok=True)
    (ROOT / "out" / "supply_summary.json").write_text(json.dumps(summ, indent=2))
    print(json.dumps({k: v for k, v in summ.items() if k not in ("classification_range", "s2_filled", "pumping_head")},
                     indent=2))
    ph = summ["pumping_head"]
    print(f"pumping head ({HEAD_RULE}): mean {ph['mean_head_m']['central']} m central; pivots with pressure "
          f"{ph['pivot_ha']:,} ha, {ph['pivot_share_of_pumped_water']['central']:.1%} of pumped water (pivot-shaped palm "
          f"groves without it: {ph['palm_grove_pivots']['ha']:,} ha); {ph['notes']['depth_age']}")
    cr, s2 = summ["classification_range"], summ["s2_filled"]
    if cr:
        print("classification range (-1 dB / published / +1 dB): farmed ha", cr["minus_1db"]["farmed_ha"],
              base["farmed_ha"], cr["plus_1db"]["farmed_ha"], "| water Mm3 central",
              round(cr["minus_1db"]["water_m3"]["central"] / 1e6, 1), round(base["water_m3"]["central"] / 1e6, 1),
              round(cr["plus_1db"]["water_m3"]["central"] / 1e6, 1), "| zero-shift identical",
              cr["zero_shift_check"]["share_identical"])
    if s2:
        t = s2["combined"]
        fac = ", ".join(f"{k} {v['straw_factor_seasons']}" for k, v in s2["caps"]["by_region"].items())
        print(f"s2 tier: winter fill {s2['fills']['winter_fill']['fields']} fields ({s2['fills']['winter_fill']['ha']:,} ha); "
              f"farmed {t['farmed_ha']:,} ha, wheat {t['wheat_ha']:,} ha (credited {t['wheat_ha_straw_credited']:,}), "
              f"water {t['water_m3']['central'] / 1e6:,.1f} Mm3, straw {t['straw_t_dry']['central']:,.0f} t "
              f"(uncapped {t['straw_t_dry_uncapped']['central']:,.0f}; national straw factor {fac})")


if __name__ == "__main__":
    main()
