"""Biochar plant siting and sizing (greedy facility location) with two feeds: wheat straw and palm fronds.

Inputs
  data/supply.csv          one row per field (model/supply.py): id, lon, lat, residue_t_dry_<level> (wheat straw) and
                           fronds_t_dry_<level> (palm fronds), dry t per year
  data/cement/saudi_cement.csv   cement plants (from gee/01_export_saudi_cement.js)
  model/params.json        every factor with low/central/high and a source

Feeds, each with its own char factors (as model/national_siting.supply)
  straw   residue_t_dry x collectable_fraction; char_yield_dry, char_c_org, h_c_org_straw; hauled as received at
          straw_dry_matter
  fronds  fronds_t_dry (already the collectable dry residue, as in the national run); palm_char_yield_dry,
          palm_char_c_org, h_c_org_fronds; hauled as received at palm_frond_dry_matter
  A feed whose char has H/C_org of 0.70 or more earns nothing (Puro rule 3.5.1) and is left out.

Method (kept simple and explainable on purpose)
  1. Candidate sites = cement plants in or near the box + a regular grid over the supplying fields.
  2. For a plant of capacity C at site j, fill it from the nearest supply points (one per field and feed) until C
     is met: all of the nearer points, and from the last only what tops the plant up to C.
  3. Every term is weighted per feed, as model/national_siting.run does: haul = dry t / dry matter x km, char =
     dry t x char yield, credited removal = dry t x char yield x organic C x persistence x 44/12.
  4. Score j by transport emissions per tonne of CO2 removed (feed in + char out).
  5. Place the best plant, remove the feed it uses, repeat until supply runs out or no site can be filled to the
     minimum load. The last, partly used point keeps its remainder for later plants (as model/national_siting.run).
  Char outlets compared per plant: back to the same fields (soil) or the nearest operating cement plant.
  Both are credited with the Puro.earth 2025 v2 soil persistence model (rule 6.2.4), so the outlet is
  chosen by haul; in-service retention in cement is reported, not credited. Truck emissions are the only ones
  subtracted: production and embodied emissions and leakage are not (a technical potential, not a credit volume).

Outputs
  out/plants_<scenario>.csv and out/plants_<scenario>.geojson: one row per plant. The feed mix: feed_straw and
  feed_fronds (dry t of each feed; together feed_t_dry), soil_removal_straw_tco2 and soil_removal_fronds_tco2 (credited
  removal from each feed before transport; together soil_removal_tco2)
  out/assignments_<scenario>.csv: field_id, plant, feed, feed_t_dry (collectable dry t the plant takes from the field;
  a field split between two plants has a row for each)
Usage  .venv/bin/python model/siting.py [low|central|high]
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from national_siting import persistence  # noqa: E402  (Puro persistence from H/C_org and soil temperature)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out"
OUT.mkdir(exist_ok=True)
CO2_PER_C = 44.0 / 12.0
FEEDS = ("straw", "fronds")


def load_params(level="central"):
    raw = json.loads((ROOT / "model" / "params.json").read_text())
    levelled = {k: v for k, v in raw.items() if not k.startswith("_") and isinstance(v, dict) and level in v}
    missing = [k for k, v in levelled.items() if v.get(level) is None]
    if missing:
        raise SystemExit(f"Fill these in model/params.json first ({level}): {missing}")
    return {k: v[level] for k, v in levelled.items()}


def feed_factors(p):
    """Char factors per feed (as model/national_siting.supply): char t per dry t, credited organic C t per dry t,
    persistence (0 if the feed fails the H/C_org gate) and as-received t hauled per dry t."""
    return {"straw": {"char_t_per_t": p["char_yield_dry"], "c_per_t": p["char_yield_dry"] * p["char_c_org"],
                      "perm": persistence(p, "straw"), "wet_per_dry": 1 / p["straw_dry_matter"]},
            "fronds": {"char_t_per_t": p["palm_char_yield_dry"], "c_per_t": p["palm_char_yield_dry"] * p["palm_char_c_org"],
                       "perm": persistence(p, "fronds"), "wet_per_dry": 1 / p["palm_frond_dry_matter"]}}


def supply_points(supply, p, level):
    """One supply point per field and feed with collectable dry t > 0 (dry_t), with its feed's char factors."""
    parts = []
    for feed, col, share in (("straw", f"residue_t_dry_{level}", p["collectable_fraction"]),
                             ("fronds", f"fronds_t_dry_{level}", 1.0)):
        if col not in supply:
            continue
        d = supply.loc[supply[col] > 0, ["id", "lon", "lat"]].copy()
        d["feed"] = feed
        d["dry_t"] = supply.loc[d.index, col] * share
        parts.append(d)
    s = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=["id", "lon", "lat", "feed", "dry_t"])
    fac = feed_factors(p)
    for k in ("char_t_per_t", "c_per_t", "perm", "wet_per_dry"):
        s[k] = s.feed.map({f: fac[f][k] for f in fac})
    return s[s.perm > 0].reset_index(drop=True)  # a feed failing the H/C_org gate earns nothing: left out


def haversine_km(lon1, lat1, lon2, lat2):
    lon1, lat1, lon2, lat2 = map(np.radians, (lon1, lat1, lon2, lat2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * np.arcsin(np.sqrt(a))


def candidate_sites(supply, cement, grid_step_deg=0.1, margin_deg=0.5):
    lo0, la0 = supply.lon.min() - margin_deg, supply.lat.min() - margin_deg
    lo1, la1 = supply.lon.max() + margin_deg, supply.lat.max() + margin_deg
    sites = []
    if cement is not None and len(cement):
        near = cement[(cement.lon.between(lo0, lo1)) & (cement.lat.between(la0, la1))]
        for _, r in near.iterrows():
            sites.append({"site": f"cement:{r.get('uid', '')}", "kind": "cement", "lon": r.lon, "lat": r.lat})
    for lo in np.arange(supply.lon.min(), supply.lon.max() + 1e-9, grid_step_deg):
        for la in np.arange(supply.lat.min(), supply.lat.max() + 1e-9, grid_step_deg):
            sites.append({"site": f"grid:{lo:.2f},{la:.2f}", "kind": "grid", "lon": lo, "lat": la})
    return pd.DataFrame(sites)


def evaluate_site(site, pool, cement, p, capacity):
    """Fill a plant at this site from the nearest supply points. Returns (result, pool index of the points drawn on,
    collectable dry t taken from each), or None below the minimum load."""
    d = haversine_km(site.lon, site.lat, pool.lon.values, pool.lat.values) * p["road_circuity"]
    order = np.argsort(d)
    avail = pool.dry_t.values[order]  # collectable dry t, nearest point first
    cum = np.cumsum(avail)
    k = min(int(np.searchsorted(cum, capacity) + 1), len(order))
    take = order[:k]
    feed = float(min(cum[k - 1], capacity))
    if feed < p["min_load_fraction"] * capacity:
        return None
    w = avail[:k].copy()
    if cum[k - 1] > capacity:  # the last point gives only what tops the plant up; it keeps the rest for later plants
        w[-1] = capacity - (cum[k - 2] if k > 1 else 0.0)
    sub = pool.iloc[take]
    dk, kind = d[take], sub.feed.values
    feed_tkm = float((w * sub.wet_per_dry.values * dk).sum())  # haul as-received (wet) tonnes, per feed
    char_t = float((w * sub.char_t_per_t.values).sum())
    c_org_t = float((w * sub.c_per_t.values).sum())
    cred = w * sub.c_per_t.values * sub.perm.values * CO2_PER_C  # credited removal of each point, per feed

    # Outlet A: soil, char spread back on the supplying fields (mean haul = feed-weighted distance)
    soil_km = float((w * dk).sum() / w.sum())
    soil_removal = float(cred.sum())
    # Outlet B: nearest cement plant
    if cement is not None and len(cement):
        dc = haversine_km(site.lon, site.lat, cement.lon.values, cement.lat.values) * p["road_circuity"]
        cem_km = float(dc.min())
    else:
        cem_km = float("nan")
    cem_removal = soil_removal  # Puro rule 6.2.4: char in cement is credited with the soil persistence model
    retained = c_org_t * CO2_PER_C * p["cement_retention"]  # held in the cement matrix: reported, not credited

    ef = p["truck_kgco2e_per_tkm"] / 1000.0
    feed_t_co2 = feed_tkm * ef
    res = {
        "site": site.site, "kind": site.kind, "lon": site.lon, "lat": site.lat,
        "fields": int(sub.id.nunique()), "feed_t_dry": feed, "load_factor": feed / capacity,
        "mean_feed_haul_km": soil_km, "feed_transport_tco2": feed_t_co2,
        "char_t": char_t,
        "soil_removal_tco2": soil_removal,
        "soil_transport_tco2": feed_t_co2 + char_t * soil_km * ef,
        "cement_km": cem_km, "cement_removal_tco2": cem_removal, "cement_retained_tco2": retained,
        "cement_transport_tco2": feed_t_co2 + char_t * cem_km * ef,
    }
    res["soil_penalty"] = res["soil_transport_tco2"] / soil_removal
    res["cement_penalty"] = res["cement_transport_tco2"] / cem_removal if cem_removal else float("nan")
    # Choose the outlet that removes the most CO2 after its own transport emissions.
    res["soil_net_tco2"] = soil_removal - res["soil_transport_tco2"]
    res["cement_net_tco2"] = (cem_removal - res["cement_transport_tco2"]) if not math.isnan(cem_km) else float("nan")
    cem_better = not math.isnan(res["cement_net_tco2"]) and res["cement_net_tco2"] > res["soil_net_tco2"]
    res["best_outlet"] = "cement" if cem_better else "soil"
    res["net_removal_tco2"] = res["cement_net_tco2"] if cem_better else res["soil_net_tco2"]
    res["penalty"] = res["cement_penalty"] if cem_better else res["soil_penalty"]
    # the feed mix: dry t of each feed and the credited removal it brings (before transport)
    for f in FEEDS:
        res[f"feed_{f}"] = round(float(w[kind == f].sum()), 1)
    for f in FEEDS:
        res[f"soil_removal_{f}_tco2"] = round(float(cred[kind == f].sum()), 1)
    return res, pool.index.values[take], w


def place_plants(points, cement, p, capacity, max_plants=50):
    pool = points.copy()
    sites = candidate_sites(points, cement)
    plants, assign = [], []
    while len(pool) and len(plants) < max_plants:
        best = None
        for _, s in sites.iterrows():
            r = evaluate_site(s, pool, cement, p, capacity)
            if r and (best is None or r[0]["penalty"] < best[0]["penalty"]):
                best = r
        if best is None:
            break
        res, ids, used = best
        res["plant"] = len(plants) + 1
        plants.append(res)
        assign += [{"field_id": points.loc[i, "id"], "plant": res["plant"], "feed": points.loc[i, "feed"],
                    "feed_t_dry": round(float(u), 1)} for i, u in zip(ids, used)]
        # remove the feed the plant uses; the last, partly used point keeps its remainder for later plants
        rem = pool.loc[ids, "dry_t"].values - used
        left = rem > 1e-6
        pool.loc[ids[left], "dry_t"] = rem[left]
        pool = pool.drop(index=ids[~left])
    return pd.DataFrame(plants), pd.DataFrame(assign)


def to_geojson(df, path):
    feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [r.lon, r.lat]},
              "properties": {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in r.items() if k not in ("lon", "lat")}}
             for _, r in df.iterrows()]
    path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}))


def main(level="central"):
    p = load_params(level)
    supply = pd.read_csv(ROOT / "data" / "supply.csv")
    points = supply_points(supply, p, level)
    by = points.groupby("feed").dry_t.sum()
    print(f"{level}: {points.id.nunique()} supplying fields, collectable t dry/y: "
          + ", ".join(f"{f} {by.get(f, 0.0):,.0f}" for f in FEEDS)
          + " | persistence " + ", ".join(f"{f} {persistence(p, f):.3f}" for f in FEEDS))
    cpath = ROOT / "data" / "cement" / "saudi_cement.csv"
    cement = pd.read_csv(cpath) if cpath.exists() else None
    if cement is not None and "status" in cement:
        cement = cement[cement.status != "Closed"].reset_index(drop=True)  # closed plants take no char
    for cap in p["plant_sizes_t_dry"]:
        plants, assign = place_plants(points, cement, p, cap) if len(points) else (pd.DataFrame(), pd.DataFrame())
        tag = f"{level}_{int(cap/1000)}kt"
        plants.to_csv(OUT / f"plants_{tag}.csv", index=False)
        assign.to_csv(OUT / f"assignments_{tag}.csv", index=False)
        to_geojson(plants, OUT / f"plants_{tag}.geojson")
        if len(plants):
            print(f"{tag}: {len(plants)} plants, feed used {plants.feed_t_dry.sum():,.0f} t dry (straw "
                  f"{plants.feed_straw.sum():,.0f}, fronds {plants.feed_fronds.sum():,.0f}), net removal "
                  f"{plants.net_removal_tco2.sum():,.0f} t CO2/y, median transport penalty {plants.penalty.median():.1%}")
        else:
            print(f"{tag}: no site reaches the minimum load")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "central")
