"""Export national results for the web app (docs/national.html).

  docs/data/national/summary.json      national totals, siting, comparison with official statistics, regions
  docs/data/national/fields/<R>.json   compact field list per region: [lon, lat, area_ha, class_code, s2_class_code]
                                       (s2_class_code: the class in the radar + Sentinel-2 tier, same codes)
  docs/data/national/plants_<tag>.json plants per scenario
  docs/data/national/manure.json       manure + litter cells [lon, lat, litter_t, manure_t] (central)

Added to the exported summary (next to out/national_summary.json's own keys):
  coverage         WorldCover cropland + tree cover share of the boxes processed, with radar results, both seasons,
                   rejected by the quality check, and the field-level share the radar classifies
  reproducibility  out/overlap_agreement.json (scripts/overlap_agreement.py): the same fields classified by two boxes
Per-region validation (regions[].validation) is computed from the national field table with the pooled rule.
Top-level keys besides the summary include lift (the lift table) and lift_notes (its text notes, '_age' and
'_shield'), mwan (with streams_source; also in official_sources as mwan_streams) and siting_check.

Checks before publishing. First, out/national_summary.json must carry the SHA-256 of the current
model/national_supply.py (national_supply_sha256): otherwise the export stops with a non-zero exit before it writes
anything, so a stale summary cannot be published unnoticed (rerun model/national_supply.py). Each further check prints
a WARNING and leaves its block out:
  siting           every entry of out/national_siting.json (central_*, low_*, high_*) must carry 'level' and 'basis'
                   (entries without them come from older siting code); its straw and fronds supply must equal the
                   summary's total at the entry's own level for its residue tier (radar-only totals, or s2_filled.
                   combined for residue_tier 'radar_s2'; within max(1 t, 0.001%): both sum the same per-field
                   columns of fields_national.csv); and its persistence must be what params.json gives now (H/C_org
                   gate, soil temperature). Any failure: no siting and no plants are exported, and siting_check.stale
                   gives the reason per run
  reproducibility  out/overlap_agreement.json must carry the summary's quality-check setting and the summary's
                   national_supply_sha256 (which is the current model/national_supply.py's, checked first)

Run after: region_pipeline.py (regions), model/manure.py, model/national_supply.py, scripts/overlap_agreement.py,
model/national_siting.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "model"))
from national_supply import LV, SELF, file_sha256, season_ok, tri  # noqa: E402  (same season rule as the national totals)

OUT = ROOT / "docs" / "data" / "national"
(OUT / "fields").mkdir(parents=True, exist_ok=True)
CODES = {"winter_only": 1, "summer_only": 2, "year_round": 3, "palm_grove": 4, "idle": 5, "unseen": 0, "wheat_rotation": 6,
         "partly_seen_active": 7, "partly_seen_inactive": 8, "radar_unusable": 9}
SUPPLY_TOL_T, SUPPLY_TOL_REL = 1.0, 1e-5  # siting straw/fronds supply against the summary total at the same level
PERSISTENCE_TOL = 2e-4                    # entries store persistence rounded to 4 decimals
# the summary totals a siting run's straw and fronds must match, by its residue_tier (national_siting.TIERS):
# 'radar' reads straw_t_dry_<level>, 'radar_s2' straw_t_dry_s2_<level> = the combined radar + Sentinel-2 tier (capped)
RESIDUE_TOTALS = {"radar": lambda s: s, "radar_s2": lambda s: s["s2_filled"]["combined"]}


def pooled(cells):
    """Pool per-region confusion areas (ha): agreement, chance agreement, kappa, precision, recall, F1."""
    tp, fp, fn, tn = (sum(c[k] for c in cells) for k in ("tp", "fp", "fn", "tn"))
    tot = tp + fp + fn + tn
    po = (tp + tn) / tot
    pe = ((tp + fp) * (tp + fn) + (fn + tn) * (fp + tn)) / tot ** 2
    prec = tp / (tp + fp) if tp + fp else None  # a true 0 stays 0; None only when undefined
    rec = tp / (tp + fn) if tp + fn else None
    # 4 decimals: pages print percentages, and 3 decimals let 0.6848 round twice to 69%
    return {"validated_ha": round(tot), "agreement": round(po, 4), "chance_agreement": round(pe, 4),
            "kappa": round((po - pe) / (1 - pe), 4) if pe < 1 else None,
            "precision": None if prec is None else round(prec, 4), "recall": None if rec is None else round(rec, 4),
            "f1": round(2 * tp / (2 * tp + fp + fn), 4) if 2 * tp + fp + fn else None,
            "radar_ha": round(tp + fp), "s2_ha": round(tp + fn)}


def cell(x):
    """Confusion areas (ha) of radar flag r against Sentinel-2 flag s, weighted by field area w."""
    return {"tp": x.w[x.r & x.s].sum(), "fp": x.w[x.r & ~x.s].sum(), "fn": x.w[~x.r & x.s].sum(), "tn": x.w[~x.r & ~x.s].sum()}


def validation(f):
    """Radar vs Sentinel-2 over the national field table (each field once, Saudi only): fields whose season the totals
    classify (radar flag not NaN) and that Sentinel-2 saw clearly; winter reference = Sentinel-2 over the radar dates.
    Returns (pooled, per region): the same rule for both, so a region's popup describes the fields it contributes."""
    v, per = {}, {}
    for se, ref in (("winter", "s2_winter_check"), ("summer", "s2_summer_active")):
        if ref not in f:
            continue
        a, s = tri(f[f"{se}_active"]), tri(f[ref])
        ok = a.notna() & s.notna()
        if not ok.any():
            continue
        d = pd.DataFrame({"region": f.region[ok], "r": a[ok].astype(bool), "s": s[ok].astype(bool), "w": f.area_ha[ok]})
        found = d.groupby("region").r.any()
        v[se] = pooled([cell(d)]) | {"regions": int(d.region.nunique()),
                                     "regions_radar_found_nothing": sorted(found[~found].index, key=lambda x: int(x[1:]))}
        for rid, x in d.groupby("region"):
            c = cell(x)
            r = pooled([c])
            per.setdefault(rid, {})[se] = r | {"area_agreement": r["agreement"],
                                               "confusion_ha": {k: round(float(val)) for k, val in c.items()}}
    return v, per


def coverage(regions, f):
    """Audits nd-6 / tx-1: how much of the WorldCover farmland in the 114 boxes the radar actually classifies."""
    tot = sum(r["worldcover_crop_ha"] + r["worldcover_tree_ha"] for r in regions)

    def grp(rs):
        ha = sum(r["worldcover_crop_ha"] + r["worldcover_tree_ha"] for r in rs)
        return {"boxes": len(rs), "ha": round(ha), "share": round(ha / tot, 3)}

    proc = [r for r in regions if r["status"] != "not run"]
    sc = lambda r: r.get("seasons_classified") or []  # noqa: E731
    rejected = [r for r in proc if not sc(r)]
    wa, sa = tri(f.winter_active), tri(f.summer_active)
    one, both = wa.notna() | sa.notna(), wa.notna() & sa.notna()
    fha = float(f.area_ha.sum())
    rej_ids = {r["id"] for r in rejected}
    return {"rule": "share of ESA WorldCover 2021 cropland plus tree cover in all region boxes (clusters of at least "
                    "1,500 ha cut into boxes of at most 0.6 degrees); radar results = at least one season passes the "
                    "quality check; rejected = processed but no season passes. fields: share of the mapped field area "
                    "on which the radar classifies at least one season, and both seasons",
            "worldcover_crop_tree_ha": round(tot), "boxes": len(regions),
            "processed": grp(proc), "radar_results": grp([r for r in proc if sc(r)]),
            "both_seasons": grp([r for r in proc if len(sc(r)) == 2]),
            "winter_classified": grp([r for r in proc if "winter" in sc(r)]),
            "summer_classified": grp([r for r in proc if "summer" in sc(r)]),
            "rejected": grp(rejected) | {"ids": [r["id"] for r in rejected]},
            "not_processed": grp([r for r in regions if r["status"] == "not run"]),
            "fields": {"field_ha": round(fha),
                       "one_season_or_more_ha": round(float(f[one].area_ha.sum())), "one_season_or_more_share": round(float(f[one].area_ha.sum()) / fha, 3),
                       "both_seasons_ha": round(float(f[both].area_ha.sum())), "both_seasons_share": round(float(f[both].area_ha.sum()) / fha, 3),
                       "in_rejected_boxes_ha": round(float(f[f.region.isin(rej_ids)].area_ha.sum())),
                       "in_rejected_boxes_share": round(float(f[f.region.isin(rej_ids)].area_ha.sum()) / fha, 3),
                       "radar_unusable_ha": round(float(f[f["class"] == "radar_unusable"].area_ha.sum()))}}


def siting_problems(siting, summ):
    """Why each out/national_siting.json entry cannot be published with this summary: {tag: reason}, empty when every
    entry can. Checked for every tag (central_*, low_*, high_*): 'level' and 'basis' present (older siting code wrote
    neither); straw and fronds supply equal to the summary's total at the entry's own level for its residue tier
    (RESIDUE_TOTALS: radar-only, or the combined radar + Sentinel-2 tier for 'radar_s2'); persistence
    equal to what params.json gives now through model/national_siting.py (catches H/C_org, gate and soil-temperature
    changes, which leave the supply unchanged)."""
    try:
        import national_siting as NSIT  # read only: the persistence the siting itself computes
    except Exception as e:  # noqa: BLE001
        NSIT = None
        print(f"WARNING: model/national_siting.py could not be imported ({e}); siting persistence not checked")
    bad = {}
    for tag, x in siting.items():
        miss = [k for k in ("level", "basis") if not x.get(k)]
        if miss:
            bad[tag] = f"no {' or '.join(miss)} (written by older siting code)"
            continue
        lvl, tier = x["level"], x.get("residue_tier") or "radar"
        if lvl not in LV:
            bad[tag] = f"unknown level {lvl!r}"
            continue
        if tier not in RESIDUE_TOTALS:
            bad[tag] = f"unknown residue tier {tier!r}"
            continue
        totals = RESIDUE_TOTALS[tier](summ)
        sup, per, feeds = x.get("supply_by_feed_t") or {}, x.get("persistence") or {}, x.get("feeds")
        for f_, k in (("straw", "straw_t_dry"), ("fronds", "fronds_t_dry")):
            if isinstance(feeds, list) and f_ not in feeds:
                continue  # not a feed of this run
            if f_ not in sup and per.get(f_) == 0:
                continue  # fails the H/C_org gate, so the siting leaves it out of the supply
            got, ref = float(sup.get(f_, 0.0)), float(totals[k][lvl])
            if abs(got - ref) > max(SUPPLY_TOL_T, SUPPLY_TOL_REL * ref):
                bad[tag] = f"{f_} supply {got:,.0f} t, summary {ref:,.0f} t ({tier} tier) at the {lvl} level"
                break
        if tag in bad or NSIT is None:
            continue
        try:
            p = NSIT.params(lvl) | (x.get("overrides") or {})
            now = {f_: round(NSIT.persistence(p, f_), 4) for f_ in per}
        except Exception as e:  # noqa: BLE001  (the siting code changed shape: never block on the check itself)
            print(f"WARNING: siting persistence not checked for {tag} ({e})")
            continue
        diff = [f"{f_} {per[f_]} -> {v}" for f_, v in now.items() if abs(v - float(per[f_])) > PERSISTENCE_TOL]
        if diff:
            bad[tag] = "persistence differs from what params.json gives now (" + ", ".join(diff) + ")"
    return bad


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
    summ = json.loads((ROOT / "out" / "national_summary.json").read_text())
    code, have = file_sha256(SELF), summ.get("national_supply_sha256")
    if have != code:  # before anything is written: a stale summary must not go out unnoticed
        sys.exit("ERROR: out/national_summary.json was computed by a different model/national_supply.py ("
                 + (f"summary {str(have)[:12]}, current file {code[:12]}" if have else "no national_supply_sha256 recorded")
                 + "): rerun model/national_supply.py; nothing exported")
    f = pd.read_csv(ROOT / "data" / "national" / "fields_national.csv", low_memory=False)
    for p in (OUT / "fields").glob("R*.json"):  # drop regions that no longer have fields
        p.unlink()
    s2c = f["class_s2"] if "class_s2" in f else f["class"]
    for rid, d in f.groupby("region"):
        rows = [[round(a, 4), round(b, 4), round(c, 1), CODES.get(k, 0), CODES.get(k2, 0)]
                for a, b, c, k, k2 in zip(d.lon, d.lat, d.area_ha, d["class"], s2c[d.index])]
        (OUT / "fields" / f"{rid}.json").write_text(json.dumps(rows, separators=(",", ":")))

    qc = bool(summ.get("quality_check"))
    regs = json.loads((ROOT / "data" / "national" / "regions.json").read_text())
    by = pd.read_csv(ROOT / "out" / "national_by_region.csv").set_index("region")
    v, per = validation(f)
    regions, masks = [], []
    for r in regs:
        mp = ROOT / "data" / "regions" / r["id"] / "meta.json"
        meta = json.loads(mp.read_text()) if mp.exists() else {}
        if meta.get("field_mask"):
            masks.append(json.dumps(meta["field_mask"], sort_keys=True))
        status = meta.get("status", "not run")
        val = {"thresholds_db": meta.get("validation", {}).get("thresholds_db", {}),
               "basis": "this region's fields in the national table (each field once, Saudi only, seasons the "
                        "quality check accepts), same rule as the pooled validation"} | per.get(r["id"], {}) if meta else {}
        row = {"id": r["id"], "bbox": r["bbox"], "worldcover_crop_ha": r["cropland_ha"], "worldcover_tree_ha": r["tree_ha"],
               "status": "error" if status.startswith("error") else status, "dates": meta.get("dates"),
               "validation": val, "s2_empty_frac": meta.get("s2_empty_frac"),
               "seasons_classified": [se for se in ("winter", "summer") if status == "ok" and season_ok(meta, se, qc)]}
        if r["id"] in by.index:
            row |= {k: clean(x) for k, x in by.loc[r["id"]].items()}
        regions.append(row)
    summ["coverage"] = coverage(regions, f)
    # the overlap check must come from the summary's quality-check setting and the summary's national_supply.py
    # (loader and rules); the summary's hash is the current file's (checked first)
    ov = ROOT / "out" / "overlap_agreement.json"
    if ov.exists():
        rep = json.loads(ov.read_text())
        why = []
        if rep.get("quality_check") != summ.get("quality_check"):
            why.append(f"quality_check {rep.get('quality_check')}, summary {summ.get('quality_check')}")
        rh = rep.get("national_supply_sha256")
        if not rh:
            why.append("no national_supply_sha256 recorded")
        elif rh != summ.get("national_supply_sha256"):
            why.append(f"national_supply_sha256 {str(rh)[:12]}, summary {str(summ.get('national_supply_sha256'))[:12]}: "
                       "computed by a different model/national_supply.py")
        if why:
            print(f"WARNING: out/overlap_agreement.json does not match this run ({'; '.join(why)}): rerun "
                  "scripts/overlap_agreement.py; reproducibility not exported")
        else:
            summ["reproducibility"] = rep
    else:
        print("WARNING: out/overlap_agreement.json missing: run scripts/overlap_agreement.py; reproducibility not exported")

    sp = ROOT / "out" / "national_siting.json"
    siting = json.loads(sp.read_text()) if sp.exists() else {}
    # siting must come from the current field table, params and siting code (siting_problems)
    stale, n_runs = siting_problems(siting, summ), len(siting)
    if stale:
        print(f"WARNING: siting is stale for {len(stale)} of {len(siting)} runs: rerun model/national_siting.py; siting "
              f"not exported")
        for tag, why in stale.items():
            print(f"  {tag}: {why}")
        siting = {}
    cmp_ = pd.read_csv(ROOT / "out" / "national_vs_official.csv")
    lift = OFF["lift_m"]
    mwan = dict(OFF.get("mwan") or {})
    if not mwan.get("streams_source"):
        print("WARNING: official_2024.json has no mwan.streams_source: the stream tonnages go out without their source")
    out = {"summary": summ, "siting": siting, "official": json.loads(cmp_.to_json(orient="records")),
           "regions": regions, "validation": v,
           "siting_check": {"rule": "each siting run must carry level and basis; its straw and fronds supply must equal "
                                    "the summary's total at its level for its residue tier (radar-only totals, or "
                                    "s2_filled.combined for residue_tier radar_s2), within "
                                    f"max({SUPPLY_TOL_T:g} t, {SUPPLY_TOL_REL * 100:g}%); and its persistence must "
                                    "match params.json; otherwise no siting is exported",
                            "runs": n_runs, "stale": stale},
           # field-mask settings of the run (the most common across regions; mixed settings are flagged)
           "field_mask": json.loads(max(set(masks), key=masks.count)) | ({"mixed": True} if len(set(masks)) > 1 else {}) if masks else None,
           "params": json.loads((ROOT / "model" / "params.json").read_text()),
           "official_sources": OFF["_sources"] | ({"mwan_streams": mwan["streams_source"]} if mwan.get("streams_source") else {}),
           "lift": lift,
           # the lift table's text notes ('_age': depths measured 1979-2009; '_shield': no pumping energy there)
           "lift_notes": {k: x for k, x in lift.items() if isinstance(x, str)},
           "mwan": mwan, "fodder_halt": OFF.get("mewa_fodder_halt"), "residue_audit": residue_audit(summ)}
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
