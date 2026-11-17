"""Residue inventory and biochar scenarios (SkyMeter v2). No plant siting.

Straw  = winter-cereal cycle area x straw yield (params straw_t_dry_per_ha). A field counts if its crop cycles
         (crop_types.cycle_seq) include a winter_cereal cycle, so wheat grown before a summer crop (double_crop)
         or inside a multi-cycle field is counted; split pivots count only their non-perennial share.
Fronds = GASTAT 2024 date-palm count x dry fronds per palm (params palm_residue_kg_dry_per_palm). The mapped
         tree-crop area x palms per ha x kg per palm is reported beside it as the share the map sees (palms
         outside the mapped farm boxes, in oases and gardens, are many).
Biochar scenarios: carbon removal per dry tonne = char yield x char organic carbon x 44/12 x persistence
         (Puro.earth 2025 v2, model/national_siting.persistence; soil and cement outlets are credited alike,
         rule 6.2.4). Scenarios vary the share of residue collected (25 / 50 / 75%); low and high use the
         params low/high factors. Truck haulage, plant energy and the economics are not netted out: these are
         technical potentials, not projects. Poultry litter and manure stay as v1 modelled context (litter fails
         the H/C_org < 0.70 gate and is not credited).
Output: out/v2/residues.json
Usage:  .venv/bin/python model/residues_v2.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "model"))
import national_siting as NSIT  # noqa: E402  (imported for params() and persistence(); not run)

LV = ("low", "central", "high")
SHARES = (0.25, 0.5, 0.75)
CO2_PER_C = 44.0 / 12.0


def main():
    raw = json.loads((ROOT / "model" / "params.json").read_text())
    off = json.loads((ROOT / "data" / "national" / "official_2024.json").read_text())
    ct = pd.read_csv(ROOT / "data" / "national" / "v2" / "crop_types.csv", low_memory=False)
    fn = pd.read_csv(ROOT / "data" / "national" / "fields_national.csv", low_memory=False)[["region", "id", "area_ha", "admin"]]
    t = fn.merge(ct[["region", "id", "crop_type", "cycle_seq", "split_flag", "perennial_share"]], on=["region", "id"], how="left")
    has_wc = t.cycle_seq.fillna("").str.contains("winter_cereal")
    share = np.where(t.split_flag.fillna(0).astype(int) == 1, 1 - t.perennial_share.fillna(0), 1.0)
    wc_ha = float((t.area_ha * share)[has_wc].sum())
    tree_ha = float(t.area_ha[t.crop_type == "tree_crop"].sum())
    palms = off["national"]["date_palms"]
    out = {"method": __doc__.split("Output:")[0].strip(), "fields_classified": int(t.crop_type.notna().sum()),
           "fields_total": int(len(t)), "winter_cereal_cycle_ha": round(wc_ha), "tree_crop_ha_mapped": round(tree_ha),
           "gastat_date_palms": palms, "straw_t_dry": {}, "fronds_t_dry_national": {}, "fronds_t_dry_mapped": {},
           "removal_t_co2_per_t_dry": {}, "scenarios": []}
    by_admin = t[has_wc].assign(ha=(t.area_ha * share)[has_wc]).groupby("admin").ha.sum()
    for lv in LV:
        p = NSIT.params(lv)
        straw = wc_ha * raw["straw_t_dry_per_ha"][lv]
        fr_nat = palms * raw["palm_residue_kg_dry_per_palm"][lv] / 1000
        fr_map = tree_ha * raw["palms_per_ha"][lv] * raw["palm_residue_kg_dry_per_palm"][lv] / 1000
        out["straw_t_dry"][lv] = round(straw)
        out["fronds_t_dry_national"][lv] = round(fr_nat)
        out["fronds_t_dry_mapped"][lv] = round(fr_map)
        rf = {"straw": raw["char_yield_dry"][lv] * raw["char_c_org"][lv] * CO2_PER_C * NSIT.persistence(p, "straw"),
              "fronds": raw["palm_char_yield_dry"][lv] * raw["palm_char_c_org"][lv] * CO2_PER_C * NSIT.persistence(p, "fronds")}
        out["removal_t_co2_per_t_dry"][lv] = {k: round(v, 4) for k, v in rf.items()}
        for s in SHARES:
            out["scenarios"].append({"level": lv, "collected_share": s,
                                     "straw_t_co2": round(straw * s * rf["straw"]), "fronds_t_co2": round(fr_nat * s * rf["fronds"]),
                                     "total_t_co2": round(straw * s * rf["straw"] + fr_nat * s * rf["fronds"])})
    out["straw_ha_by_admin"] = {k: round(float(v)) for k, v in by_admin.sort_values(ascending=False).items()}
    v1 = json.loads((ROOT / "out" / "national_summary.json").read_text())
    out["v1_modelled_context"] = {k: v1.get(k) for k in ("litter_t_dry", "manure_t_dry") if k in v1}
    out["published_range_t"] = {"note": "published national agricultural-residue estimates span ~0.46 Mt to ~47 Mt (method-dependent)"}
    (ROOT / "out" / "v2").mkdir(parents=True, exist_ok=True)
    (ROOT / "out" / "v2" / "residues.json").write_text(json.dumps(out, indent=1))
    c = [s for s in out["scenarios"] if s["level"] == "central" and s["collected_share"] == 0.5][0]
    print(f"winter-cereal cycles {wc_ha:,.0f} ha; straw {out['straw_t_dry']['central']/1e3:,.0f} kt dry; fronds (GASTAT palms) "
          f"{out['fronds_t_dry_national']['central']/1e3:,.0f} kt dry (mapped {out['fronds_t_dry_mapped']['central']/1e3:,.0f} kt); "
          f"50% collected: {c['total_t_co2']/1e6:.2f} Mt CO2/yr technical potential")


if __name__ == "__main__":
    main()
