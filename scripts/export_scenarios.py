"""Export scenario results for the web page (docs/scenarios.html).

  docs/data/scenarios/scenarios.json      every scenario's results, the scenario inputs with sources, cement outlets, run id
  docs/data/scenarios/plants_<id>.json    plants of each biochar scenario: [lon, lat, char_t, to_cement_t, to_soil_t, credited_t, cement_parts]
  docs/data/scenarios/watchlist.json      MEWA fodder-halt watch-list: [lon, lat, ha, admin, winter_margin_db, summer_margin_db]

Run after: model/national_scenarios.py. Writes only under docs/data/scenarios/.
"""
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "model"))
OUT = ROOT / "docs" / "data" / "scenarios"
OUT.mkdir(parents=True, exist_ok=True)


def num(v, d=0):
    return None if pd.isna(v) else round(float(v), d)


def main():
    import national_scenarios as NSC  # cement table with filled coordinates
    res = json.loads((ROOT / "out" / "national_scenarios.json").read_text())
    for p in OUT.glob("plants_*.json"):  # only scenarios present in this run are published
        p.unlink()
    for sid, s in res["scenarios"].items():
        if s["family"] != "C":
            continue
        csv = ROOT / "out" / f"scenario_{sid}.csv"
        if not csv.exists():
            continue
        try:
            d = pd.read_csv(csv)
        except pd.errors.EmptyDataError:  # a scenario that placed no plant
            d = pd.DataFrame()
        rows = [[num(r.lon, 3), num(r.lat, 3), int(r.char_t), int(r.char_to_cement_t), int(r.char_to_soil_t),
                 int(r.credited_tco2), r.cement_parts if isinstance(r.cement_parts, str) else ""] for r in d.itertuples()]
        (OUT / f"plants_{sid}.json").write_text(json.dumps(rows, separators=(",", ":")))
    wl = ROOT / "out" / "scenario_B1_watchlist.csv"
    if wl.exists():
        w = pd.read_csv(wl)
        rows = [[num(r.lon, 4), num(r.lat, 4), num(r.area_ha, 1), r.admin.replace(" Region", ""), num(r.winter_margin_db, 1),
                 num(r.summer_margin_db, 1)] for r in w.itertuples()]
        (OUT / "watchlist.json").write_text(json.dumps(rows, separators=(",", ":")))
    cem = NSC.cement_table()
    params = json.loads((ROOT / "model" / "params.json").read_text())
    out = {"run_id": res.get("run_id"), "scenarios": res["scenarios"], "params": res.get("scenario_params", {}),
           "cement_retention": params["cement_retention"]["central"],
           "cement": [{"city": c.city, "company": c.company, "lon": round(float(c.lon), 4), "lat": round(float(c.lat), 4),
                       "output_mt": c.cement_sales_2024_mt} for c in cem.itertuples()],
           "baseline_check": res.get("baseline_check")}
    (OUT / "scenarios.json").write_text(json.dumps(out, separators=(",", ":"), default=str))
    print("exported", len(out["scenarios"]), "scenarios")


if __name__ == "__main__":
    main()
