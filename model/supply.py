"""Per-field water, pumping energy, CO2 and collectable straw, with low/central/high ranges.

Input  data/fields.csv-like table with: id, lon, lat, area_ha, winter_active, summer_active
       (default: data/fields/fields.csv using the Sentinel-2 columns; pass --source radar
        once data/fields/fields_radar.csv exists)
Output data/supply.csv  (one row per field; used by model/siting.py)
       out/supply_summary.json

Field classes
  winter_only  -> seasonal crop, treated as wheat (straw collectable)
  summer_only  -> seasonal summer crop (water counted; no sourced straw factor, so 0)
  year_round   -> perennial fodder, mostly alfalfa (water counted; residue not collectable)
  idle         -> not farmed this year
"""
import argparse
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RHO_G = 1000 * 9.81  # N per m3 per m of lift


def load():
    raw = json.loads((ROOT / "model" / "params.json").read_text())
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def classify(w, s):
    if w and s:
        return "year_round"
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
    df["class"] = [classify(w, s) for w, s in zip(df.winter_active, df.summer_active)]

    out = df[["id", "lon", "lat", "area_ha", "class"]].copy()
    m2 = df.area_ha * 1e4
    for lvl, eff_lvl, lift_lvl in (("low", "high", "low"), ("central", "central", "central"), ("high", "low", "high")):
        mm = df["class"].map({
            "winter_only": P["irrigation_mm_winter_only"][lvl],
            "summer_only": P["irrigation_mm_winter_only"][lvl],
            "year_round": P["irrigation_mm_year_round"][lvl],
            "idle": 0,
        })
        water = mm / 1000 * m2 / P["pivot_application_efficiency"][eff_lvl]           # m3 pumped
        work_kwh = water * RHO_G * P["pumping_lift_m"][lift_lvl] / 3.6e6                # water work
        elec_kwh = work_kwh / P["pump_wire_to_water_eff"][lvl]
        out[f"water_m3_{lvl}"] = water.round(0)
        out[f"elec_kwh_{lvl}"] = elec_kwh.round(0)
        out[f"co2_t_electric_{lvl}"] = (elec_kwh * P["grid_kgco2e_per_kwh"][lvl] / 1000).round(2)
        out[f"co2_t_diesel_{lvl}"] = (work_kwh / P["diesel_water_kwh_per_litre"][lvl] * P["diesel_kgco2e_per_litre"][lvl] / 1000).round(2)
        straw = (df["class"] == "winter_only") * df.area_ha * P["straw_t_dry_per_ha"][lvl]
        out[f"residue_t_dry_{lvl}"] = straw.round(1)
    out["residue_t_dry"] = out["residue_t_dry_central"]
    out.to_csv(ROOT / "data" / "supply.csv", index=False)

    summ = {"source": a.source, "fields": int(len(out)),
            "area_ha_by_class": out.groupby("class").area_ha.sum().round(0).to_dict()}
    for k in ("water_m3", "elec_kwh", "co2_t_electric", "co2_t_diesel", "residue_t_dry"):
        summ[k] = {lvl: float(out[f"{k}_{lvl}"].sum()) for lvl in ("low", "central", "high")}
    (ROOT / "out").mkdir(exist_ok=True)
    (ROOT / "out" / "supply_summary.json").write_text(json.dumps(summ, indent=2))
    print(json.dumps(summ, indent=2))


if __name__ == "__main__":
    main()
