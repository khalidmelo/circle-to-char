"""Export scenario results for the web page (docs/scenarios.html).

  docs/data/scenarios/scenarios.json      every scenario's results, the scenario inputs with sources, cement outlets, run id
                                          (run_id string and its parts in run_inputs) and whether litter is credited
  docs/data/scenarios/plants_<id>.json    plants of each biochar scenario, credited (family C) or upside (family C_upside,
                                          not credited): [lon, lat, char_t, to_cement_t, to_soil_t, credited_t, cement_parts]
  docs/data/scenarios/watchlist.json      MEWA fodder-halt watch-list (scope of B1_seasonal_100_s2fill on national_supply's
                                          radar + Sentinel-2 tier: the radar scope plus fields with a season from Sentinel-2):
                                          [lon, lat, ha, admin, winter_margin_db, summer_margin_db, s2_filled (1/0),
                                          fill_code]; a margin is null where that season came from Sentinel-2. fill_code,
                                          the 8th element (the first 7 keep their meaning for older page code), says how
                                          the field got its seasons (national_scenarios.FILL_CODES): 0 radar only;
                                          1 season_fill, a season filled from Sentinel-2 on a field the radar observed;
                                          2 s2_only, classified from Sentinel-2 alone where the radar covered the field but
                                          classified no season; 3 unseen, classified from Sentinel-2 alone outside the
                                          swath of every radar date used (the radar never observed it)

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
SITING_FAMILIES = ("C", "C_upside")  # biochar scenarios with a plant table


def num(v, d=0):
    return None if pd.isna(v) else round(float(v), d)


def flag(w, *cols):
    """First of cols present in the watch-list as 1/0 (lists from older runs carry winter_from_s2 or no flag)."""
    for c in cols:
        if c in w:
            return w[c].map({True: 1, False: 0, "True": 1, "False": 0}).fillna(0).astype(int)
    return pd.Series(0, index=w.index)


def fill_code(w):
    """The watch-list fill code (0 radar, 1 season_fill, 2 s2_only, 3 unseen). Lists from older runs carry no
    fill_code column: their s2_fill gives 0-2 (unseen fields not told apart), else the 1/0 flag."""
    if "fill_code" in w:
        return w.fill_code.fillna(0).astype(int)
    if "s2_fill" in w:
        return w.s2_fill.fillna("").astype(str).map(lambda f: 2 if f == "s2_only" else 1 if f else 0)
    return flag(w, "s2_filled", "winter_from_s2")


def main():
    import national_scenarios as NSC  # cement table with filled coordinates
    res = json.loads((ROOT / "out" / "national_scenarios.json").read_text())
    for p in OUT.glob("plants_*.json"):  # only scenarios present in this run are published
        p.unlink()
    for sid, s in res["scenarios"].items():
        if s["family"] not in SITING_FAMILIES:
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
        s2, code = flag(w, "s2_filled", "winter_from_s2"), fill_code(w)
        rows = [[num(r.lon, 4), num(r.lat, 4), num(r.area_ha, 1), r.admin.replace(" Region", ""), num(r.winter_margin_db, 1),
                 num(r.summer_margin_db, 1), int(f), int(c)] for r, f, c in zip(w.itertuples(), s2, code)]
        (OUT / "watchlist.json").write_text(json.dumps(rows, separators=(",", ":")))
    cem = NSC.cement_table()
    params = json.loads((ROOT / "model" / "params.json").read_text())
    out = {"run_id": res.get("run_id"), "run_inputs": res.get("run_inputs"), "litter_credited": res.get("litter_credited"),
           "scenarios": res["scenarios"], "params": res.get("scenario_params", {}),
           "cement_retention": params["cement_retention"]["central"],
           "cement": [{"city": c.city, "company": c.company, "lon": round(float(c.lon), 4), "lat": round(float(c.lat), 4),
                       "output_mt": c.cement_sales_2024_mt} for c in cem.itertuples()],
           "baseline_check": res.get("baseline_check")}
    (OUT / "scenarios.json").write_text(json.dumps(out, separators=(",", ":"), default=str))
    print("exported", len(out["scenarios"]), "scenarios")


if __name__ == "__main__":
    main()
