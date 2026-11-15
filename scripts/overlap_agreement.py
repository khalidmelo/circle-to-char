"""Reproducibility in the overlap zones: the same field classified by two neighbouring region boxes.

Region boxes touch or overlap, so before the national table drops duplicate copies (model/national_supply.load_fields)
a field near an edge is classified twice, each time against its own box's desert background and threshold. This
pairs the two copies through the label rasters and measures how often the boxes agree (audit nd-2).

Pairs: every two processed boxes that touch or overlap; box B's fields_labels.tif is resampled (nearest) onto box A's
grid, and a field pair is kept when the shared pixels cover at least half of the smaller field. Flags: each region's
own table under the national rules (national_supply.load_region: quality check on unless --no-qc, WorldCover filter
applied). Agreement and Cohen's kappa are weighted by the shared area, per season, over pairs where both boxes
observed the season. The Sentinel-2 flags of the same pairs are the control: same sensor, same field, so they should
agree almost always, which shows the pairing itself is sound.

The output records the quality-check setting ('quality_check') and the SHA-256 of model/national_supply.py
('national_supply_sha256'), whose loader and rules it uses; scripts/export_national.py warns and leaves the block out
when either differs from the summary's (the summary's hash must be the current file's, or the export stops). Rerun
this script after national_supply.py changes.

Output: out/overlap_agreement.json (exported by scripts/export_national.py as summary key 'reproducibility')
Usage:  .venv/bin/python scripts/overlap_agreement.py [--no-qc]
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.warp import Resampling, reproject

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "model"))
import national_supply as NS  # noqa: E402

MIN_SHARE = 0.5  # shared pixels / smaller field
REF = {"winter": "s2_winter_check", "summer": "s2_summer_active"}  # Sentinel-2 over the radar's own winter dates; Jun-Oct


def agree(a, b, w):
    """Area-weighted agreement, Cohen's kappa and disagreement of two boolean flag arrays."""
    a, b, w = np.asarray(a, dtype=bool), np.asarray(b, dtype=bool), np.asarray(w, dtype=float)
    tot = w.sum()
    if tot <= 0:
        return None
    po = w[a == b].sum() / tot
    pa, pb = w[a].sum() / tot, w[b].sum() / tot
    pe = pa * pb + (1 - pa) * (1 - pb)
    dis = w[a != b].sum()
    mean_act = (w[a].sum() + w[b].sum()) / 2
    return {"pairs": int(len(w)), "ha": round(float(tot)), "agreement": round(float(po), 3),
            "kappa": round(float((po - pe) / (1 - pe)), 3) if pe < 1 else None,
            "disagreement_ha": round(float(dis)), "disagreement_share": round(float(dis / tot), 3),
            "disagreement_over_mean_active": round(float(dis / mean_act), 3) if mean_act else None,
            "active_ha_box_a": round(float(w[a].sum())), "active_ha_box_b": round(float(w[b].sum()))}


def main():
    qc = "--no-qc" not in sys.argv[1:]
    code_hash = NS.file_sha256(NS.SELF)  # hashed before the run: the code these numbers come from
    bbox = {r["id"]: r["bbox"] for r in json.loads((ROOT / "data" / "national" / "regions.json").read_text())}
    T, dates = {}, {}
    for f in sorted((ROOT / "data" / "regions").glob("R*/fields_radar.csv")):
        d, meta = NS.load_region(f, qc)
        if d is None:
            continue
        d = d[~d.wc_major.isin(list(NS.WC_DROP))]
        T[f.parent.name] = d.set_index("id")
        dates[f.parent.name] = meta.get("dates")
    ids = sorted(T, key=lambda r: int(r[1:]))
    boxes = [(a, b) for i, a in enumerate(ids) for b in ids[i + 1:]
             if max(bbox[a][0], bbox[b][0]) <= min(bbox[a][2], bbox[b][2]) + 1e-6
             and max(bbox[a][1], bbox[b][1]) <= min(bbox[a][3], bbox[b][3]) + 1e-6]
    recs = []
    for a, b in boxes:
        with rasterio.open(ROOT / "data" / "regions" / a / "fields_labels.tif") as sa, \
                rasterio.open(ROOT / "data" / "regions" / b / "fields_labels.tif") as sb:
            la = sa.read(1)
            lb = np.zeros_like(la)
            reproject(sb.read(1), lb, src_transform=sb.transform, src_crs=sb.crs, dst_transform=sa.transform,
                      dst_crs=sa.crs, src_nodata=0, dst_nodata=0, resampling=Resampling.nearest)
            px_ha = abs(sa.transform.a * sa.transform.e) / 1e4
        m = (la > 0) & (lb > 0)
        if not m.any():
            continue
        vc = pd.DataFrame({"la": la[m], "lb": lb[m]}).value_counts().rename("n").reset_index()
        for ia, ib, n in vc.itertuples(index=False):
            if ia not in T[a].index or ib not in T[b].index:
                continue
            fa, fb = T[a].loc[ia], T[b].loc[ib]
            ov = n * px_ha
            if ov < MIN_SHARE * min(fa.area_ha, fb.area_ha):
                continue
            r = {"a": a, "b": b, "ov_ha": ov, "same_dates": dates[a] == dates[b]}
            for se in NS.SEASONS:
                r[f"{se}_a"], r[f"{se}_b"] = fa[f"{se}_active"], fb[f"{se}_active"]
                r[f"s2_{se}_a"], r[f"s2_{se}_b"] = fa[REF[se]], fb[REF[se]]
            recs.append(r)
    X = pd.DataFrame(recs)
    out = {"rule": "Fields mapped by two neighbouring region boxes (shared pixels at least half of the smaller field), "
                   "each copy classified against its own box's desert background and threshold under the national "
                   "rules (quality check, WorldCover filter); agreement and Cohen's kappa between the two boxes' "
                   "radar flags, weighted by the shared area, over pairs where both boxes observed the season. "
                   "Sentinel-2 flags of the same pairs are the control (winter: over the radar's own dates; summer: "
                   "Jun-Oct).",
           "quality_check": qc,
           "national_supply_sha256": code_hash,
           "box_pairs_touching": len(boxes), "box_pairs_with_shared_fields": int(X[["a", "b"]].drop_duplicates().shape[0]),
           "field_pairs": int(len(X)), "field_pairs_ha": round(float(X.ov_ha.sum()))}
    for se in NS.SEASONS:
        ca, cb = f"{se}_a", f"{se}_b"
        y = X[X[ca].notna() & X[cb].notna()]
        res = agree(y[ca], y[cb], y.ov_ha) or {}
        for tag, z in (("same_radar_dates", y[y.same_dates]), ("different_radar_dates", y[~y.same_dates])):
            res[tag] = agree(z[ca], z[cb], z.ov_ha) if len(z) else None
        s = y[y[f"s2_{se}_a"].notna() & y[f"s2_{se}_b"].notna()]
        ctl = agree(s[f"s2_{se}_a"], s[f"s2_{se}_b"], s.ov_ha) if len(s) else None
        res["s2_control"] = {"agreement": ctl["agreement"], "kappa": ctl["kappa"], "ha": ctl["ha"]} if ctl else None
        worst = []
        for (a, b), z in y.groupby(["a", "b"]):
            g = agree(z[ca], z[cb], z.ov_ha)
            worst.append({"box_a": a, "box_b": b, "same_radar_dates": bool(z.same_dates.iloc[0]), **{k: g[k] for k in (
                "pairs", "ha", "agreement", "disagreement_ha", "active_ha_box_a", "active_ha_box_b")}})
        res["largest_disagreements"] = sorted(worst, key=lambda r: -r["disagreement_ha"])[:5]
        out[se] = res
    path = ROOT / "out" / "overlap_agreement.json"
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(out, indent=1))
    tmp.replace(path)
    print(json.dumps({k: v for k, v in out.items() if k not in NS.SEASONS}, indent=1))
    for se in NS.SEASONS:
        r = out[se]
        print(f"{se}: {r['pairs']} pairs, {r['ha']:,} ha; agreement {r['agreement']}, kappa {r['kappa']}; same dates "
              f"{(r['same_radar_dates'] or {}).get('agreement')}; Sentinel-2 control {(r['s2_control'] or {}).get('agreement')}")


if __name__ == "__main__":
    main()
