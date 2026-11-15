"""Scenarios on top of the national baseline: data robustness, water and energy policy, biochar deployment.

Reads, never writes, the national inputs and outputs:
  data/regions/R*/fields_radar.csv and meta.json (through national_supply.load_fields), data/national/regions.json,
  sau_adm1.geojson and ne_50m_countries.geojson (admin_regions), data/national/fields_national.csv (baseline check),
  data/national/manure_points.csv, data/cement/saudi_cement.csv (C0), model/params.json,
  data/national/official_2024.json, model/scenario_params.json, model/scenario_cement_plants.csv
Writes only: out/national_scenarios.json, out/scenario_*.csv

Families
  A  data robustness   A0 published table; A1 radar-verified floor (quality check on, southwest apart) with Monte
                       Carlo ranges and validation on the same table; A2 grid of data rules; A4 floor-to-ceiling
                       bracket against official statistics
  B  water and energy  B1 MEWA perennial-fodder halt from 16 Nov 2026 (pre-rule baseline, savings, watch-list);
                       B2 pivot retrofits with and without a cap on re-use of freed water
  C  biochar           C0 published siting; C1 radar-verified floor and modelled upside under realistic outlets:
                       per-plant cement caps (dose x 2024 output, low-ash chars only, haul limit) and a soil outlet
                       limited by the radar-active farmland within reach; sensitivities on dose, crediting, radius

Field tables are rebuilt with national_supply's own loader (quality check on and off) and accounted with
national_supply.flows; the rebuild at the published setting must equal fields_national.csv column by column on every
run. C0 calls national_siting.run itself. run_id fingerprints every input file.

Usage: .venv/bin/python model/national_scenarios.py [scenario ids ...]   (default: all)
"""
import contextlib
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "model"))
import national_siting as NS  # noqa: E402
import national_supply as SUP  # noqa: E402

LV = ("low", "central", "high")
RHO_G = 1000 * 9.81
CO2_PER_C = 44 / 12
FLOW_KEYS = ("water_m3", "elec_kwh", "elec_kwh_summer", "co2_t_grid", "co2_t_diesel", "straw_t_dry", "fronds_t_dry")
IRRIGATED = ("winter_only", "summer_only", "wheat_rotation", "year_round", "palm_grove", "partly_seen_active")


def SP():
    raw = json.loads((ROOT / "model" / "scenario_params.json").read_text())
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def OFF():
    return json.loads((ROOT / "data" / "national" / "official_2024.json").read_text())


# ================================================================ fields: classification and accounting
def load_fields():
    """The published field table (written by model/national_supply.py)."""
    return pd.read_csv(ROOT / "data" / "national" / "fields_national.csv", low_memory=False)


def base_table(qc):
    """Field table built exactly as national_supply.main builds it, with the radar quality check on or off:
    load_fields (dedupe, season flags), admin regions, fields abroad dropped, classes."""
    df = SUP.admin_regions(SUP.load_fields(qc))
    df = df[df.admin != "abroad"].drop(columns=["country"], errors="ignore").reset_index(drop=True)
    df["class"] = df.apply(SUP.classify, axis=1)
    return df


def load_metas():
    return {p.parent.name: json.loads(p.read_text()) for p in (ROOT / "data" / "regions").glob("R*/meta.json")}


def _obj(flag, known):
    """Boolean array -> object Series of True/False, NaN where not known."""
    return pd.Series(np.where(known, flag, None), dtype=object).where(known, np.nan)


def reclassify(df, fill_winter_from_s2=False, season_rule="radar"):
    """Season flags and classes as national_supply builds them (the input table already carries the quality-check
    setting), with options:
      fill_winter_from_s2  an unobserved winter takes the Sentinel-2 winter flag
      season_rule          'radar' (default); 'both' = active only where radar and Sentinel-2 agree (unknown stays
                           unknown); 'either' = radar or Sentinel-2 active (a ceiling: fields are green pixels)"""
    d = df.copy().reset_index(drop=True)
    wa, sa = SUP.tri(d.winter_active), SUP.tri(d.summer_active)
    radar_obs = (wa.notna() | sa.notna()).values  # palm groves need at least one season the radar itself observed
    s2w, s2s = SUP.tri(d.s2_winter_active), SUP.tri(d.s2_summer_active)
    seen = SUP.tri(d.radar_seen).eq(True)
    if fill_winter_from_s2:
        fill = wa.isna() & seen & s2w.notna()
        wa[fill] = s2w[fill]
    if season_rule == "both":
        wa = _obj((wa.eq(True) & s2w.eq(True)).values, wa.notna().values)
        sa = _obj((sa.eq(True) & s2s.eq(True)).values, sa.notna().values)
    elif season_rule == "either":
        wa = _obj((wa.eq(True) | s2w.eq(True)).values, (wa.notna() | s2w.notna()).values & seen.values)
        sa = _obj((sa.eq(True) | s2s.eq(True)).values, (sa.notna() | s2s.notna()).values & seen.values)
    d["winter_active"], d["summer_active"] = wa.values, sa.values
    wa, sa = d.winter_active, d.summer_active
    d["palm_grove"] = ((d.tree_frac >= 0.3) & radar_obs
                       & (wa.isna() | wa.eq(True)) & (sa.isna() | sa.eq(True)))
    if "spring_brown" in d:
        d["spring_brown"] = SUP.tri(d.spring_brown)
    d["class"] = d.apply(SUP.classify, axis=1)
    return d


def accounting(d, p=None, eff_override=None):
    """national_supply.flows on a copy. eff_override (a number) is an irrigation upgrade: each level's efficiency
    becomes max(its value, eff_override), so an upgrade never makes a system less efficient."""
    p = p or SUP.P()
    if eff_override is not None:
        base = p["pivot_application_efficiency"]
        eff_override = {lv: max(base[lv], eff_override) for lv in LV}
    return SUP.flows(d.copy(), p, eff_override=eff_override)


def totals(d):
    t = {"fields": int(len(d)), "field_ha": round(float(d.area_ha.sum())),
         "farmed_ha": round(float(d[d.winter_active.eq(True) | d.summer_active.eq(True)].area_ha.sum())),
         "active_ha": {se: round(float(d[d[f"{se}_active"].eq(True)].area_ha.sum())) for se in ("winter", "summer")},
         # every radar-seen field whose season is unknown (incl. fields with neither season classified and palm groves
         # with one season unknown); national_supply's season_not_observed_ha counts one-season-observed fields only
         "season_unknown_ha": {se: round(float(d[d[f"{se}_active"].isna() & SUP.tri(d.radar_seen).eq(True)].area_ha.sum()))
                               for se in ("winter", "summer")},
         "area_ha_by_class": d.groupby("class").area_ha.sum().round().to_dict()}
    for k in FLOW_KEYS:
        t[k] = {l: round(float(np.nansum(d[f"{k}_{l}"]))) for l in LV}
    t["summer_pumping_avg_mw"] = {l: round(t["elec_kwh_summer"][l] / (122 * 24) / 1000, 1) for l in LV}
    return t


def validation(d, skip=()):
    """Area-weighted agreement of radar season flags with Sentinel-2 on this table, over fields where both are
    known (winter: Sentinel-2 over the radar's own Dec-Jan dates; summer: Sentinel-2 Jun-Oct). Seasons in skip
    (filled from Sentinel-2) are not validated against Sentinel-2."""
    out = {}
    for se, ref in (("winter", "s2_winter_check"), ("summer", "s2_summer_active")):
        if se in skip:
            continue
        r, s = SUP.tri(d[f"{se}_active"]), SUP.tri(d[ref])
        m = r.notna() & s.notna()
        if not m.any():
            continue
        w, r, s = d.area_ha[m].values, r[m].astype(bool).values, s[m].astype(bool).values
        tp, fp, fn, tn = (float(w[r & s].sum()), float(w[r & ~s].sum()), float(w[~r & s].sum()), float(w[~r & ~s].sum()))
        tot = tp + fp + fn + tn
        po = (tp + tn) / tot
        pe = ((tp + fp) * (tp + fn) + (fn + tn) * (fp + tn)) / tot ** 2
        prec, rec = (tp / (tp + fp) if tp + fp else None), (tp / (tp + fn) if tp + fn else None)
        out[se] = {"validated_ha": round(tot), "agreement": round(po, 3), "chance_agreement": round(pe, 3),
                   "kappa": round((po - pe) / (1 - pe), 3) if pe < 1 else None,
                   "precision": round(prec, 3) if prec is not None else None, "recall": round(rec, 3) if rec is not None else None,
                   "radar_ha": round(tp + fp), "s2_ha": round(tp + fn)}
    return out


def check_baseline(built, published):
    """The table rebuilt with national_supply's loader and accounted with national_supply.flows must equal the
    published fields_national.csv: same fields in the same order (uid) and every shared column equal."""
    d = accounting(reclassify(built))
    if len(d) != len(published) or not (d.uid.values == published.uid.values).all():
        raise SystemExit(f"baseline mismatch: field lists differ ({len(d)} rebuilt vs {len(published)} published)")
    bad = []
    for c in published.columns:
        if c not in d.columns:
            continue
        a, b = d[c], published[c]
        if pd.api.types.is_numeric_dtype(b) and pd.api.types.is_numeric_dtype(a):
            ok = np.allclose(np.nan_to_num(a.values.astype(float)), np.nan_to_num(b.values.astype(float)), atol=1.0)
        else:  # flags and labels: compare as text, gaps as empty
            norm = lambda s: s.map(lambda v: "" if pd.isna(v) else str(v))  # noqa: E731
            ok = (norm(a).values == norm(b).values).all()
        if not ok:
            bad.append(c)
    if bad:
        raise SystemExit("baseline mismatch with fields_national.csv in columns: " + ", ".join(bad))
    return d


def _tri_ppf(u, lo, mode, hi):
    lo, hi = min(lo, hi), max(lo, hi)
    mode = min(max(mode, lo), hi)
    if hi - lo < 1e-12:
        return np.full_like(u, lo, dtype=float)
    fc = (mode - lo) / (hi - lo)
    return np.where(u < fc, lo + np.sqrt(u * (hi - lo) * (mode - lo)), hi - np.sqrt((1 - u) * (hi - lo) * (hi - mode)))


def monte_carlo(d, sp):
    """P5/P50/P95 of the totals: triangular(low, central, high) per factor; irrigation depths share one quantile,
    lift one quantile across regions, everything else independent. Vectorised on class x lift-region areas."""
    mc = sp["monte_carlo"]
    rng = np.random.default_rng(mc["seed"])
    n = mc["n"]
    p, lifts = SUP.P(), OFF()["lift_m"]
    cls = d["class"]
    part_s = cls.eq("partly_seen_active") & d.summer_active.eq(True)
    part_w = cls.eq("partly_seen_active") & d.winter_active.eq(True)
    groups = {"win": cls.eq("winter_only") | part_w, "smr": cls.eq("summer_only") | part_s, "rot": cls.eq("wheat_rotation"),
              "yr": cls.isin(["year_round", "palm_grove"])}
    shield = SUP.tri(d.shield).eq(True) if d.shield.dtype == object else d.shield.astype(bool)
    keys = sorted(d.lift_key.unique())
    A = {g: np.array([d.area_ha[m & (d.lift_key == k)].sum() for k in keys]) for g, m in groups.items()}
    Ae = {g: np.array([d.area_ha[m & (d.lift_key == k) & ~shield].sum() for k in keys]) for g, m in groups.items()}
    ud, ue, ul = rng.random(n), rng.random(n), rng.random(n)
    ind = {k: rng.random(n) for k in ("pump", "grid", "straw", "palms", "resid")}
    t = lambda key, u: _tri_ppf(u, p[key]["low"], p[key]["central"], p[key]["high"])  # noqa: E731
    win, smr, yr = t("irrigation_mm_winter_only", ud), t("irrigation_mm_summer_crop", ud), t("irrigation_mm_year_round", ud)
    eff = t("pivot_application_efficiency", ue)
    lift = np.stack([_tri_ppf(ul, lifts[k]["low"], lifts[k]["central"], lifts[k]["high"]) for k in keys], axis=1)  # n x regions
    depth = {"win": win, "smr": smr, "rot": win + smr, "yr": yr}
    share = {"win": 0 * win, "smr": 1 + 0 * win, "rot": smr / (win + smr), "yr": 0.5 + 0 * win}
    water = sum(depth[g] * 10 / eff * A[g].sum() for g in groups)          # m3 (mm x 10 = m3/ha)
    we = {g: (depth[g] * 10 / eff)[:, None] * Ae[g][None, :] for g in groups}  # n x regions, non-shield
    pe = t("pump_wire_to_water_eff", ind["pump"])
    elec = sum((we[g] * lift).sum(axis=1) for g in groups) * RHO_G / 3.6e6 / pe
    elec_s = sum((we[g] * lift).sum(axis=1) * share[g] for g in groups) * RHO_G / 3.6e6 / pe
    co2 = elec * t("grid_kgco2e_per_kwh", ind["grid"]) / 1000
    a_wheat = float(d.area_ha[cls.isin(["winter_only", "wheat_rotation"])].sum())
    a_palm = float(d.area_ha[cls.eq("palm_grove")].sum())
    straw = a_wheat * t("straw_t_dry_per_ha", ind["straw"])
    fronds = a_palm * t("palms_per_ha", ind["palms"]) * t("palm_residue_kg_dry_per_palm", ind["resid"]) / 1000
    q = lambda x: {"p5": float(np.percentile(x, 5)), "p50": float(np.percentile(x, 50)), "p95": float(np.percentile(x, 95))}  # noqa: E731
    return {"n": n, "seed": mc["seed"], "water_m3": q(water), "elec_kwh": q(elec), "co2_t_grid": q(co2),
            "summer_pumping_avg_mw": q(elec_s / (122 * 24) / 1000), "straw_t_dry": q(straw), "fronds_t_dry": q(fronds)}


# ================================================================ B: water and energy policy
def fodder_halt(d, regions, variant="seasonal", compliance=1.0):
    """MEWA perennial-fodder halt. Year-round fields in the named regions switch to seasonal winter fodder
    ('seasonal': winter depth, no straw because forage is cut green), to winter wheat ('wheat': straw on), or go
    fallow ('fallow'). compliance scales each field's change. Returns (accounted table, scope mask, baseline)."""
    scope = d["class"].eq("year_round") & d.admin.isin(regions)
    base = accounting(d)
    sw = d.copy()
    sw.loc[scope, "class"] = "fallow" if variant == "fallow" else "winter_only"
    sw = accounting(sw)
    if variant == "seasonal":
        for l in LV:
            sw.loc[scope, f"straw_t_dry_{l}"] = 0.0
    cols = [f"{k}_{l}" for k in FLOW_KEYS for l in LV]
    out = base.copy()
    out[cols] = base[cols].values + compliance * (sw[cols].fillna(0).values - base[cols].fillna(0).values)
    return out, scope, base


def watchlist(d, scope, metas):
    thr = {rid: m.get("validation", {}).get("thresholds_db", {}) for rid, m in metas.items()}
    w = d.loc[scope, ["uid", "region", "admin", "lon", "lat", "area_ha", "tree_frac", "hv_above_desert_winter", "hv_above_desert_summer"]].copy()
    for se in ("winter", "summer"):
        t = w.region.map(lambda r: thr.get(r, {}).get(se, np.nan))
        w[f"{se}_margin_db"] = (w[f"hv_above_desert_{se}"] - t).round(2)
    return w.sort_values("area_ha", ascending=False)


def retrofit(d, sp, eff_new, rebound):
    """Pivot retrofit (central level): pivots (circularity > 0.75, >= 10 ha, irrigated class) move from medium-
    pressure sprinklers (efficiency and pressure head from scenario_params) to the new efficiency at low pressure.
    Energy counts static lift plus pressure head. Uncapped, a share 'rebound' of the freed water irrigates new land."""
    r0 = sp["pivot_retrofit"]
    p, lifts = SUP.P(), OFF()["lift_m"]
    sprinkled = [c for c in IRRIGATED if c != "palm_grove"]  # palm groves are not on sprinkler pivots
    piv = (d.circularity > 0.75) & (d.area_ha >= 10) & d["class"].isin(sprinkled)
    shield = SUP.tri(d.shield).eq(True) if d.shield.dtype == object else d.shield.astype(bool)
    lift = d.lift_key.map(lambda k: lifts[k]["central"])
    pe, ef = p["pump_wire_to_water_eff"]["central"], p["grid_kgco2e_per_kwh"]["central"]
    w0 = d.water_m3_central.where(piv, 0.0) * p["pivot_application_efficiency"]["central"] / r0["baseline_efficiency"]
    w1 = w0 * r0["baseline_efficiency"] / eff_new
    e = lambda w, h: (w * RHO_G * (lift + h) / 3.6e6 / pe).where(~shield, 0.0)  # noqa: E731
    share = (d.elec_kwh_summer_central / d.elec_kwh_central).where(d.elec_kwh_central > 0, 0.0).fillna(0)
    e0, e1 = e(w0, r0["baseline_pressure_head_m"]), e(w1, r0["low_pressure_head_m"])
    freed = (w0 - w1).sum()
    reuse = rebound * freed
    dw_e = ((w0 - w1) * RHO_G * (lift + r0["low_pressure_head_m"]) / 3.6e6 / pe).where(~shield, 0.0)  # freed water re-pumped
    e_reuse, es_reuse = rebound * dw_e.sum(), rebound * (dw_e * share).sum()
    es0, es1 = (e0 * share).sum(), (e1 * share).sum()
    return {"pivot_fields": int(piv.sum()), "pivot_ha": round(float(d.area_ha[piv].sum())),
            "pivot_water_m3": round(float(w0.sum())), "pumped_water_saved_m3": round(float(freed - reuse)),
            "elec_baseline_with_pressure_kwh": round(float(e0.sum())),
            "elec_saved_kwh": round(float(e0.sum() - e1.sum() - e_reuse)),
            "summer_mw_saved": round(float(es0 - es1 - es_reuse) / (122 * 24) / 1000, 1),
            "co2_saved_t": round(float((e0.sum() - e1.sum() - e_reuse) * ef / 1000)),
            "note": "Pumped water saved, not consumptive use: crop water need is unchanged; how much of the losses "
                    "returned to the aquifer is unknown, so depletion saved is at most this. The lower pressure head "
                    "saves energy even when all freed water is re-used"}


# ================================================================ C: biochar siting
def cement_table():
    """Cement outlets for the capped scenarios: model/scenario_cement_plants.csv (2024 sales per plant, corrected
    locations), with coordinates missing there taken from data/cement/saudi_cement.csv row by row (its first 19 rows
    keep their order; rows added later sit at the end)."""
    c0 = pd.read_csv(ROOT / "data" / "cement" / "saudi_cement.csv")
    c = pd.read_csv(ROOT / SP()["cement_plants_file"]["value"])
    for i in range(min(len(c), len(c0))):
        if pd.isna(c.at[i, "lon"]) or pd.isna(c.at[i, "lat"]):
            c.at[i, "lon"], c.at[i, "lat"] = c0.at[i, "lon"], c0.at[i, "lat"]
    c["output_t"] = c.cement_sales_2024_mt * 1e6
    return c


@contextlib.contextmanager
def _supply_root(d):
    """Let national_siting.supply read a scenario field table: a temporary ROOT with that table as
    fields_national.csv and a link to the real manure points, so the feed maps stay national_siting's own."""
    tmp = Path(tempfile.mkdtemp(prefix="scen_"))
    (tmp / "data" / "national").mkdir(parents=True)
    cols = ["lon", "lat", "region"] + [f"{k}_{l}" for k in ("straw_t_dry", "fronds_t_dry") for l in LV]
    d[cols].to_csv(tmp / "data" / "national" / "fields_national.csv", index=False)
    mp = ROOT / "data" / "national" / "manure_points.csv"
    if mp.exists():
        (tmp / "data" / "national" / "manure_points.csv").symlink_to(mp)
    (tmp / "model").symlink_to(ROOT / "model")  # supply() also reads model/params.json (persistence table, dry matter)
    old = NS.ROOT
    NS.ROOT = tmp
    try:
        yield
    finally:
        NS.ROOT = old
        shutil.rmtree(tmp, ignore_errors=True)


def supply_from(d, level, p, feeds=None):
    with _supply_root(d):
        return NS.supply(level, p, feeds)


def published_siting(size_t):
    """C0: the published siting itself (national_siting.run on the published table, closed cement plants dropped,
    as national_siting.main does), translated to this engine's plant columns and summary."""
    p = NS.params("central")
    cem = pd.read_csv(ROOT / "data" / "cement" / "saudi_cement.csv")
    if "status" in cem:
        cem = cem[cem.status != "Closed"].reset_index(drop=True)
    df, s = NS.run("central", size_t, cem, p)
    if not len(df):
        return df, s
    to_cem = df.best_outlet.eq("cement")
    # credited removal before transport, backed out of the rounded transport share (within ~1 t per plant)
    before = df.net_removal_tco2 / (1 - df.transport_share.clip(upper=0.999999))
    transport = before - df.net_removal_tco2
    retained = np.where(to_cem, df["cement_retained_tco2"] - transport, df.net_removal_tco2)
    out = pd.DataFrame({"lon": df.lon, "lat": df.lat, "kind": df.kind, "name": df["name"], "feed_t_dry": df.feed_t_dry,
                        "char_t": df.char_t, "char_to_cement_t": np.where(to_cem, df.char_t, 0),
                        "char_to_soil_t": np.where(to_cem, 0, df.char_t), "char_unplaced_t": 0,
                        "cement_parts": np.where(to_cem, df.cement_name + ":" + df.char_t.astype(str) + "@" + df.cement_km.round().astype(int).astype(str) + "km", ""),
                        "net_removal_tco2": df.net_removal_tco2, "credited_tco2": df.net_removal_tco2,
                        "retained_tco2": np.round(retained), "transport_tco2": np.round(transport),
                        **{f"feed_{f}": df[f"feed_{f}"] for f in ("straw", "fronds", "litter", "manure")}, "plant": df.plant})
    return out, s


def site2(s, size_t, p, cement=None, allowance=None, soil=None, credit="puro", radius_km=NS.RADIUS_KM,
          max_char_haul_km=300, cement_feeds=("straw", "fronds"), min_outlet_share=0.0):
    """Greedy siting with realistic outlets.
      s          supply (national_siting.supply format)
      cement     cement outlets (lon, lat, city) with 'allowance' = char each can take (t/yr); only chars of
                 cement_feeds may go there, nearest first within max_char_haul_km, and only where cement beats soil
      soil       None (unlimited soil, char returned along the feed haul) or a dict: lon, lat, cap (char-dose units
                 per field, t/yr at the central dose), units ({feed: units per t char}), radius_km. Char that finds
                 no capacity within the radius is unplaced and earns nothing.
      credit     'puro' (char in cement credited like soil, Puro 2025 v2 rule 6.2.4) or 'retention' (in-service)
      min_outlet_share  a site is built only if at least this share of its char has an outlet
    Every plant records credited (Puro) and retained (in-service) removal, net of truck emissions."""
    lon, lat = s.lon.values, s.lat.values
    dry = s.dry_t.values.astype(float).copy()
    wpd, cpt, chpt, perm, feed = s.wet_per_dry.values, s.c_per_t.values, s.char_t_per_t.values, s.soil_perm.values, s.feed.values
    elig = np.isin(feed, cement_feeds)
    ef, circ, ret = p["truck_kgco2e_per_tkm"] / 1000, p["road_circuity"], p["cement_retention"]
    grid = s.assign(gx=(s.lon / 0.25).round() * 0.25, gy=(s.lat / 0.25).round() * 0.25)[["gx", "gy"]].drop_duplicates()
    parts_s = [pd.DataFrame({"lon": grid.gx, "lat": grid.gy, "kind": "grid", "name": ""})]
    if cement is not None:
        parts_s.insert(0, pd.DataFrame({"lon": cement.lon, "lat": cement.lat, "kind": "cement", "name": cement.city.fillna("") + " cement"}))
    sites = pd.concat(parts_s, ignore_index=True)
    s_lon, s_lat, s_kind, s_name = sites.lon.values, sites.lat.values, sites.kind.values, sites.name.values
    allow = None if allowance is None else np.array(allowance, dtype=float).copy()
    dcem = (NS.hav(s_lon[:, None], s_lat[:, None], cement.lon.values[None, :], cement.lat.values[None, :]) * circ
            if cement is not None else None)
    if soil is not None:  # fields within the return radius of each candidate site, nearest first
        cap = np.array(soil["cap"], dtype=float).copy()
        flon, flat = np.asarray(soil["lon"]), np.asarray(soil["lat"])
        near_f = []
        for i in range(len(sites)):
            dd = NS.hav(s_lon[i], s_lat[i], flon, flat) * circ
            idx = np.flatnonzero(dd <= soil["radius_km"])
            o = np.argsort(dd[idx])
            near_f.append((idx[o], dd[idx][o]))
        unit = np.vectorize(lambda f: soil["units"].get(f, 1.0))(feed)
        # with farmland the binding outlet, a plant draws its most valuable feed first: cement-eligible chars, then
        # the highest credit per unit of farmland (straw/fronds > manure > litter); distance breaks ties
        val = cpt * perm * CO2_PER_C / chpt / unit
        prio = np.where(elig, -np.inf, -val)
    alive, plants = dry > 1e-6, []
    while alive.any() and len(plants) < NS.MAX_PLANTS:
        ia, best = np.flatnonzero(alive), None
        for i in range(len(sites)):
            d = NS.hav(s_lon[i], s_lat[i], lon[ia], lat[ia]) * circ
            near = np.where(d <= radius_km)[0]
            if not len(near) or dry[ia][near].sum() < 0.8 * size_t:
                continue
            o = near[np.lexsort((d[near], prio[ia][near]))] if soil is not None else near[np.argsort(d[near])]
            k = int(np.searchsorted(np.cumsum(dry[ia][o]), size_t) + 1)
            take = o[:min(k, len(o))]
            g = ia[take]
            w = dry[g].copy()
            if w.sum() > size_t:
                w[-1] -= w.sum() - size_t
            feed_tkm = float((w * wpd[g] * d[take]).sum())
            mean_km = float((w * d[take]).sum() / w.sum())
            ch = w * chpt[g]                                   # char by supply point
            e = elig[g]
            char_e, char_o = float(ch[e].sum()), float(ch[~e].sum())
            f_e = float((w * cpt[g] * perm[g])[e].sum()) * CO2_PER_C / char_e if char_e else 0.0   # credited t CO2 / t char
            f_o = float((w * cpt[g] * perm[g])[~e].sum()) * CO2_PER_C / char_o if char_o else 0.0
            g_e = float((w * cpt[g])[e].sum()) * CO2_PER_C * ret / char_e if char_e else 0.0      # in-service, cement
            u_o = float((ch * (unit[g] if soil is not None else 1.0))[~e].sum()) / char_o if char_o else 1.0
            u_e = float((ch * (unit[g] if soil is not None else 1.0))[e].sum()) / char_e if char_e else 1.0
            # soil option: capacity within the return radius, nearest first
            if soil is not None:
                fi, fd = near_f[i]
                cc = cap[fi]
                cum = np.cumsum(cc)
                avail = float(cum[-1]) if len(cum) else 0.0
                need = char_e * u_e + char_o * u_o
                kk = int(np.searchsorted(cum, min(need, avail))) + 1 if len(cum) else 0
                soil_km = float((cc[:kk] * fd[:kk]).sum() / max(cc[:kk].sum(), 1e-9)) if kk else 0.0
            else:
                avail, soil_km = np.inf, mean_km
            # cement option for eligible char. With farmland limited (a shared, depleting outlet), eligible char goes
            # to cement wherever allowance remains within the haul limit, keeping farmland for chars only soil can take;
            # with soil unlimited, only where cement beats soil per tonne after haul
            parts, left = [], char_e
            if allow is not None and char_e > 0:
                cem_val = g_e if credit == "retention" else f_e
                for j in np.argsort(dcem[i]):
                    if left <= 1e-9 or dcem[i, j] > max_char_haul_km:
                        break
                    worth = cem_val - dcem[i, j] * ef
                    if allow[j] <= 0 or worth <= 0 or (soil is None and worth <= f_e - soil_km * ef):
                        continue
                    a = min(left, allow[j])
                    parts.append((j, a))
                    left -= a
            to_cem = char_e - left
            # soil placement: eligible remainder first (higher persistence, lower salts), then the rest
            units_left = avail
            soil_e = min(left, units_left / u_e) if u_e else left
            units_left -= soil_e * u_e
            soil_o = min(char_o, units_left / u_o) if u_o else char_o
            unplaced = (left - soil_e) + (char_o - soil_o)
            if min_outlet_share and unplaced > (1 - min_outlet_share) * (char_e + char_o) + 1e-9:
                continue  # no developer builds a plant whose char has nowhere to go
            haul = feed_tkm + sum(a * dcem[i, j] for j, a in parts) + (soil_e + soil_o) * soil_km
            credited = (to_cem + soil_e) * f_e + soil_o * f_o - haul * ef
            retained = to_cem * g_e + soil_e * f_e + soil_o * f_o - haul * ef
            net = credited if credit == "puro" else retained
            if best is None or net > best["net_removal_tco2"]:
                best = {"lon": float(s_lon[i]), "lat": float(s_lat[i]), "kind": s_kind[i], "name": s_name[i],
                        "feed_t_dry": float(w.sum()), "char_t": round(char_e + char_o), "char_to_cement_t": round(to_cem),
                        "char_to_soil_t": round(soil_e + soil_o), "char_unplaced_t": round(unplaced),
                        "cement_parts": ";".join(f"{cement.city.iloc[j]} ({cement.company.iloc[j]}):{round(a)}@{round(float(dcem[i, j]))}km"
                                                 if "company" in cement else f"{cement.city.iloc[j]}:{round(a)}@{round(float(dcem[i, j]))}km"
                                                 for j, a in parts),
                        "soil_haul_km": round(soil_km, 1), "net_removal_tco2": net, "credited_tco2": round(credited),
                        "retained_tco2": round(retained), "transport_tco2": round(haul * ef),
                        **{f"feed_{f}": round(float(w[feed[g] == f].sum())) for f in ("straw", "fronds", "litter", "manure")},
                        "_g": g, "_w": w, "_parts": parts, "_i": i, "_soil_units": soil_e * u_e + soil_o * u_o}
        if best is None:
            break
        g, w, parts, i, su = best.pop("_g"), best.pop("_w"), best.pop("_parts"), best.pop("_i"), best.pop("_soil_units")
        dry[g] -= w
        alive[g] = dry[g] > 1e-6
        for j, a in parts:
            allow[j] -= a
        if soil is not None and su > 0:  # use up capacity nearest first
            fi, _ = near_f[i]
            cum = np.cumsum(cap[fi])
            kk = int(np.searchsorted(cum, su))
            cap[fi[:kk]] = 0.0
            if kk < len(fi):
                cap[fi[kk]] = max(0.0, cum[kk] - su)
        best["net_removal_tco2"] = round(best["net_removal_tco2"])
        best["plant"] = len(plants) + 1
        plants.append(best)
    return pd.DataFrame(plants), allow


def siting_summary(df, s, cement=None, allow0=None, allow=None, avoided=None):
    if not len(df):
        return {"plants": 0, "credited_tco2": 0, "retained_tco2": 0, "supply_t": round(float(s.dry_t.sum()))}
    fu = {f: round(float(df[f"feed_{f}"].sum())) for f in ("straw", "fronds", "litter", "manure")}
    out = {"plants": int(len(df)), "feed_used_t": round(float(df.feed_t_dry.sum())), "supply_t": round(float(s.dry_t.sum())),
           "supply_by_feed_t": s.groupby("feed").dry_t.sum().round().to_dict(), "feed_used_by_feed_t": fu,
           "radar_feed_share": round((fu["straw"] + fu["fronds"]) / max(float(df.feed_t_dry.sum()), 1), 4),
           "char_t": round(float(df.char_t.sum())), "char_to_cement_t": round(float(df.char_to_cement_t.sum())),
           "char_to_soil_t": round(float(df.char_to_soil_t.sum())), "char_unplaced_t": round(float(df.char_unplaced_t.sum())),
           "credited_tco2": round(float(df.credited_tco2.sum())), "retained_tco2": round(float(df.retained_tco2.sum())),
           "transport_tco2": round(float(df.transport_tco2.sum())),
           "feed_left_by_feed_t": {f: round(float(s[s.feed == f].dry_t.sum()) - fu[f]) for f in fu}}
    if allow0 is not None and allow is not None:
        used = np.array(allow0) - np.array(allow)
        out["cement_use"] = [{"plant": f"{cement.city.iloc[j]} ({cement.company.iloc[j]})" if "company" in cement else cement.city.iloc[j],
                              "allowance_t": round(float(allow0[j])), "char_t": round(float(used[j])),
                              "at_cap": bool(allow[j] <= 1e-6 and allow0[j] > 0)} for j in range(len(cement)) if used[j] > 0.5]
    if avoided:
        out["avoided_cement_tco2_not_removal"] = {k: round(out["char_to_cement_t"] * v) for k, v in avoided.items()}
    return out


# ================================================================ scenario registry
def scenarios(sp):
    dos, sw = sp["cement_dosage_share"], tuple(sp["southwest_admin"]["values"])
    c = dos["central"]
    S = {
        "A0_published": {"family": "A", "name": "Published table (no radar quality check, southwest in)", "fields": {}},
        "A1_floor": {"family": "A", "name": "Radar-verified floor: quality check on, southwest apart", "fields": {"qc": True, "drop_admin": sw},
                     "mc": True, "headline": True},
        "A1_southwest_line": {"family": "A", "name": "Southwest regions alone (low confidence)", "fields": {"qc": True, "keep_admin": sw}},
        "A4_both": {"family": "A", "name": "Bracket floor: radar and Sentinel-2 agree (QC on, southwest in)", "fields": {"qc": True, "season_rule": "both"}, "bracket": True},
        "A4_radar": {"family": "A", "name": "Bracket: radar rule (QC on, southwest in)", "fields": {"qc": True}, "bracket": True},
        "A4_s2fill": {"family": "A", "name": "Bracket: radar, unobserved winters from Sentinel-2 (QC on, southwest in)", "fields": {"qc": True, "fill_winter_from_s2": True}, "bracket": True},
        "A4_either": {"family": "A", "name": "Bracket ceiling: radar or Sentinel-2 (QC on, southwest in)", "fields": {"qc": True, "season_rule": "either"}, "bracket": True},
    }
    for qc in (False, True):
        for swo in (False, True):
            for fill in (False, True):
                S[f"A2_qc{int(qc)}_sw{'out' if swo else 'in'}_w{'s2' if fill else 'radar'}"] = {
                    "family": "A2", "name": f"QC {'on' if qc else 'off'}, southwest {'out' if swo else 'in'}, winter {'from Sentinel-2 where unobserved' if fill else 'radar only'}",
                    "fields": {"qc": qc, "drop_admin": sw if swo else (), "fill_winter_from_s2": fill}}
    for v, comp in [("seasonal", c_) for c_ in sorted(sp["fodder_compliance"]["values"], reverse=True)] + [("wheat", 1.0), ("fallow", 1.0)]:
        S[f"B1_{v}_{int(comp * 100)}"] = {"family": "B", "name": f"Fodder halt: year-round fields to {'seasonal winter fodder' if v == 'seasonal' else 'winter wheat' if v == 'wheat' else 'fallow'}, {int(comp * 100)}% compliance",
                                          "fields": {"qc": True, "drop_admin": sw}, "fodder": {"variant": v, "compliance": comp}}
    for lab, key in (("LESA", "lesa_efficiency"), ("LEPA", "lepa_efficiency")):
        S[f"B2_{lab.lower()}"] = {"family": "B2", "name": f"Pivot retrofit to {lab}", "fields": {"qc": True, "drop_admin": sw}, "retrofit": key}
    S["C0_published"] = {"family": "C", "name": "As published: soil or nearest cement by haul, both unlimited (gross)", "published": True,
                         "note": "The national page's siting: Puro crediting, no limit on soil absorption or cement uptake"}
    base = {"fields": {"qc": True, "drop_admin": sw}, "credit": "puro", "dosage": c, "soil_dose": sp["soil_dose_t_per_ha"]["central"]}
    S["C1_F1"] = base | {"family": "C", "name": "Radar-measured feed (straw, fronds): the floor", "feeds": ("straw", "fronds")}
    S["C1_F2"] = base | {"family": "C", "name": "Radar feed + modelled litter", "feeds": ("straw", "fronds", "litter")}
    S["C1_F3"] = base | {"family": "C", "name": "All feeds: radar feed + modelled litter and manure", "feeds": None}
    S["C1_F1_25kt"] = S["C1_F1"] | {"name": "Radar-measured feed, 25 kt plants", "size": 25000}
    S["C1_F1_10kt"] = S["C1_F1"] | {"name": "Radar-measured feed, 10 kt plants", "size": 10000}
    S["C1_F3_soil_unlimited"] = S["C1_F3"] | {"name": "All feeds, soil absorption unlimited", "soil_dose": None}
    for sd in sp["soil_dose_t_per_ha"]["values"]:
        if sd != sp["soil_dose_t_per_ha"]["central"]:
            S[f"C1_F3_soildose_{sd:g}"] = S["C1_F3"] | {"name": f"All feeds, soil dose {sd:g} t/ha/yr", "soil_dose": sd}
    for v in dos["values"]:
        if v != c:
            S[f"C1_F3_dose_{100 * v:g}pct"] = S["C1_F3"] | {"name": f"All feeds, cement dose {100 * v:g}%", "dosage": v}
    S["C1_F3_all_feeds_to_cement"] = S["C1_F3"] | {"name": "All feeds, manure and litter chars also allowed in cement", "cement_feeds": ("straw", "fronds", "litter", "manure")}
    S["C3_F3_retention"] = S["C1_F3"] | {"name": "All feeds, sited for in-service retention in cement (not Puro)", "credit": "retention"}
    S["C3_E1_no_litter"] = base | {"family": "C", "name": "Litter fails the H/Corg gate: radar feed + manure", "feeds": ("straw", "fronds", "manure")}
    for r in sp["haul_radius_km"]["values"]:
        S[f"C6_radius_{int(r)}"] = S["C1_F3"] | {"name": f"All feeds, haul radius {int(r)} km", "radius": r}
    return S


def table_for(bases, spec, metas, sp):
    f = spec.get("fields", {})
    d = reclassify(bases[bool(f.get("qc", False))], fill_winter_from_s2=f.get("fill_winter_from_s2", False),
                   season_rule=f.get("season_rule", "radar"))
    if f.get("drop_admin"):
        d = d[~d.admin.isin(f["drop_admin"])].reset_index(drop=True)
    if f.get("keep_admin"):
        d = d[d.admin.isin(f["keep_admin"])].reset_index(drop=True)
    return d


def bracket_by_region(d):
    off = OFF()
    rows = []
    for name, o in off["regions"].items():
        x = d[d.admin == name]
        rows.append({"region": o["key"], "farmed_ha": round(float(x[x.winter_active.eq(True) | x.summer_active.eq(True)].area_ha.sum())),
                     "wheat_ha": round(float(x[x["class"].isin(["winter_only", "wheat_rotation"])].area_ha.sum())),
                     "year_round_ha": round(float(x[x["class"].eq("year_round")].area_ha.sum())),
                     "water_m3": round(float(x.water_m3_central.sum())),
                     "mewa_agri_groundwater_m3": o["agri_groundwater_m3"], "gastat_wheat_ha": o["wheat_ha"], "gastat_fodder_ha": o["fodder_ha"]})
    return rows


def run_scenario(sid, spec, bases, metas, sp):
    t0 = time.time()
    res = {"id": sid, "family": spec["family"], "name": spec["name"], "note": spec.get("note", "")}
    if spec["family"] in ("A", "A2", "B", "B2"):
        d = accounting(table_for(bases, spec, metas, sp))
        if spec.get("fodder"):
            fz = spec["fodder"]
            regions = sp["mewa_fodder_halt_regions"]["values"]
            d, scope, b0 = fodder_halt(d, regions, fz["variant"], fz["compliance"])
            res |= {"scope_fields": int(scope.sum()), "scope_ha": round(float(d.area_ha[scope].sum())),
                    "scope_by_region_ha": d[scope].groupby("admin").area_ha.sum().round().to_dict(),
                    "baseline": {k: round(float(np.nansum(b0[f"{k}_central"]))) for k in FLOW_KEYS},
                    "baseline_summer_mw": round(float(np.nansum(b0.elec_kwh_summer_central)) / (122 * 24) / 1000, 1),
                    "scope_baseline_water_m3": round(float(b0.water_m3_central[scope].sum())),
                    "scope_baseline_water_per_ha_m3": round(float(b0.water_m3_central[scope].sum() / max(b0.area_ha[scope].sum(), 1)))}
            if fz["variant"] == "seasonal" and fz["compliance"] == 1.0:
                watchlist(d, scope, metas).to_csv(ROOT / "out" / "scenario_B1_watchlist.csv", index=False)
                res["watchlist"] = "out/scenario_B1_watchlist.csv"
        if spec.get("retrofit"):
            res |= {"by_rebound": {str(r): retrofit(d, sp, sp["pivot_retrofit"][spec["retrofit"]], r) for r in sp["rebound_share"]["values"]}}
        res |= totals(d)
        f = spec.get("fields", {})
        skip = {"winter", "summer"} if f.get("season_rule", "radar") != "radar" else ({"winter"} if f.get("fill_winter_from_s2") else set())
        res["validation"] = validation(d, skip)
        if spec.get("mc"):
            res["monte_carlo"] = monte_carlo(d, sp)
        if spec.get("bracket"):
            res["by_region"] = bracket_by_region(d)
    else:
        p = NS.params("central")
        avoided = {k: sp["avoided_cement_tco2_per_t_char"][k] for k in LV}
        size = spec.get("size", 50000)
        if spec.get("published"):
            df, s = published_siting(size)
            res |= siting_summary(df, s, avoided=avoided) | {"plant_size_t": size, "credit": "puro",
                                                             "outlets": "soil or nearest cement by haul, both unlimited"}
        else:
            d = accounting(table_for(bases, spec, metas, sp))
            s = supply_from(d, "central", p, spec.get("feeds"))
            cem = cement_table()
            allow0 = (cem.output_t * spec["dosage"]).values
            soil = None
            if spec.get("soil_dose") is not None:
                act = d[d.winter_active.eq(True) | d.summer_active.eq(True)]
                ml = sp["soil_dose_t_per_ha"]["manure_litter_central"] / sp["soil_dose_t_per_ha"]["central"]
                soil = {"lon": act.lon.values, "lat": act.lat.values, "cap": (act.area_ha * spec["soil_dose"]).values,
                        "units": {"litter": 1 / ml, "manure": 1 / ml}, "radius_km": sp["soil_dose_t_per_ha"]["return_radius_km"]}
            df, allow = site2(s, size, p, cement=cem, allowance=allow0, soil=soil, credit=spec["credit"],
                              radius_km=spec.get("radius", NS.RADIUS_KM), max_char_haul_km=sp["max_char_haul_km"]["central"],
                              cement_feeds=tuple(spec.get("cement_feeds", sp["cement_eligible_feeds"]["values"])),
                              min_outlet_share=sp["min_outlet_share"]["central"] if soil is not None else 0.0)
            res |= siting_summary(df, s, cem, allow0, allow, avoided) | {
                "plant_size_t": size, "credit": spec["credit"], "dosage": spec["dosage"], "soil_dose": spec.get("soil_dose"),
                "radius_km": spec.get("radius", NS.RADIUS_KM), "feeds": list(spec["feeds"]) if spec.get("feeds") else "all",
                "cement_feeds": list(spec.get("cement_feeds", sp["cement_eligible_feeds"]["values"]))}
        df.to_csv(ROOT / "out" / f"scenario_{sid}.csv", index=False)
    res["seconds"] = round(time.time() - t0)
    brief = {k: res.get(k) for k in ("plants", "credited_tco2", "char_unplaced_t", "farmed_ha") if k in res}
    if "water_m3" in res:
        brief["water_bn_m3"] = round(res["water_m3"]["central"] / 1e9, 2)
    print(sid, json.dumps(brief), f"{res['seconds']}s", flush=True)
    return res


def run_id():
    """Commit (with -dirty when the tree has changes) plus short hashes of every input that shapes the numbers."""
    import hashlib
    import subprocess

    def h(*paths):
        m = hashlib.sha256()
        for p in paths:
            m.update(p.read_bytes() if p.exists() else b"none")
        return m.hexdigest()[:8]
    try:
        commit = subprocess.run(["git", "-C", str(ROOT), "describe", "--always", "--dirty"], capture_output=True, text=True).stdout.strip()
    except Exception:
        commit = "?"
    nat = ROOT / "data" / "national"
    region_files = sorted((ROOT / "data" / "regions").glob("R*/fields_radar.csv")) + sorted((ROOT / "data" / "regions").glob("R*/meta.json"))
    parts = {"fields": h(nat / "fields_national.csv"), "regions": h(*region_files),
             "boundaries": h(nat / "regions.json", nat / "sau_adm1.geojson", nat / "ne_50m_countries.geojson", nat / "official_2024.json"),
             "manure": h(nat / "manure_points.csv"), "cement": h(ROOT / "data" / "cement" / "saudi_cement.csv", ROOT / "model" / "scenario_cement_plants.csv"),
             "params": h(ROOT / "model" / "params.json"), "scenario_params": h(ROOT / "model" / "scenario_params.json"),
             "engine": h(ROOT / "model" / "national_scenarios.py"), "supply": h(ROOT / "model" / "national_supply.py"),
             "siting": h(ROOT / "model" / "national_siting.py")}
    return f"{commit} " + " ".join(f"{k}:{v}" for k, v in parts.items())


def main(ids=None):
    sp = SP()
    bases = {qc: base_table(qc) for qc in (False, True)}
    published, pub_qc, errors = load_fields(), None, {}
    for qc in (True, False):  # which quality-check setting was the published table built with?
        try:
            check_baseline(bases[qc], published)
            pub_qc = qc
            break
        except SystemExit as e:
            errors[qc] = str(e)
    if pub_qc is None:
        raise SystemExit(f"published table matches neither setting: QC on: {errors[True]}; QC off: {errors[False]}")
    metas = load_metas()
    S = scenarios(sp)
    outp = ROOT / "out" / "national_scenarios.json"
    out = json.loads(outp.read_text()) if (outp.exists() and ids) else {}
    out.setdefault("scenarios", {})
    rid = run_id()
    out["run_id"] = rid
    out["published_table_quality_check"] = pub_qc
    if out["published_table_quality_check"]:  # A0 mirrors the published table, whichever setting it was built with
        S["A0_published"]["name"] = "Published table (radar quality check on, southwest in)"
        S["A0_published"]["fields"] = {"qc": True}
    for sid in (ids or list(S)):
        out["scenarios"][sid] = run_scenario(sid, S[sid], bases, metas, sp) | {"run_id": rid}
        outp.write_text(json.dumps(out, indent=1, default=str))
    out["scenario_params"] = json.loads((ROOT / "model" / "scenario_params.json").read_text())
    out["baseline_check"] = "classification and accounting reproduce data/national/fields_national.csv"
    outp.write_text(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main(sys.argv[1:] or None)
