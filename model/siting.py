"""Biochar plant siting and sizing (greedy facility location).

Inputs
  data/supply.csv          one row per active field: id, lon, lat, residue_t_dry (per year)
  data/cement/saudi_cement.csv   cement plants (from gee/01_export_saudi_cement.js)
  model/params.json        every factor with low/central/high and a source

Method (kept simple and explainable on purpose)
  1. Candidate sites = cement plants in or near the box + a regular grid over the farms.
  2. For a plant of capacity C at site j, fill it with the nearest fields until C is met.
  3. Score j by transport emissions per tonne of CO2 removed (feed in + char out).
  4. Place the best plant, remove its fields, repeat until residue runs out
     or no site can be filled to the minimum load.
  Char outlets compared per plant: back to the same fields (soil) or the nearest cement plant.

Outputs
  out/plants_<scenario>.csv and out/plants_<scenario>.geojson, out/assignments_<scenario>.csv
"""
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out"
OUT.mkdir(exist_ok=True)
CO2_PER_C = 44.0 / 12.0


def load_params(level="central"):
    raw = json.loads((ROOT / "model" / "params.json").read_text())
    missing = [k for k, v in raw.items() if not k.startswith("_") and v.get(level) is None]
    if missing:
        raise SystemExit(f"Fill these in model/params.json first ({level}): {missing}")
    return {k: v[level] for k, v in raw.items() if not k.startswith("_")}


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
    d = haversine_km(site.lon, site.lat, pool.lon.values, pool.lat.values) * p["road_circuity"]
    order = np.argsort(d)
    cum = np.cumsum(pool.residue_t_dry.values[order]) * p["collectable_fraction"]
    k = int(np.searchsorted(cum, capacity) + 1)
    k = min(k, len(order))
    take = order[:k]
    feed = float(min(cum[k - 1], capacity))
    if feed < p["min_load_fraction"] * capacity:
        return None
    w = pool.residue_t_dry.values[take] * p["collectable_fraction"]
    w = w * (feed / w.sum())
    feed_tkm = float((w / p["straw_dry_matter"] * d[take]).sum())  # haul as-received (wet) tonnes
    char_t = feed * p["char_yield_dry"]
    c_org_t = char_t * p["char_c_org"]

    # Outlet A: soil, char spread back on the supplying fields (mean haul = feed-weighted distance)
    soil_km = float((w * d[take]).sum() / w.sum())
    soil_removal = c_org_t * CO2_PER_C * p["soil_persistence_100y"]
    # Outlet B: nearest cement plant
    if cement is not None and len(cement):
        dc = haversine_km(site.lon, site.lat, cement.lon.values, cement.lat.values) * p["road_circuity"]
        cem_km = float(dc.min())
    else:
        cem_km = float("nan")
    cem_removal = c_org_t * CO2_PER_C * p["cement_retention"]

    ef = p["truck_kgco2e_per_tkm"] / 1000.0
    feed_t_co2 = feed_tkm * ef
    res = {
        "site": site.site, "kind": site.kind, "lon": site.lon, "lat": site.lat,
        "fields": len(take), "feed_t_dry": feed, "load_factor": feed / capacity,
        "mean_feed_haul_km": soil_km, "feed_transport_tco2": feed_t_co2,
        "char_t": char_t,
        "soil_removal_tco2": soil_removal,
        "soil_transport_tco2": feed_t_co2 + char_t * soil_km * ef,
        "cement_km": cem_km, "cement_removal_tco2": cem_removal,
        "cement_transport_tco2": feed_t_co2 + char_t * cem_km * ef,
    }
    res["soil_penalty"] = res["soil_transport_tco2"] / soil_removal
    res["cement_penalty"] = res["cement_transport_tco2"] / cem_removal if cem_removal else float("nan")
    res["best_outlet"] = "soil" if res["soil_penalty"] <= np.nan_to_num(res["cement_penalty"], nan=9e9) else "cement"
    res["penalty"] = min(res["soil_penalty"], np.nan_to_num(res["cement_penalty"], nan=9e9))
    return res, pool.index.values[take]


def place_plants(supply, cement, p, capacity, max_plants=50):
    pool = supply.copy()
    sites = candidate_sites(supply, cement)
    plants, assign = [], []
    while len(pool) and len(plants) < max_plants:
        best = None
        for _, s in sites.iterrows():
            r = evaluate_site(s, pool, cement, p, capacity)
            if r and (best is None or r[0]["penalty"] < best[0]["penalty"]):
                best = r
        if best is None:
            break
        res, ids = best
        res["plant"] = len(plants) + 1
        plants.append(res)
        assign += [{"field_id": supply.loc[i, "id"], "plant": res["plant"]} for i in ids]
        pool = pool.drop(index=ids)
    return pd.DataFrame(plants), pd.DataFrame(assign)


def to_geojson(df, path):
    feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [r.lon, r.lat]},
              "properties": {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in r.items() if k not in ("lon", "lat")}}
             for _, r in df.iterrows()]
    path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}))


def main(level="central"):
    p = load_params(level)
    supply = pd.read_csv(ROOT / "data" / "supply.csv")
    supply["residue_t_dry"] = supply[f"residue_t_dry_{level}"]
    supply = supply[supply.residue_t_dry > 0].reset_index(drop=True)
    print(f"{level}: {len(supply)} supplying fields, {supply.residue_t_dry.sum():,.0f} t dry/y collectable")
    cpath = ROOT / "data" / "cement" / "saudi_cement.csv"
    cement = pd.read_csv(cpath) if cpath.exists() else None
    for cap in p["plant_sizes_t_dry"]:
        plants, assign = place_plants(supply, cement, p, cap)
        tag = f"{level}_{int(cap/1000)}kt"
        plants.to_csv(OUT / f"plants_{tag}.csv", index=False)
        assign.to_csv(OUT / f"assignments_{tag}.csv", index=False)
        to_geojson(plants, OUT / f"plants_{tag}.geojson")
        if len(plants):
            print(f"{tag}: {len(plants)} plants, residue used {plants.feed_t_dry.sum():,.0f} t dry, "
                  f"median transport penalty {plants.penalty.median():.1%}")
        else:
            print(f"{tag}: no site reaches the minimum load")


if __name__ == "__main__":
    import sys
    main(sys.argv[1] if len(sys.argv) > 1 else "central")
