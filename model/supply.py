"""Per-field water, pumping energy, CO2 and collectable straw, with low/central/high ranges.

Input  data/fields.csv-like table with: id, lon, lat, area_ha, winter_active, summer_active
       (default: data/fields/fields.csv using the Sentinel-2 columns; pass --source radar
        once data/fields/fields_radar.csv exists)
Output data/supply.csv  (one row per field; used by model/siting.py)
       out/supply_summary.json

Field classes (irrigation depths and summer shares as in model/national_supply.py)
  winter_only    -> seasonal crop, treated as wheat (winter depth; straw collectable)
  summer_only    -> seasonal summer crop (summer-crop depth; no sourced straw factor, so 0)
  wheat_rotation -> wheat, then a summer crop (winter + summer depth; straw collectable). Needs a
                    spring_brown column (Sentinel-2 spring check, scripts/s2_spring.py); the deep dive
                    has none, so its fields active in both seasons stay year_round
  year_round     -> perennial fodder, mostly alfalfa (perennial depth; residue not collectable)
  idle           -> not farmed this year
elec_kwh_summer_<lvl> is the June-September share of pumping electricity: all of a summer crop's,
summer / (winter + summer) of a rotation's, half of a perennial field's.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RHO_G = 1000 * 9.81  # N per m3 per m of lift


def load():
    raw = json.loads((ROOT / "model" / "params.json").read_text())
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def classify(w, s, spring_brown=None):
    if w and s:
        # brown in late spring (Sentinel-2) = wheat harvested, then a summer crop
        return "wheat_rotation" if spring_brown == True else "year_round"  # noqa: E712 (NaN-safe)
    if w:
        return "winter_only"
    if s:
        return "summer_only"
    return "idle"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["s2", "radar"], default="s2")
    a = ap.parse_args()
    P = load()
    if a.source == "s2":
        df = pd.read_csv(ROOT / "data" / "fields" / "fields.csv")
        df["winter_active"], df["summer_active"] = df.s2_winter_active, df.s2_summer_active
    else:
        df = pd.read_csv(ROOT / "data" / "fields" / "fields_radar.csv")
    spring = df["spring_brown"] if "spring_brown" in df else pd.Series(None, index=df.index, dtype=object)
    df["class"] = [classify(w, s, b) for w, s, b in zip(df.winter_active, df.summer_active, spring)]

    out = df[["id", "lon", "lat", "area_ha", "class"]].copy()
    m2 = df.area_ha * 1e4
    cls = df["class"]
    conds = [cls == "winter_only", cls == "summer_only", cls == "wheat_rotation", cls == "year_round"]
    for lvl, eff_lvl, lift_lvl in (("low", "high", "low"), ("central", "central", "central"), ("high", "low", "high")):
        win, smr, yr = (P["irrigation_mm_winter_only"][lvl], P["irrigation_mm_summer_crop"][lvl],
                        P["irrigation_mm_year_round"][lvl])
        mm = pd.Series(np.select(conds, [win, smr, win + smr, yr], 0.0), index=df.index)
        summer_share = pd.Series(np.select(conds, [0.0, 1.0, smr / (win + smr), 0.5], 0.0), index=df.index)
        water = mm / 1000 * m2 / P["pivot_application_efficiency"][eff_lvl]           # m3 pumped
        work_kwh = water * RHO_G * P["pumping_lift_m"][lift_lvl] / 3.6e6                # water work
        elec_kwh = work_kwh / P["pump_wire_to_water_eff"][lvl]
        out[f"water_m3_{lvl}"] = water.round(0)
        out[f"elec_kwh_{lvl}"] = elec_kwh.round(0)
        out[f"elec_kwh_summer_{lvl}"] = (elec_kwh * summer_share).round(0)
        out[f"co2_t_electric_{lvl}"] = (elec_kwh * P["grid_kgco2e_per_kwh"][lvl] / 1000).round(2)
        out[f"co2_t_diesel_{lvl}"] = (work_kwh / P["diesel_water_kwh_per_litre"][lvl] * P["diesel_kgco2e_per_litre"][lvl] / 1000).round(2)
        straw = cls.isin(["winter_only", "wheat_rotation"]) * df.area_ha * P["straw_t_dry_per_ha"][lvl]
        out[f"residue_t_dry_{lvl}"] = straw.round(1)
    out["residue_t_dry"] = out["residue_t_dry_central"]
    out.to_csv(ROOT / "data" / "supply.csv", index=False)

    summ = {"source": a.source, "fields": int(len(out)),
            "area_ha_by_class": out.groupby("class").area_ha.sum().round(0).to_dict()}
    for k in ("water_m3", "elec_kwh", "elec_kwh_summer", "co2_t_electric", "co2_t_diesel", "residue_t_dry"):
        summ[k] = {lvl: float(out[f"{k}_{lvl}"].sum()) for lvl in ("low", "central", "high")}
    (ROOT / "out").mkdir(exist_ok=True)
    (ROOT / "out" / "supply_summary.json").write_text(json.dumps(summ, indent=2))
    print(json.dumps(summ, indent=2))


if __name__ == "__main__":
    main()
