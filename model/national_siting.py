"""National biochar siting with mixed feedstocks (greedy facility location).

Supply points
  straw   radar wheat fields: winter-only and wheat rotations (data/national/fields_national.csv)
  fronds  radar palm-grove fields (same file)
  litter  poultry litter, ~10 km cells (data/national/manure_points.csv, modelled)
  manure  cattle/sheep/goat manure, ~10 km cells (same file, modelled)
Each feedstock has its own char yield, organic C and H/C_org (model/params.json).

Crediting (Puro.earth Biochar Methodology 2025 v2)
  Persistence PF = (M - a x H/C_org) / 100 with M, a for the soil temperature (Table 6.1; one national value,
  30 C central with a 25-33 C band, not yet set per region of first use); a stream with H/C_org >= 0.70 earns
  nothing (rule 3.5.1) and is left out of the supply. Char in cement is credited with the same soil model
  (rule 6.2.4), so both outlets earn the same credit and the outlet is chosen by haul. Production and
  embodied emissions and leakage are not subtracted (a technical potential, not a credit volume).
  In-service retention in cement (cement_retention) is reported, not credited. Soil absorption is not
  limited here (gross technical framing); constrained cases are in model/national_scenarios.py.

Method
  Candidate sites: the operating cement plants + a 0.25 degree grid over cells with supply.
  A plant of capacity C draws the nearest supply within RADIUS_KM until C is met
  (needs >= 80% of C). Its net removal = credited char C x 44/12 x PF, minus truck emissions for feed
  in and char out (to the fields it came from, or to the nearest cement plant if that haul is shorter).
  Place the plant with the largest net removal, remove its supply, repeat.

Output: out/national_plants_<lvl>[_radar]_<size>kt.csv and summary in out/national_siting.json
Usage:  .venv/bin/python model/national_siting.py [central] [low] [high]   (one call per set: each run replaces the last)
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CO2_PER_C = 44 / 12
RADIUS_KM = 100.0  # assumption: farthest a plant draws feedstock from (sensitivity-tested)
MAX_PLANTS = 400   # safety stop; reported if reached


def params(level):
    raw = json.loads((ROOT / "model" / "params.json").read_text())
    return {k: v[level] for k, v in raw.items() if not k.startswith("_") and isinstance(v, dict) and level in v}


def hav(lon1, lat1, lon2, lat2):
    lon1, lat1, lon2, lat2 = map(np.radians, (lon1, lat1, lon2, lat2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * np.arcsin(np.sqrt(a))


def supply(level, p, feeds=None):
    f = pd.read_csv(ROOT / "data" / "national" / "fields_national.csv", low_memory=False)
    parts = []
    for feed, col in (("straw", f"straw_t_dry_{level}"), ("fronds", f"fronds_t_dry_{level}")):
        d = f[f[col] > 0][["lon", "lat", "region"]].copy()
        d["dry_t"] = f.loc[d.index, col]
        d["feed"] = feed
        parts.append(d)
    mp = ROOT / "data" / "national" / "manure_points.csv"
    if mp.exists():
        m = pd.read_csv(mp)
        for feed in ("litter", "manure"):
            d = m[m[f"{feed}_t_dry_{level}"] > 0][["lon", "lat"]].copy()
            d["dry_t"] = m.loc[d.index, f"{feed}_t_dry_{level}"]
            d["feed"] = feed
            d["region"] = "grid"
            parts.append(d)
    s = pd.concat(parts, ignore_index=True)
    if feeds:
        s = s[s.feed.isin(feeds)].reset_index(drop=True)
    yld = {"straw": p["char_yield_dry"], "fronds": p["palm_char_yield_dry"], "litter": p["litter_char_yield_dry"], "manure": p["manure_char_yield_dry"]}
    cor = {"straw": p["char_c_org"], "fronds": p["palm_char_c_org"], "litter": p["litter_char_c_org"], "manure": p["manure_char_c_org"]}
    per = {f: persistence(p, f) for f in ("straw", "fronds", "litter", "manure")}
    dm = {"straw": p["straw_dry_matter"], "fronds": p["palm_frond_dry_matter"], "litter": p["litter_dry_matter"],
          "manure": p["manure_dry_matter"]}  # wet tonnes hauled per dry tonne = 1 / DM
    s["char_t_per_t"] = s.feed.map(yld)
    s["c_per_t"] = s.feed.map(yld) * s.feed.map(cor)
    s["soil_perm"] = s.feed.map(per)
    s["wet_per_dry"] = 1 / s.feed.map(dm)
    return s[s.soil_perm > 0].reset_index(drop=True)  # streams failing the H/C_org gate earn nothing: left out


def persistence(p, feed):
    """Puro 2025 v2 persistence fraction for a feed at the level's soil temperature; 0 if H/C_org >= 0.70."""
    raw = json.loads((ROOT / "model" / "params.json").read_text())
    m, a = raw["puro_pf_table"]["values"][str(int(p["soil_temp_c"]))]
    hc = p[f"h_c_org_{feed}"]
    return 0.0 if hc >= 0.70 else (m - a * hc) / 100


def run(level, size_t, cement, p, feeds=None):
    s = supply(level, p, feeds)
    pool = s.copy()
    ef = p["truck_kgco2e_per_tkm"] / 1000
    circ = p["road_circuity"]
    grid = pool.assign(gx=(pool.lon / 0.25).round() * 0.25, gy=(pool.lat / 0.25).round() * 0.25)[["gx", "gy"]].drop_duplicates()
    sites = pd.concat([pd.DataFrame({"lon": cement.lon, "lat": cement.lat, "kind": "cement", "name": cement.city.fillna("") + " cement"}),
                       pd.DataFrame({"lon": grid.gx, "lat": grid.gy, "kind": "grid", "name": ""})], ignore_index=True)
    plants = []
    fed = {f: 0.0 for f in ("straw", "fronds", "litter", "manure")}  # unrounded feed used, by stream
    credited = {f: 0.0 for f in fed}  # credited removal by stream before haulage (t CO2)
    while len(pool) and len(plants) < MAX_PLANTS:
        best = None
        lon_p, lat_p, dry = pool.lon.values, pool.lat.values, pool.dry_t.values
        for _, st in sites.iterrows():
            d = hav(st.lon, st.lat, lon_p, lat_p) * circ
            near = np.where(d <= RADIUS_KM)[0]
            if not len(near) or dry[near].sum() < 0.8 * size_t:
                continue
            o = near[np.argsort(d[near])]
            cum = np.cumsum(dry[o])
            k = int(np.searchsorted(cum, size_t) + 1)
            take = o[:min(k, len(o))]
            w = dry[take].copy()
            if w.sum() > size_t:
                w[-1] -= w.sum() - size_t
            sub = pool.iloc[take]
            feed_tkm = float((w * sub.wet_per_dry.values * d[take]).sum())
            c_t = float((w * sub.c_per_t.values).sum())
            char_t = float((w * sub.char_t_per_t.values).sum())
            mean_km = float((w * d[take]).sum() / w.sum())
            soil_rem = float((w * sub.c_per_t.values * sub.soil_perm.values).sum()) * CO2_PER_C
            dc = hav(st.lon, st.lat, cement.lon.values, cement.lat.values) * circ
            j = int(np.argmin(dc))
            if soil_rem <= 0:  # every stream in reach is ineligible (H/C_org >= 0.70): nothing to credit here
                continue
            cem_rem = soil_rem  # Puro rule 6.2.4: char in cement is credited with the soil persistence model
            retained = c_t * CO2_PER_C * p["cement_retention"]  # carbon held in the cement matrix: reported, not credited
            soil_net = soil_rem - (feed_tkm + char_t * mean_km) * ef
            cem_net = cem_rem - (feed_tkm + char_t * float(dc[j])) * ef
            net = max(soil_net, cem_net)
            if best is None or net > best["net_removal_tco2"]:
                mix = {f: float(w[sub.feed.values == f].sum()) for f in ("straw", "fronds", "litter", "manure")}
                cred = {f: float((w * sub.c_per_t.values * sub.soil_perm.values)[sub.feed.values == f].sum()) * CO2_PER_C
                        for f in ("straw", "fronds", "litter", "manure")}  # credited removal by stream, before haulage
                best = {"lon": float(st.lon), "lat": float(st.lat), "kind": st.kind, "name": st["name"],
                        "feed_t_dry": float(w.sum()), "load": float(w.sum() / size_t), "mean_haul_km": round(mean_km, 1),
                        "char_t": round(char_t), "soil_net_tco2": round(soil_net), "cement_net_tco2": round(cem_net),
                        "cement_km": round(float(dc[j]), 1), "cement_name": f"{cement.city.iloc[j]}",
                        "best_outlet": "cement" if cem_net > soil_net else "soil", "net_removal_tco2": round(net),
                        "cement_retained_tco2": round(retained) if cem_net > soil_net else 0,
                        "transport_share": round(1 - net / (cem_rem if cem_net > soil_net else soil_rem), 4),
                        **{f"feed_{k}": round(v) for k, v in mix.items()}, "_take": pool.index.values[take], "_used": w,
                        "_mix": mix, "_cred": cred}
        if best is None:
            break
        # remove what the plant uses; the last, partly used point keeps its remainder for later plants
        idx, used = best.pop("_take"), best.pop("_used")
        for f, v in best.pop("_mix").items():
            fed[f] += v
        for f, v in best.pop("_cred").items():
            credited[f] += v
        rem = pool.loc[idx, "dry_t"].values - used
        left = rem > 1e-6
        pool.loc[idx[left], "dry_t"] = rem[left]
        pool = pool.drop(index=idx[~left])
        best["plant"] = len(plants) + 1
        plants.append(best)
    capped = len(plants) >= MAX_PLANTS
    if capped:
        print(f"  stopped at the {MAX_PLANTS}-plant cap with {pool.dry_t.sum():,.0f} t of supply left", flush=True)
    out = pd.DataFrame(plants)
    # run facts travel on the frame so run() keeps its (plants, supply) return shape
    out.attrs |= {"capped": capped, "supply_left_t": float(pool.dry_t.sum()), "feed_used_by_feed_t": fed,
                  "credited_by_feed_tco2": credited}
    return out, s


def main(levels=("central",), sizes=(10000, 25000, 50000)):
    cement = pd.read_csv(ROOT / "data" / "cement" / "saudi_cement.csv")
    cement = cement[cement.status != "Closed"].reset_index(drop=True)  # closed plants take no char
    summ = {}
    # all residues, and radar-measured residues alone (straw + fronds; no modelled manure or litter)
    runs = [(lvl, size, None, f"{lvl}_{size // 1000}kt") for lvl in levels for size in sizes]
    runs += [(lvl, size, ("straw", "fronds"), f"{lvl}_radar_{size // 1000}kt") for lvl in levels for size in sizes]
    for lvl, size, feeds, tag in runs:
        p = params(lvl)
        df, s = run(lvl, size, cement, p, feeds)
        df.to_csv(ROOT / "out" / f"national_plants_{tag}.csv", index=False)
        summ[tag] = {"plants": int(len(df)), "feed_used_t": round(float(df.feed_t_dry.sum())) if len(df) else 0,
                     "supply_t": round(float(s.dry_t.sum())), "supply_by_feed_t": s.groupby("feed").dry_t.sum().round().to_dict(),
                     "net_removal_tco2": round(float(df.net_removal_tco2.sum())) if len(df) else 0,
                     "cement_outlet_plants": int((df.best_outlet == "cement").sum()) if len(df) else 0,
                     "cement_retained_tco2": round(float(df.cement_retained_tco2.sum())) if len(df) else 0,
                     "credited_basis": "Puro.earth 2025 v2: soil persistence model for soil and cement (rule 6.2.4), "
                                       "H/C_org < 0.70 gate; soil absorption not limited",
                     "persistence": {f: round(persistence(p, f), 4) for f in ("straw", "fronds", "litter", "manure")},
                     "median_transport_share": round(float(df.transport_share.median()), 4) if len(df) else None,
                     "feed_used_by_feed_t": {f: round(v) for f, v in df.attrs.get("feed_used_by_feed_t", {}).items()},
                     "credited_by_feed_tco2": {f: round(v) for f, v in df.attrs.get("credited_by_feed_tco2", {}).items()},
                     "capped": bool(df.attrs.get("capped", False)), "supply_left_t": round(df.attrs.get("supply_left_t", 0.0)),
                     "feeds": list(feeds) if feeds else "all", "radius_km": RADIUS_KM}
        print(tag, json.dumps(summ[tag]))
    # this run replaces the previous one: scenarios it did not produce (e.g. an older low/high run) are removed
    for p in (ROOT / "out").glob("national_plants_*.csv"):
        if p.stem.replace("national_plants_", "") not in summ:
            p.unlink()
    (ROOT / "out" / "national_siting.json").write_text(json.dumps(summ, indent=1))


if __name__ == "__main__":
    lv = sys.argv[1:] or ["central"]
    main(tuple(lv))
