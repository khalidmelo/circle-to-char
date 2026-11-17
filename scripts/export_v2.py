"""Export the SkyMeter v2 record for the site: a self-contained docs/data/v2/ (the v1 docs/data/* is not touched).

Reads   data/national/fields_national.csv (the published, de-duplicated v1 field table: ids, geometry, admin),
        data/national/v2/crop_types.csv (model/crop_types.py), data/national/v2/fields_et.csv and out/v2/et_summary.json
        (model/et_fields.py), out/v2/residues.json (model/residues_v2.py), out/v2/insar/ (scripts/insar_qassim.py),
        data/national/official_2024.json, data/national/regions.json, data/regions/<R>/meta.json (radar QC).
Writes  docs/data/v2/summary.json   headline numbers, tables and method notes
        docs/data/v2/regions.json   one row per processed box
        docs/data/v2/fields/R##.json positional rows [lon, lat, area_ha, crop_code, et_mm, water_m3, conf_code, method_code]
        docs/data/v2/insar/          insar.json and the pilot's figures
Built in docs/data/v2.tmp, then swapped in, so a failed run leaves the previous export intact. Every number is
rounded and checked finite (json allow_nan=False): a NaN would blank the page.
Usage: .venv/bin/python scripts/export_v2.py
"""
import hashlib
import json
import math
import os
import shutil
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "model"))
from national_supply import season_ok  # noqa: E402  (imported, not run)

OUT = ROOT / "docs" / "data" / "v2"
TMP = ROOT / "docs" / "data" / "v2.tmp"
CROPS = [  # code, key, display name (order = legend order)
    (1, "perennial_forage", "Perennial forage (alfalfa, Rhodes grass)"),
    (2, "winter_cereal", "Winter cereal (wheat, barley)"),
    (3, "double_crop", "Winter cereal then summer crop"),
    (4, "summer_crop", "Summer crop"),
    (5, "tree_crop", "Tree crop (palms, orchards)"),
    (6, "autumn_crop", "Autumn crop"),
    (7, "spring_crop", "Spring crop"),
    (8, "winter_fodder", "Winter fodder"),
    (9, "multi_cycle", "Several crop cycles"),
    (10, "fallow", "No crop this season"),
    (0, "insufficient_data", "Too few clear looks"),
]
CODE = {k: c for c, k, _ in CROPS}
CONF = {"high": 3, "medium": 2, "low": 1}
METHOD = {"thermal": 1, "mixed": 2, "ndvi_calibrated": 3, "kc_tree": 4, "insufficient": 0}
LV = ("low", "central", "high")


def clean(o):
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if not math.isfinite(f) else f
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def dump(path, obj, compact=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(clean(obj), allow_nan=False, separators=(",", ":") if compact else None, indent=None if compact else 1)
    path.write_text(txt)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()[:16] if Path(p).exists() else None


def kappa(a, b, w):
    labs = sorted(set(a) | set(b))
    m = pd.crosstab(pd.Categorical(a, labs), pd.Categorical(b, labs), values=w, aggfunc="sum", dropna=False).fillna(0).values
    t = m.sum()
    po = np.trace(m) / t
    pe = (m.sum(0) * m.sum(1)).sum() / t ** 2
    return (po - pe) / (1 - pe) if pe < 1 else np.nan


def main():
    off = json.loads((ROOT / "data" / "national" / "official_2024.json").read_text())
    regs = {r["id"]: r for r in json.loads((ROOT / "data" / "national" / "regions.json").read_text())}
    fn = pd.read_csv(ROOT / "data" / "national" / "fields_national.csv", low_memory=False)
    ct = pd.read_csv(ROOT / "data" / "national" / "v2" / "crop_types.csv", low_memory=False)
    et = pd.read_csv(ROOT / "data" / "national" / "v2" / "fields_et.csv", low_memory=False)
    ets = json.loads((ROOT / "out" / "v2" / "et_summary.json").read_text())
    res = json.loads((ROOT / "out" / "v2" / "residues.json").read_text())
    ctcols = ["region", "id", "crop_type", "stand", "tier", "confidence", "stability", "label_l8", "label_l9",
              "radar_agree", "ndvi_spring_ls", "split_flag", "perennial_share", "cycle_seq"]
    etcols = ["region", "id", "method", "et_mm_central", "net_mm_central"] + [f"water_et_m3_{lv}" for lv in LV] + \
             [f"elec_kwh_et_{lv}" for lv in LV] + [f"elec_kwh_jjas_et_{lv}" for lv in LV]
    t = fn[["region", "id", "uid", "lon", "lat", "area_ha", "admin", "is_pivot", "spring_brown", "class_s2"] +
           [f"water_m3_{lv}" for lv in LV]].merge(ct[ctcols], on=["region", "id"], how="left") \
        .merge(et[etcols], on=["region", "id"], how="left")
    t["crop_type"] = t.crop_type.fillna("insufficient_data")
    if TMP.exists():
        shutil.rmtree(TMP)
    (TMP / "fields").mkdir(parents=True)
    # ---- radar QC per region (same rule as the v1 national totals)
    radar_ok = {}
    for rid in t.region.unique():
        mp = ROOT / "data" / "regions" / rid / "meta.json"
        meta = json.loads(mp.read_text()) if mp.exists() else {}
        try:
            radar_ok[rid] = {se: bool(season_ok(meta, se, True)) for se in ("winter", "summer")}
        except Exception:
            radar_ok[rid] = {"winter": False, "summer": False}
    t["radar_box"] = t.region.map(lambda r: radar_ok[r]["winter"] or radar_ok[r]["summer"])
    # ---- field rows
    for rid, d in t.groupby("region"):
        rows = [[round(a, 4), round(b, 4), round(c, 1), CODE.get(k, 0),
                 (round(e) if pd.notna(e) else None), (round(w) if pd.notna(w) else None), CONF.get(cf, 0), METHOD.get(m, 0)]
                for a, b, c, k, e, w, cf, m in zip(d.lon, d.lat, d.area_ha, d.crop_type, d.et_mm_central,
                                                    d.water_et_m3_central, d.confidence, d.method)]
        dump(TMP / "fields" / f"{rid}.json", rows, compact=True)
    A = float(t.area_ha.sum())
    # ---- crop table
    crop_rows = []
    for c, k, name in CROPS:
        s = t[t.crop_type == k]
        crop_rows.append({"code": c, "key": k, "name": name, "fields": int(len(s)), "area_ha": round(float(s.area_ha.sum())),
                          "share": round(float(s.area_ha.sum()) / A, 4),
                          "median_et_mm": (round(float(s.et_mm_central.median())) if s.et_mm_central.notna().any() else None),
                          "water_bn_m3": round(float(s.water_et_m3_central.sum()) / 1e9, 3)})
    wc = t.cycle_seq.fillna("").str.contains("winter_cereal")
    # ---- halt baseline (MEWA: perennial fodder halted in six sedimentary-shelf regions from 16 Nov 2026)
    key_of = {name: v["key"] for name, v in off["regions"].items()}
    t["admin_key"] = t.admin.map(key_of)
    halt_keys = off["mewa_fodder_halt"]["regions"]
    per = t[(t.crop_type == "perennial_forage")]
    per_cur = per[per.stand.isin(["established", "new"]) | per.stand.isna()]
    halt = []
    for k in halt_keys:
        s = per_cur[per_cur.admin_key == k]
        o = [v for v in off["regions"].values() if v["key"] == k][0]
        halt.append({"region": k, "perennial_ha": round(float(s.area_ha.sum())), "fields": int(len(s)),
                     "water_bn_m3_central": round(float(s.water_et_m3_central.sum()) / 1e9, 3),
                     "gastat_fodder_ha": o["fodder_ha"], "gastat_wheat_ha": o["wheat_ha"],
                     "mapped_winter_cereal_cycle_ha": round(float(t[wc & (t.admin_key == k)].area_ha.sum())),
                     "mewa_agri_groundwater_bn_m3": round(o["agri_groundwater_m3"] / 1e9, 3),
                     "mapped_water_bn_m3_central": round(float(t[t.admin_key == k].water_et_m3_central.sum()) / 1e9, 3)})
    hs = per_cur[per_cur.admin_key.isin(halt_keys)]
    # ---- validation and checks
    lab_ok = t.label_l8.notna() & t.label_l9.notna()
    v = {"split_half_kappa": round(float(kappa(t.label_l8[lab_ok], t.label_l9[lab_ok], t.area_ha[lab_ok])), 3),
         "split_half_same_area_share": round(float(t.area_ha[lab_ok & (t.label_l8 == t.label_l9)].sum() / t.area_ha[lab_ok].sum()), 3),
         "bootstrap_stability_median": round(float(t.stability.median()), 3),
         "area_share_stability_ge_0_9": round(float(t.area_ha[t.stability >= 0.9].sum() / A), 3),
         "confidence_ha": {c: round(float(t.area_ha[t.confidence == c].sum())) for c in CONF},
         "tier_ha": {k: round(float(t.area_ha[t.tier == k].sum())) for k in ("reliable", "provisional", "edge_mixed")}}
    sb = t.spring_brown.astype(str).str.lower().map({"true": True, "false": False})
    m = sb.notna() & t.ndvi_spring_ls.notna()
    v["spring_check_agreement"] = round(float(((t.ndvi_spring_ls[m] < 0.30) == sb[m]).mean()), 3)
    ra = t[t.radar_agree.notna()]
    v["radar_agreement_by_crop"] = {k: round(float(g.radar_agree.astype(float).mean()), 3) for k, g in ra.groupby("crop_type") if len(g) >= 30}
    v["radar_agreement_area_share"] = round(float((ra.radar_agree.astype(float) * ra.area_ha).sum() / ra.area_ha.sum()), 3) if len(ra) else None
    gas = []
    for name, o in off["regions"].items():
        s = t[t.admin == name]
        if not len(s):
            continue
        gas.append({"region": o["key"], "mapped_winter_cereal_cycle_ha": round(float(s[wc[s.index]].area_ha.sum())),
                    "gastat_wheat_ha": o["wheat_ha"], "mapped_perennial_forage_ha": round(float(s[s.crop_type == "perennial_forage"].area_ha.sum())),
                    "gastat_fodder_ha": o["fodder_ha"], "mapped_tree_crop_ha": round(float(s[s.crop_type == "tree_crop"].area_ha.sum())),
                    "gastat_date_palms": o["date_palms"], "water_bn_m3_central": round(float(s.water_et_m3_central.sum()) / 1e9, 3),
                    "mewa_agri_groundwater_bn_m3": round(o["agri_groundwater_m3"] / 1e9, 3), "halt_region": o["key"] in halt_keys})
    v["gastat_by_region"] = sorted(gas, key=lambda r: -r["gastat_fodder_ha"])
    cc = ROOT / "out" / "v2" / "crop_check.json"
    v["blind_check"] = json.loads(cc.read_text()) if cc.exists() else None
    # ---- regions
    rrows = []
    for rid, d in t.groupby("region"):
        r = regs[rid]
        ms = d.groupby(d.method.fillna("none")).area_ha.sum() / d.area_ha.sum()
        rrows.append({"id": rid, "bbox": r["bbox"], "center": r["center"], "admin": d.admin.mode().iat[0] if d.admin.notna().any() else None,
                      "fields": int(len(d)), "area_ha": round(float(d.area_ha.sum())),
                      "crop_ha": {str(CODE[k]): round(float(g.area_ha.sum())) for k, g in d.groupby("crop_type") if k in CODE},
                      "water_bn_m3_central": round(float(d.water_et_m3_central.sum()) / 1e9, 4),
                      "median_et_mm": round(float(d.et_mm_central.median())) if d.et_mm_central.notna().any() else None,
                      "thermal_share": round(float(ms.get("thermal", 0) + ms.get("mixed", 0)), 3),
                      "radar_qc": radar_ok[rid]})
    dump(TMP / "regions.json", rrows)
    # ---- InSAR
    ins_src = ROOT / "out" / "v2" / "insar"
    insar = None
    if (ins_src / "insar.json").exists():
        shutil.copytree(ins_src, TMP / "insar")
        insar = json.loads((ins_src / "insar.json").read_text())
    radar_boxes = [r for r, ok in radar_ok.items() if ok["winter"] or ok["summer"]]
    summ = {
        "generated": date.today().isoformat(), "season": "2025-11-01 to 2026-10-31",
        "coverage": {"boxes_processed": int(t.region.nunique()), "boxes_total": len(regs), "fields": int(len(t)), "area_ha": round(A),
                     "radar_qc_boxes": len(radar_boxes), "radar_qc_area_ha": round(float(t[t.radar_box].area_ha.sum())),
                     "crop_tree_share_of_worldcover": round(sum(r["cropland_ha"] + r["tree_ha"] for k, r in regs.items() if k in set(t.region))
                                                            / sum(r["cropland_ha"] + r["tree_ha"] for r in regs.values()), 3),
                     "crop_tree_share_rule": "ESA WorldCover 2021 cropland plus tree cover inside the processed boxes, as a share of that cover in all "
                                             "114 farming boxes (WorldCover clusters of at least 1,500 ha, cut into boxes of at most 0.6 degrees); "
                                             "scattered farmland outside the boxes is not in either figure"},
        "crops": crop_rows,
        "winter_cereal_cycle_ha": round(float(t[wc].area_ha.sum())),
        "halt": {"effective": off["mewa_fodder_halt"]["effective"], "regions": halt, "perennial_ha": round(float(hs.area_ha.sum())),
                 "fields": int(len(hs)), "water_bn_m3_central": round(float(hs.water_et_m3_central.sum()) / 1e9, 3),
                 "stand_ha": {s: round(float(per[(per.stand == s) & per.admin_key.isin(halt_keys)].area_ha.sum())) for s in ("established", "new", "ended", "within")},
                 "source": off["mewa_fodder_halt"]["source"], "url": off["mewa_fodder_halt"]["url"]},
        "water": {"gross_bn_m3": {lv: round(float(t[f"water_et_m3_{lv}"].sum()) / 1e9, 3) for lv in LV},
                  "net_bn_m3": ets.get("net_use_bn_m3"), "benchmark_bn_m3": {lv: round(float(t[f"water_m3_{lv}"].sum()) / 1e9, 3) for lv in LV},
                  "shelf_groundwater_bn_m3": ets.get("water_et_shelf_bn_m3"), "shield_undetermined_bn_m3": ets.get("water_et_shield_bn_m3"),
                  "noncrop_et_bn_m3": ets.get("noncrop_et_bn_m3"), "shield_ha": ets.get("shield_ha"),
                  "mewa_shelf_regions_bn_m3": round(sum(o["agri_groundwater_m3"] for o in off["regions"].values()
                                                        if o["key"] in ("Al-Jouf", "Riyadh", "Qassim", "Hail", "Eastern", "Tabuk", "N. Borders")) / 1e9, 2),
                  "mewa_bn_m3": round(off["national"]["agri_groundwater_m3"] / 1e9, 2),
                  "radar_qc_boxes_gross_bn_m3": round(float(t[t.radar_box].water_et_m3_central.sum()) / 1e9, 3),
                  "methods_area_share": {k: round(float(t[t.method == k].area_ha.sum()) / A, 4) for k in METHOD},
                  "qc": {r["region"]: {"accepted": r["accepted"], "overpasses": r["overpasses"], "dT_ratio": r.get("dT_obs_over_ssebop"),
                                       "dT_src": r.get("dT_ratio_source", "region"), "c_src": r.get("c_source")}
                         for r in ets.get("regions", [])},
                  "eto_adj_mm_median": round(float(np.median([r["eto_adj_mm"] for r in ets.get("regions", [])])), 0) if ets.get("regions") else None},
        "energy": {"twh": {lv: round(float(t[f"elec_kwh_et_{lv}"].sum()) / 1e9, 3) for lv in LV},
                   "jjas_mw": {lv: round(float(t[f"elec_kwh_jjas_et_{lv}"].sum()) / (122 * 24) / 1000) for lv in LV}},
        "residues": {k: res[k] for k in ("winter_cereal_cycle_ha", "tree_crop_ha_mapped", "gastat_date_palms", "straw_t_dry",
                                          "fronds_t_dry_national", "fronds_t_dry_mapped", "removal_t_co2_per_t_dry", "scenarios") if k in res},
        "validation": v,
        "insar": insar and {k: insar[k] for k in insar if k in ("conclusion", "track_frame", "figures", "caveats", "method_notes")}
                 | {"pairs": [{"ref": p["ref"], "sec": p["sec"], "dt_days": p["dt_days"], "segment": p.get("segment")} for p in insar.get("pairs", [])],
                    "full": "insar/insar.json"},
        "inputs": {"crop_types_sha": sha(ROOT / "model" / "crop_types.py"), "et_fields_sha": sha(ROOT / "model" / "et_fields.py"),
                   "landsat_fields_sha": sha(ROOT / "scripts" / "landsat_fields.py"), "fields_national_sha": sha(ROOT / "data" / "national" / "fields_national.csv"),
                   "eto_daily_sha": sha(ROOT / "data" / "national" / "eto_daily.csv")},
    }
    dump(TMP / "summary.json", summ)
    if OUT.exists():
        old = OUT.with_name("v2.old")
        if old.exists():
            shutil.rmtree(old)
        os.replace(OUT, old)
        os.replace(TMP, OUT)
        shutil.rmtree(old)
    else:
        os.replace(TMP, OUT)
    w = summ["water"]["gross_bn_m3"]
    print(f"exported {summ['coverage']['fields']:,} fields in {summ['coverage']['boxes_processed']} boxes; "
          f"perennial forage {crop_rows[0]['area_ha']:,} ha; halt baseline {summ['halt']['perennial_ha']:,} ha; "
          f"water {w['central']} bn m3 ({w['low']}-{w['high']}); benchmark {summ['water']['benchmark_bn_m3']['central']}")


if __name__ == "__main__":
    main()
