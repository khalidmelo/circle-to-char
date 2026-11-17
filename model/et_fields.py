"""Heat-based water use per field (SkyMeter v2): a two-anchor surface-temperature index on Landsat 8/9, scaled by
FAO-56 reference ET from NASA POWER.

Method (an SSEB-type two-anchor Ts index, Senay et al. 2007, with METRIC-style anchor selection and SSEBop
dT / c-factor checks; inputs from scripts/landsat_fields.py, which already applies the emissivity and elevation
corrections and splits field pixels into distance-from-edge bands):

  For each overpass and region
    T_cold = median Ts of interior (>= 200 m from the field edge) full-cover pixels (NDVI >= 0.75): ETf = 1
             fallback: c * Tmax(POWER), c = the region's seasonal median of T_cold / Tmax
    T_hot  = median Ts of fallow field pixels (NDVI < 0.15 now and at the previous clear look): ETf = 0
             fallback: desert median + the region's median (fallow - desert) offset; last resort T_cold + r * dT_SSEBop
    QC     accept only if >= 30% of the box is clear, dT = T_hot - T_cold >= 6 K, 0.6 <= dT / dT_SSEBop <= 1.5 (when
           both anchors are observed), T_cold / Tmax inside the region's 5th-95th percentile (thin cloud or haze over
           the cold fields) and <= 5 mm rain in the previous 5 days (wet bare soil is not ET = 0). The fallow-pixel
           p10-p90 spread is recorded but not used: it is 10-18 K on clear days because dry fallow and freshly
           watered bare fields sit side by side (tested on R04), so it does not indicate contamination.
  Edge mixing: Landsat's 100 m thermal footprint blends hot desert into pixels near a field edge. From large full-cover
    fields, w(band) = (Ts_band - Ts_interior) / (T_hot - Ts_interior) per region and season half (monotone, <= 0.35);
    ETf_true = ETf_obs / (1 - w) by band (linear mixing with a hot surround).
  Field ETf per overpass = pixel-weighted mean over bands, kept if 2+ clean pixels and -0.3 <= ETf <= 1.3 (no clipping
    of single pixels, so symmetric noise on idle fields averages to ~0 instead of a positive bias).
  Fields without a usable thermal sample (small or thin fields, QC-failed overpasses): ETf from the overpass's
    monotone ETf-NDVI relation fitted on thermal fields of the same region (non-tree crops; tree crops get their own
    relation when 30+ tree fields have thermal samples, otherwise ETa = Kc ETo with Kc 0.8, range 0.7-0.9).
  Time: daily ETf by linear interpolation between observations (gaps > 32 days flagged), ETa = ETf x k x ETo:
    central k = 1.2 on aridity-adjusted ETo (FAO-56 Annex 6, dew point = Tmin - 2 C), low 1.1 x adjusted ETo,
    high 1.2 x unadjusted ETo (POWER describes desert air; this is the largest single scaling uncertainty, ~+/-12%).
    Season totals are capped at 1.3 x sum(k ETo).
  Net consumptive use = max(ETa - Peff, 0), Peff from POWER monthly rain (FAO/CROPWAT: 0.8P-25 if P>75 mm, else
    max(0.6P-10, 0)). Gross abstraction = net / application efficiency: pivots 0.88 / 0.80 / 0.70 (params.json,
    inverted: the low estimate uses the high efficiency), other fields (palms, basins, drip) 0.85 / 0.70 / 0.55.
  Energy (cross-check only): water x rho g x head_m_<lvl> (fields_national.csv) / 3.6e6 / 0.66; Arabian Shield: none.

Season year 2025-11-01 .. 2026-10-31; winter = Nov-Apr, summer = May-Oct, grid peak = Jun-Sep.
Outputs: data/regions/<R>/et_fields.csv, data/regions/<R>/et_overpasses.csv;
         with 'all': data/national/v2/fields_et.csv and out/v2/et_summary.json
Usage: .venv/bin/python model/et_fields.py R04 [R05 ...] | all
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
Y0, Y1 = pd.Timestamp("2025-11-01"), pd.Timestamp("2026-10-31")
D0, D1 = pd.Timestamp("2025-09-15"), pd.Timestamp("2026-11-15")      # interpolation support either side
NB = 4
K = {"low": 1.1, "central": 1.2, "high": 1.2}
ETO_COL = {"low": "eto_adj_mm", "central": "eto_adj_mm", "high": "eto_mm"}
EA_PIVOT = {"low": 0.88, "central": 0.80, "high": 0.70}
EA_OTHER = {"low": 0.85, "central": 0.70, "high": 0.55}
KC_TREE = {"low": 0.7, "central": 0.8, "high": 0.9}
MAX_GAP = 32
RHO_G = 9810.0
PUMP_EFF = 0.66
TREE = {"tree_crop"}


def season_half(dates):
    m = pd.DatetimeIndex(pd.to_datetime(dates)).month
    return np.where((m >= 5) & (m <= 10), "summer", "winter")


_GLOBAL = None


def global_defaults():
    """Medians over every region's observed anchors, used only where a region never observes its own (small-field and
    terrace boxes with no 30 full-cover interior pixels, or no fallow fields): c = T_cold / Tmax by season half, the
    fallow - desert offset, and dT_obs / dT_SSEBop. Flagged in the outputs (tc_src / th_src = '..._national')."""
    global _GLOBAL
    if _GLOBAL is None:
        a = pd.concat([pd.read_csv(f) for f in sorted((ROOT / "data" / "regions").glob("R*/landsat_anchors.csv"))], ignore_index=True)
        a["half"] = season_half(a.date)
        c = (a.tc / a.tmax_k).groupby(a.half).median()
        obs = a.tc.notna() & a.th.notna()
        _GLOBAL = {"c": c.to_dict(), "off": float((a.th - a.desert_ts).median()),
                   "r": float(((a.th - a.tc) / a.dt_ssebop)[obs].median())}
    return _GLOBAL


def anchors(rid):
    an = pd.read_csv(ROOT / "data" / "regions" / rid / "landsat_anchors.csv")
    an["half"] = season_half(an.date)
    an["c"] = an.tc / an.tmax_k
    g = global_defaults()
    c_bar = an.groupby("half").c.median().reindex(["winter", "summer"])
    c_src = {h: ("region" if np.isfinite(c_bar.get(h, np.nan)) else "national") for h in ("winter", "summer")}
    c_bar = c_bar.fillna(pd.Series(g["c"]))
    off = (an.th - an.desert_ts).median()
    off = off if np.isfinite(off) else g["off"]
    obs = an.tc.notna() & an.th.notna()
    r_bar = ((an.th - an.tc) / an.dt_ssebop)[obs].median()
    r_src = "region" if np.isfinite(r_bar) else "national"
    r_bar = r_bar if np.isfinite(r_bar) else g["r"]
    off_src = "region" if np.isfinite((an.th - an.desert_ts).median()) else "national"
    an["tc_src"] = np.where(an.tc.notna(), "obs", np.where(an.half.map(c_src) == "national", "c_tmax_national", "c_tmax"))
    an["Tc"] = an.tc.fillna(an.half.map(c_bar) * an.tmax_k)
    an["th_src"] = np.where(an.th.notna(), "obs", np.where(an.desert_ts.notna(), "desert_offset", "ssebop"))
    an["Th"] = an.th.fillna(an.desert_ts + off).fillna(an.Tc + r_bar * an.dt_ssebop)
    an["dT"] = an.Th - an.Tc
    ratio = (an.th - an.tc) / an.dt_ssebop
    an["hot_spread"] = an.hot_p90 - an.hot_p10
    lo, hi = an.c.quantile(0.05), an.c.quantile(0.95)
    an["qc_clear"] = an.clear_frac >= 0.3
    an["qc_cold"] = an.c.isna() | an.c.between(lo, hi)
    an["qc_dt"] = an.dT >= 6.0
    an["qc_ratio"] = ~obs | ratio.between(0.6, 1.5)
    an["qc_rain"] = ~(an.rain5_mm > 5.0)
    an["qc_ok"] = an.qc_clear & an.qc_cold & an.qc_dt & an.qc_ratio & an.qc_rain & an.Tc.notna() & an.Th.notna()
    # edge-mixing weights by band, per season half, from large full-cover fields on accepted overpasses
    w = {}
    for half, g in an[an.qc_ok].groupby("half"):
        interior = g["fc_ts_b4"]
        ws = []
        for k in range(1, NB):
            wk = ((g[f"fc_ts_b{k}"] - interior) / (g.Th - interior)).median()
            ws.append(float(np.clip(wk if np.isfinite(wk) else 0.0, 0.0, 0.35)))
        for k in range(1, len(ws)):          # monotone: farther from the edge never mixes more
            ws[k] = min(ws[k], ws[k - 1])
        w[half] = ws + [0.0]
    for half in ("winter", "summer"):
        w.setdefault(half, w.get("winter" if half == "summer" else "summer", [0.0] * NB))
    meta = {"c_bar": c_bar.round(4).to_dict(), "c_source": c_src, "fallow_minus_desert_K": round(float(off), 3) if np.isfinite(off) else None,
            "dT_obs_over_ssebop": round(float(r_bar), 3) if np.isfinite(r_bar) else None, "dT_ratio_source": r_src,
            "fallow_offset_source": off_src, "edge_w": w,
            "overpasses": int(len(an)), "accepted": int(an.qc_ok.sum()),
            "rejected": {k: int((~an[k]).sum()) for k in ("qc_clear", "qc_cold", "qc_dt", "qc_ratio", "qc_rain")}}
    return an, meta


def monotone_fit(x, y, bins=np.arange(-0.1, 1.0001, 0.05), min_n=5):
    """Binned medians of y by x, made non-decreasing (pool-adjacent-violators); returns (centres, values)."""
    idx = np.digitize(x, bins)
    cx, cy, cn = [], [], []
    for i in np.unique(idx):
        s = idx == i
        if s.sum() >= min_n:
            cx.append(np.median(x[s])); cy.append(np.median(y[s])); cn.append(s.sum())
    if len(cx) < 3:
        return None
    cy, cn = list(cy), list(cn)
    i = 0
    while i < len(cy) - 1:                    # PAVA
        if cy[i] > cy[i + 1]:
            tot = cn[i] + cn[i + 1]
            v = (cy[i] * cn[i] + cy[i + 1] * cn[i + 1]) / tot
            cy[i:i + 2] = [v]; cn[i:i + 2] = [tot]; cx[i:i + 2] = [(cx[i] + cx[i + 1]) / 2]
            i = max(i - 1, 0)
        else:
            i += 1
    return np.array(cx), np.array(cy)


def region(rid, crop=None):
    R = ROOT / "data" / "regions" / rid
    if not (R / "landsat_thermal.csv.gz").exists():
        print(rid, "no Landsat samples; skipped", flush=True)
        return None
    an, meta = anchors(rid)
    th = pd.read_csv(R / "landsat_thermal.csv.gz")
    nd = pd.read_csv(R / "landsat_ndvi.csv.gz")
    key = ["date", "sensor", "path"]
    th = th.merge(an[key + ["Th", "Tc", "dT", "half", "qc_ok"]], on=key, how="inner")
    num = np.zeros(len(th)); den = np.zeros(len(th))
    for k in range(1, NB + 1):
        wk = np.where(th.half == "summer", meta["edge_w"]["summer"][k - 1], meta["edge_w"]["winter"][k - 1])
        n = th[f"n_b{k}"].fillna(0).values
        e = ((th.Th - th[f"ts_b{k}"]) / th.dT).values / (1 - wk)
        ok = (n > 0) & np.isfinite(e)
        num += np.where(ok, e * n, 0); den += np.where(ok, n, 0)
    th["etf"] = np.where(den > 0, num / np.maximum(den, 1), np.nan)
    th["npx"] = den
    th = th[th.qc_ok & (th.npx >= 2) & th.etf.between(-0.3, 1.3)]
    th = th.merge(nd[["id"] + key + ["ndvi"]], on=["id"] + key, how="left")
    is_tree = pd.Series(False, index=pd.Index(np.unique(nd.id), name="id"))
    if crop is not None:
        is_tree = crop.set_index("id").crop_type.isin(TREE).reindex(is_tree.index, fill_value=False)
    th["tree"] = th.id.map(is_tree).fillna(False).values
    # ETf-NDVI relations per accepted overpass (non-tree; tree if enough)
    rel, rel_tree = {}, {}
    acc = an[an.qc_ok]
    for _, o in acc.iterrows():
        g = th[(th.date == o.date) & (th.sensor == o.sensor) & (th.path == o.path) & th.ndvi.notna()]
        f = monotone_fit(g[~g.tree].ndvi.values, g[~g.tree].etf.values)
        if f is not None:
            rel[(o.date, o.sensor, o.path)] = f
        gt = g[g.tree]
        if gt.id.nunique() >= 30:
            ft = monotone_fit(gt.ndvi.values, gt.etf.values, min_n=3)
            if ft is not None:
                rel_tree[(o.date, o.sensor, o.path)] = ft
    rel_dates = pd.to_datetime(pd.Series([k[0] for k in rel])) if rel else pd.Series([], dtype="datetime64[ns]")
    rel_keys = list(rel)

    def nearest_rel(date, table, keys, dates):
        if not keys:
            return None
        k = (date, ) if False else None
        dd = (dates - pd.Timestamp(date)).abs()
        i = int(dd.values.argmin())
        return table[keys[i]] if dd.iloc[i] <= pd.Timedelta(days=16) else None

    # NDVI-tier observations for every clear NDVI look without an accepted thermal sample
    have = set(zip(th.id, th.date, th.sensor, th.path))
    nd2 = nd[[(i, d, s, p) not in have for i, d, s, p in zip(nd.id, nd.date, nd.sensor, nd.path)]].copy()
    nd2["tree"] = nd2.id.map(is_tree).fillna(False).values
    out_e = np.full(len(nd2), np.nan)
    rt_keys, rt_dates = list(rel_tree), (pd.to_datetime(pd.Series([k[0] for k in rel_tree])) if rel_tree else pd.Series([], dtype="datetime64[ns]"))
    for (d, s, p), g in nd2.groupby(key):
        f = rel.get((d, s, p)) or nearest_rel(d, rel, rel_keys, rel_dates)
        ft = rel_tree.get((d, s, p)) or nearest_rel(d, rel_tree, rt_keys, rt_dates)
        ii = g.index
        nt = ~g.tree.values
        if f is not None:
            out_e[nd2.index.get_indexer(ii[nt])] = np.interp(g.ndvi.values[nt], f[0], f[1])
        if ft is not None:
            out_e[nd2.index.get_indexer(ii[~nt])] = np.interp(g.ndvi.values[~nt], ft[0], ft[1])
    nd2["etf"] = out_e
    obs = pd.concat([th[["id", "date", "etf"]].assign(tier=1), nd2[["id", "date", "etf"]].dropna().assign(tier=2)])
    obs["date"] = pd.to_datetime(obs.date)
    obs = obs[(obs.date >= D0) & (obs.date <= D1)]
    obs = obs.groupby(["id", "date"], as_index=False).agg(etf=("etf", "mean"), tier=("tier", "min"))
    # weather
    wx = pd.read_csv(ROOT / "data" / "national" / "eto_daily.csv")
    wx = wx[wx.region == rid].assign(date=lambda x: pd.to_datetime(x.date)).set_index("date")
    days = pd.date_range(Y0, Y1)
    eto = {lv: wx[ETO_COL[lv]].reindex(days).interpolate().values * K[lv] for lv in K}
    pm = wx.precip_mm.reindex(days).fillna(0).groupby(days.to_period("M")).sum()
    peff_m = np.where(pm > 75, 0.8 * pm - 25, np.maximum(0.6 * pm - 10, 0))
    peff = float(peff_m.sum())
    peff_w = float(peff_m[[p.month in (11, 12, 1, 2, 3, 4) for p in pm.index]].sum())
    jjas = np.array([d.month in (6, 7, 8, 9) for d in days])
    summer = np.array([5 <= d.month <= 10 for d in days])
    t_day = (days - Y0).days.values
    rows = []
    ids_all = np.unique(nd.id)
    by = dict(tuple(obs.groupby("id")))
    for fid in ids_all:
        g = by.get(fid)
        tree = bool(is_tree.get(fid, False))
        rec = {"id": fid, "n_thermal": 0, "n_ndvi_tier": 0, "max_gap_d": np.nan, "tree": tree}
        if g is None or len(g) < 2:
            if tree:                                      # Kc fallback for tree crops with no usable relation
                for lv in K:
                    et = KC_TREE[lv] * eto[lv].sum() / K[lv]
                    rec[f"et_mm_{lv}"] = et
                    rec[f"et_mm_summer_{lv}"] = KC_TREE[lv] * eto[lv][summer].sum() / K[lv]
                    rec[f"et_mm_jjas_{lv}"] = KC_TREE[lv] * eto[lv][jjas].sum() / K[lv]
                rec["method"] = "kc_tree"
            else:
                rec["method"] = "insufficient"
            rows.append(rec)
            continue
        td = (g.date - Y0).dt.days.values
        e = g.etf.values
        daily = np.interp(t_day, td, e)
        gaps = np.diff(np.r_[td[td <= 0][-1:] if (td <= 0).any() else [0], td[(td > 0) & (td < 365)], td[td >= 365][:1] if (td >= 365).any() else [364]])
        rec.update(n_thermal=int((g.tier == 1).sum()), n_ndvi_tier=int((g.tier == 2).sum()),
                   max_gap_d=int(gaps.max()) if gaps.size else np.nan, etf_mean=round(float(daily.mean()), 4))
        for lv in K:
            et_d = daily * eto[lv]
            cap = 1.3 * eto[lv].sum()
            rec[f"et_mm_{lv}"] = float(np.clip(et_d.sum(), 0, cap))
            rec[f"et_mm_summer_{lv}"] = float(np.clip(et_d[summer].sum(), 0, 1.3 * eto[lv][summer].sum()))
            rec[f"et_mm_jjas_{lv}"] = float(np.clip(et_d[jjas].sum(), 0, 1.3 * eto[lv][jjas].sum()))
        rec["method"] = "thermal" if rec["n_thermal"] >= max(4, 0.5 * len(g)) else ("mixed" if rec["n_thermal"] > 0 else "ndvi_calibrated")
        rows.append(rec)
    df = pd.DataFrame(rows)
    df["peff_mm"] = round(peff, 1)
    df["peff_winter_mm"] = round(peff_w, 1)
    df["region"] = rid
    for c in [c for c in df.columns if c.startswith("et_mm")]:
        df[c] = df[c].round(1)
    df.to_csv(R / "et_fields.csv", index=False)
    an.to_csv(R / "et_overpasses.csv", index=False)
    meta.update(region=rid, peff_mm=round(peff, 1), eto_adj_mm=round(float(eto["central"].sum() / K["central"]), 1),
                fields=int(len(df)), methods=df.method.value_counts().to_dict())
    print(rid, f"overpasses {meta['accepted']}/{meta['overpasses']} accepted; edge w summer {meta['edge_w']['summer']}; "
               f"methods {meta['methods']}; median ET {df.et_mm_central.median():.0f} mm/yr; Peff {peff:.0f} mm", flush=True)
    return df, meta


def national(rids):
    fn = pd.read_csv(ROOT / "data" / "national" / "fields_national.csv")
    crop_all = None
    cf = ROOT / "data" / "national" / "v2" / "crop_types.csv"
    if cf.exists():
        crop_all = pd.read_csv(cf)
    parts, metas = [], []
    for rid in rids:
        crop = None
        if crop_all is not None:
            crop = crop_all[crop_all.region == rid][["id", "crop_type"]]
        elif (ROOT / "data" / "regions" / rid / "crop_types.csv").exists():
            crop = pd.read_csv(ROOT / "data" / "regions" / rid / "crop_types.csv")[["id", "crop_type"]]
        r = region(rid, crop)
        if r is not None:
            parts.append(r[0]); metas.append(r[1])
    et = pd.concat(parts, ignore_index=True)
    keep = ["region", "id", "uid", "admin", "area_ha", "is_pivot", "shield", "class", "class_s2", "water_m3_low",
            "water_m3_central", "water_m3_high", "head_m_low", "head_m_central", "head_m_high"]
    t = fn[keep].merge(et, on=["region", "id"], how="left")
    # Accounting rules: a field with no crop cycle this season (crop_types 'fallow') is not counted as irrigated; its
    # ET (sparse regrowth on rain or residual moisture; mostly on the Arabian Shield) is reported separately. Shield
    # fields (south-west; spate floods, rain and shallow alluvial wells) are reported as irrigation water whose
    # source is not determined; the groundwater headline is the sedimentary shelf.
    ctype = None
    if crop_all is not None:
        ctype = t[["region", "id"]].merge(crop_all[["region", "id", "crop_type"]], on=["region", "id"], how="left").crop_type
    t["crop_type"] = ctype.values if ctype is not None else np.nan
    t["irrigated"] = t.crop_type.ne("fallow")
    t["water_source"] = np.where(t.shield.astype(bool), "shield_undetermined", "shelf_groundwater")
    for lv in K:
        ea = np.where(t.is_pivot.astype(bool), EA_PIVOT[lv], EA_OTHER[lv])
        net = np.maximum(t[f"et_mm_{lv}"] - t.peff_mm, 0)
        t[f"net_mm_{lv}"] = net.round(1)
        t[f"noncrop_et_m3_{lv}"] = np.where(t.irrigated, 0.0, (t[f"et_mm_{lv}"] / 1000 * t.area_ha * 1e4).fillna(0)).round()
        net = np.where(t.irrigated, net, 0.0)
        t[f"water_et_m3_{lv}"] = (net / 1000 * t.area_ha * 1e4 / ea).round()
        frac_jjas = (t[f"et_mm_jjas_{lv}"] / t[f"et_mm_{lv}"]).clip(0, 1)
        work = np.where(t.shield.astype(bool), np.nan, t[f"water_et_m3_{lv}"] * RHO_G * t[f"head_m_{lv}"] / 3.6e6)
        t[f"elec_kwh_et_{lv}"] = np.round(work / PUMP_EFF)
        t[f"elec_kwh_jjas_et_{lv}"] = np.round(work / PUMP_EFF * frac_jjas)
    out = ROOT / "data" / "national" / "v2"
    out.mkdir(parents=True, exist_ok=True)
    t.to_csv(out / "fields_et.csv", index=False)
    sm = summarize(t, metas)
    (ROOT / "out" / "v2").mkdir(parents=True, exist_ok=True)
    (ROOT / "out" / "v2" / "et_summary.json").write_text(json.dumps(sm, indent=1, default=float))
    print(json.dumps({k: sm[k] for k in ("fields", "area_ha", "water_et_bn_m3", "water_benchmark_bn_m3", "methods_area_share")}, indent=1))


def summarize(t, metas):
    def bn(x):
        return round(float(np.nansum(x)) / 1e9, 3)
    rq = json.loads((ROOT / "out" / "national_summary.json").read_text()) if (ROOT / "out" / "national_summary.json").exists() else {}
    a = t.area_ha.sum()
    meth = t.groupby(t.method.fillna("no_samples")).area_ha.sum() / a
    sm = {"season": "2025-11-01..2026-10-31", "fields": int(len(t)), "area_ha": round(float(a)),
          "water_et_bn_m3": {lv: bn(t[f"water_et_m3_{lv}"]) for lv in K},
          "water_et_shelf_bn_m3": {lv: bn(t[f"water_et_m3_{lv}"][t.water_source == "shelf_groundwater"]) for lv in K},
          "water_et_shield_bn_m3": {lv: bn(t[f"water_et_m3_{lv}"][t.water_source == "shield_undetermined"]) for lv in K},
          "noncrop_et_bn_m3": {lv: bn(t[f"noncrop_et_m3_{lv}"]) for lv in K},
          "shield_ha": round(float(t[t.water_source == "shield_undetermined"].area_ha.sum())),
          "net_use_bn_m3": {lv: bn(t[f"net_mm_{lv}"] / 1000 * t.area_ha * 1e4) for lv in K},
          "water_benchmark_bn_m3": {lv: bn(t[f"water_m3_{lv}"]) for lv in K},
          "elec_twh_et": {lv: round(float(np.nansum(t[f"elec_kwh_et_{lv}"])) / 1e9, 3) for lv in K},
          "jjas_load_mw_et": {lv: round(float(np.nansum(t[f"elec_kwh_jjas_et_{lv}"])) / (122 * 24) / 1000, 1) for lv in K},
          "methods_area_share": meth.round(4).to_dict(),
          "regions": metas}
    by_class = t.groupby("class_s2").agg(area_ha=("area_ha", "sum"), et_mm=("et_mm_central", "median"),
                                         water_et=("water_et_m3_central", "sum"), water_bm=("water_m3_central", "sum"))
    sm["by_v1_class"] = {k: {"area_ha": round(float(v.area_ha)), "median_et_mm": round(float(v.et_mm), 0) if np.isfinite(v.et_mm) else None,
                             "water_et_bn_m3": round(float(v.water_et) / 1e9, 3), "water_benchmark_bn_m3": round(float(v.water_bm) / 1e9, 3)}
                         for k, v in by_class.iterrows()}
    sm["mewa_agriculture_bn_m3"] = 11.56
    sm["v1_published"] = rq.get("water_m3") if isinstance(rq.get("water_m3"), dict) else None
    return sm


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["all"]:
        rids = sorted(p.parent.name for p in (ROOT / "data" / "regions").glob("R*/landsat_thermal.csv.gz"))
        national(rids)
    else:
        for rid in args:
            crop = None
            cf = ROOT / "data" / "regions" / rid / "crop_types.csv"
            if cf.exists():
                crop = pd.read_csv(cf)[["id", "crop_type"]]
            region(rid, crop)
