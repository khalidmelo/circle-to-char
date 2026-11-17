"""Score the blind check of the v2 crop-type map (stratified estimators, Olofsson et al. 2014, Remote Sens. Environ.
148:42-57).

Inputs (the folder used by scripts/v2_check_cards.py):
  key.csv      sample_id, crop_type (mapped = stratum), stratum_n, stratum_ha
  labels.csv   sample_id, label, confidence, interpreter   (first interpretation of every card)
  labels2.csv  optional: a second, independent interpretation of a subset (same columns)
Cards labelled 'unsure' are dropped from the error matrix and counted.
Output: <dir>/score.json and out/v2/crop_check.json (copied into the site export)
  overall accuracy (area-weighted), user's and producer's accuracy per class with 95% CIs, the error matrix in area
  proportions, error-adjusted class areas with 95% CIs, and between-interpreter agreement on the double-labelled cards.
Usage: .venv/bin/python scripts/v2_check_score.py <dir>
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def main(d):
    d = Path(d)
    key = pd.read_csv(d / "key.csv")
    lab = pd.read_csv(d / "labels.csv")
    t = key.merge(lab, on="sample_id", how="inner")
    unsure = int((t.label == "unsure").sum())
    t = t[t.label != "unsure"]
    strata = sorted(key.crop_type.unique())
    W = key.groupby("crop_type").stratum_ha.first()
    W = W / W.sum()                                       # area weight of each mapped class
    classes = sorted(set(strata) | set(t.label))
    n_h = t.groupby("crop_type").size()
    # area-proportion error matrix p_ij = W_i * n_ij / n_i.
    P = pd.DataFrame(0.0, index=classes, columns=classes)
    for h, g in t.groupby("crop_type"):
        for j, c in g.label.value_counts().items():
            P.loc[h, j] = W[h] * c / len(g)
    oa = float(np.trace(P.values))
    # variance of overall accuracy (Olofsson eq. 5)
    v_oa = 0.0
    for h, g in t.groupby("crop_type"):
        u = (g.label == h).mean()
        v_oa += W[h] ** 2 * u * (1 - u) / max(len(g) - 1, 1)
    users, producers, areas = {}, {}, {}
    total_ha = float(key.groupby("crop_type").stratum_ha.first().sum())
    for c in strata:
        g = t[t.crop_type == c]
        if len(g):
            u = float((g.label == c).mean())
            users[c] = {"value": round(u, 3), "ci95": round(1.96 * np.sqrt(u * (1 - u) / max(len(g) - 1, 1)), 3), "n": int(len(g))}
    for c in classes:
        col = P[c].sum()
        if col > 0 and c in P.index:
            producers[c] = round(float(P.loc[c, c] / col), 3)
        # error-adjusted area of reference class c and its SE (Olofsson eq. 10-11)
        se = 0.0
        for h, g in t.groupby("crop_type"):
            p = (g.label == c).mean()
            se += W[h] ** 2 * p * (1 - p) / max(len(g) - 1, 1)
        areas[c] = {"ha": round(col * total_ha), "ci95_ha": round(1.96 * np.sqrt(se) * total_ha),
                    "mapped_ha": round(float(key[key.crop_type == c].stratum_ha.iloc[0])) if c in strata else 0}
    out = {"design": "test sample: stratified random by mapped class (fields >= 3 ha, 25 per class), drawn after the crop-rule changes and "
                     "excluding the 224-card calibration sample used to make them; blind visual interpretation of raw Landsat NDVI looks plus "
                     "six Sentinel-2 true-colour chips per field by independent interpreters who never saw the mapped label; a random 20% "
                     "was labelled again by a second interpreter. Visual interpretation, not field visits.",
           "cards": int(len(key)), "labelled": int(len(t)), "unsure": unsure,
           "overall_accuracy": round(oa, 3), "overall_ci95": round(1.96 * np.sqrt(v_oa), 3),
           "users_accuracy": users, "producers_accuracy": producers, "error_adjusted_area": areas,
           "error_matrix_area_share": {i: {j: round(float(P.loc[i, j]), 4) for j in classes if P.loc[i, j] > 0} for i in classes if P.loc[i].sum() > 0}}
    # coarse legend: the level the fodder-halt baseline and the water accounting depend on
    group = {"perennial_forage": "perennial", "tree_crop": "tree", "fallow": "no_crop", "not_farmland": "no_crop"}
    tg = t.assign(map_g=t.crop_type.map(lambda c: group.get(c, "seasonal")), ref_g=t.label.map(lambda c: group.get(c, "seasonal")))
    Wg = W.groupby(lambda c: group.get(c, "seasonal")).sum()
    oa_g, users_g = 0.0, {}
    for g, gg in tg.groupby("map_g"):
        # within a coarse map group, weight each stratum by its area share of the group
        acc = sum(W[h] / Wg[g] * (sub.ref_g == g).mean() for h, sub in gg.groupby("crop_type"))
        users_g[g] = round(float(acc), 3)
        oa_g += Wg[g] * acc
    out["coarse_legend"] = {"groups": {"perennial": ["perennial_forage"], "tree": ["tree_crop"], "no_crop": ["fallow", "not_farmland"],
                                       "seasonal": "every other class"},
                            "overall_accuracy": round(float(oa_g), 3), "users_accuracy": users_g}
    if (d / "labels2.csv").exists():
        l2 = pd.read_csv(d / "labels2.csv")
        m = lab.merge(l2, on="sample_id", suffixes=("_1", "_2"))
        m = m[(m.label_1 != "unsure") & (m.label_2 != "unsure")]
        po = float((m.label_1 == m.label_2).mean()) if len(m) else np.nan
        labs = sorted(set(m.label_1) | set(m.label_2))
        pe = sum((m.label_1 == c).mean() * (m.label_2 == c).mean() for c in labs) if len(m) else np.nan
        out["interpreter_agreement"] = {"n": int(len(m)), "agreement": round(po, 3),
                                        "kappa": round((po - pe) / (1 - pe), 3) if len(m) and pe < 1 else None}
    (d / "score.json").write_text(json.dumps(out, indent=1))
    (ROOT / "out" / "v2").mkdir(parents=True, exist_ok=True)
    (ROOT / "out" / "v2" / "crop_check.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: out[k] for k in ("labelled", "unsure", "overall_accuracy", "overall_ci95")}),
          "| users:", {k: v["value"] for k, v in users.items()})


if __name__ == "__main__":
    main(sys.argv[1])
