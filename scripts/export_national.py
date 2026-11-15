"""Export national results for the web app (docs/national.html).

  docs/data/national/summary.json      national totals, siting, comparison with official statistics, regions
  docs/data/national/fields/<R>.json   compact field list per region: [lon, lat, area_ha, class_code]
  docs/data/national/plants_<tag>.json plants per scenario
  docs/data/national/manure.json       manure + litter cells [lon, lat, litter_t, manure_t] (central)

Run after: region_pipeline.py (regions), model/manure.py, model/national_supply.py, model/national_siting.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "model"))
from national_supply import season_ok, tri  # noqa: E402  (same season rule as the national totals)

OUT = ROOT / "docs" / "data" / "national"
(OUT / "fields").mkdir(parents=True, exist_ok=True)
CODES = {"winter_only": 1, "summer_only": 2, "year_round": 3, "palm_grove": 4, "idle": 5, "unseen": 0, "wheat_rotation": 6,
         "partly_seen_active": 7, "partly_seen_inactive": 8, "radar_unusable": 9}


def pooled(cells):
    """Pool per-region confusion areas (ha): agreement, chance agreement, kappa, precision, recall, F1."""
    tp, fp, fn, tn = (sum(c[k] for c in cells) for k in ("tp", "fp", "fn", "tn"))
    tot = tp + fp + fn + tn
    po = (tp + tn) / tot
    pe = ((tp + fp) * (tp + fn) + (fn + tn) * (fp + tn)) / tot ** 2
    prec = tp / (tp + fp) if tp + fp else None  # a true 0 stays 0; None only when undefined
    rec = tp / (tp + fn) if tp + fn else None
    return {"validated_ha": round(tot), "agreement": round(po, 3), "chance_agreement": round(pe, 3),
            "kappa": round((po - pe) / (1 - pe), 3) if pe < 1 else None,
            "precision": None if prec is None else round(prec, 3), "recall": None if rec is None else round(rec, 3),
            "f1": round(2 * tp / (2 * tp + fp + fn), 3) if 2 * tp + fp + fn else None,
            "radar_ha": round(tp + fp), "s2_ha": round(tp + fn)}


OFF = json.loads((ROOT / "data" / "national" / "official_2024.json").read_text())


def residue_audit(summ):
    """This app's residue supply next to the same factors applied to national statistics (central, t dry/yr)."""
    P = json.loads((ROOT / "model" / "params.json").read_text())
    g = P["gastat_2024_totals"]["values"]
    m = pd.read_csv(ROOT / "data" / "national" / "manure_points.csv")
    c = lambda k: P[k]["central"]
    return {
        "straw_app_t": summ["straw_t_dry"]["central"], "radar_wheat_ha": summ["vs_official"]["radar_wheat_ha"],
        "official_wheat_ha": OFF["national"]["wheat_ha"], "straw_national_t": OFF["national"]["wheat_ha"] * c("straw_t_dry_per_ha"),
        "fronds_app_t": summ["fronds_t_dry"]["central"], "palms_official": g["date_palms"],
        "fronds_national_t": g["date_palms"] * c("palm_residue_kg_dry_per_palm") / 1000,
        "litter_app_t": float(m.litter_t_dry_central.sum()), "manure_app_t": float(m.manure_t_dry_central.sum()),
        "manure_excreted_t": (g["cattle"] * c("cattle_manure_kg_dry_per_head")
                              + (g["sheep"] + g["goats"]) * c("small_ruminant_manure_kg_dry_per_head")) / 1000,
    }


def clean(v):
    if isinstance(v, (np.floating, float)):
        return None if np.isnan(v) else round(float(v), 4)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, np.bool_):
        return bool(v)
    return v


def main():
    f = pd.read_csv(ROOT / "data" / "national" / "fields_national.csv", low_memory=False)
    for p in (OUT / "fields").glob("R*.json"):  # drop regions that no longer have fields
        p.unlink()
    for rid, d in f.groupby("region"):
        rows = [[round(a, 4), round(b, 4), round(c, 1), CODES.get(k, 0)] for a, b, c, k in zip(d.lon, d.lat, d.area_ha, d["class"])]
        (OUT / "fields" / f"{rid}.json").write_text(json.dumps(rows, separators=(",", ":")))

    summ = json.loads((ROOT / "out" / "national_summary.json").read_text())
    qc = bool(summ.get("quality_check"))
    regs = json.loads((ROOT / "data" / "national" / "regions.json").read_text())
    by = pd.read_csv(ROOT / "out" / "national_by_region.csv").set_index("region")
    regions, masks = [], []
    for r in regs:
        mp = ROOT / "data" / "regions" / r["id"] / "meta.json"
        meta = json.loads(mp.read_text()) if mp.exists() else {}
        if meta.get("field_mask"):
            masks.append(json.dumps(meta["field_mask"], sort_keys=True))
        status = meta.get("status", "not run")
        row = {"id": r["id"], "bbox": r["bbox"], "worldcover_crop_ha": r["cropland_ha"], "worldcover_tree_ha": r["tree_ha"],
               "status": "error" if status.startswith("error") else status, "dates": meta.get("dates"),
               "validation": meta.get("validation", {}), "s2_empty_frac": meta.get("s2_empty_frac"),
               "seasons_classified": [se for se in ("winter", "summer") if status == "ok" and season_ok(meta, se, qc)]}
        if r["id"] in by.index:
            row |= {k: clean(v) for k, v in by.loc[r["id"]].items()}
        regions.append(row)

    siting = json.loads((ROOT / "out" / "national_siting.json").read_text()) if (ROOT / "out" / "national_siting.json").exists() else {}
    # siting must come from the current field table: its straw and fronds supply must match the summary's
    stale = [tag for tag, x in siting.items() if tag.startswith("central")
             and any(abs(x.get("supply_by_feed_t", {}).get(f, 0) - summ[k]["central"]) > max(1.0, 1e-3 * summ[k]["central"])
                     for f, k in (("straw", "straw_t_dry"), ("fronds", "fronds_t_dry")))]
    if stale:
        print(f"WARNING: siting is stale for {stale} (straw/fronds differ from the summary): rerun model/national_siting.py; "
              f"siting not exported")
        siting = {}
    cmp_ = pd.read_csv(ROOT / "out" / "national_vs_official.csv")
    # validation over the national field table (each field once, Saudi only): fields whose season the totals
    # classify (radar flag not NaN) and that Sentinel-2 saw clearly; winter reference = Sentinel-2 over the radar dates
    v = {}
    for se, ref in (("winter", "s2_winter_check"), ("summer", "s2_summer_active")):
        if ref not in f:
            continue
        a, s = tri(f[f"{se}_active"]), tri(f[ref])
        ok = a.notna() & s.notna()
        if not ok.any():
            continue
        d = pd.DataFrame({"region": f.region[ok], "r": a[ok].astype(bool), "s": s[ok].astype(bool), "w": f.area_ha[ok]})
        cell = lambda x: {"tp": x.w[x.r & x.s].sum(), "fp": x.w[x.r & ~x.s].sum(), "fn": x.w[~x.r & x.s].sum(), "tn": x.w[~x.r & ~x.s].sum()}
        found = d.groupby("region").r.any()
        v[se] = pooled([cell(d)]) | {"regions": int(d.region.nunique()),
                                     "regions_radar_found_nothing": sorted(found[~found].index, key=lambda x: int(x[1:]))}
    out = {"summary": summ, "siting": siting, "official": json.loads(cmp_.to_json(orient="records")),
           "regions": regions, "validation": v,
           # field-mask settings of the run (the most common across regions; mixed settings are flagged)
           "field_mask": json.loads(max(set(masks), key=masks.count)) | ({"mixed": True} if len(set(masks)) > 1 else {}) if masks else None,
           "params": json.loads((ROOT / "model" / "params.json").read_text()),
           "official_sources": json.loads((ROOT / "data" / "national" / "official_2024.json").read_text())["_sources"],
           "lift": json.loads((ROOT / "data" / "national" / "official_2024.json").read_text())["lift_m"],
           "mwan": OFF.get("mwan"), "fodder_halt": OFF.get("mewa_fodder_halt"), "residue_audit": residue_audit(summ)}
    (OUT / "summary.json").write_text(json.dumps(out, default=clean))

    for p in OUT.glob("plants_*.json"):  # only the scenarios of the current siting run are published
        p.unlink()
    for p in sorted((ROOT / "out").glob("national_plants_*.csv")):
        if p.stem.replace("national_plants_", "") not in siting:
            continue
        try:
            d = pd.read_csv(p)
        except pd.errors.EmptyDataError:
            d = pd.DataFrame()
        (OUT / f"plants_{p.stem.replace('national_plants_', '')}.json").write_text(d.to_json(orient="records"))
    m = ROOT / "data" / "national" / "manure_points.csv"
    if m.exists():
        d = pd.read_csv(m)
        rows = [[round(a, 3), round(b, 3), round(c), round(e)] for a, b, c, e in zip(d.lon, d.lat, d.litter_t_dry_central, d.manure_t_dry_central)]
        (OUT / "manure.json").write_text(json.dumps(rows, separators=(",", ":")))
    print("exported", len(regions), "regions,", f.region.nunique(), "with fields")


if __name__ == "__main__":
    main()
