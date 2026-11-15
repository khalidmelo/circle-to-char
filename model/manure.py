"""Collectable manure and poultry litter as ~10 km supply points (modelled, not radar-measured).

Spatial pattern: FAO Gridded Livestock of the World GLW4 2020 (head/km2, CC BY 4.0).
Herds: cattle, sheep and goats scaled to GASTAT Livestock Statistics 2024 head counts; manure as total solids
(ash included) x collectable share. Poultry: GASTAT 2024 broilers produced (1.32 bn birds) x bedded litter per
bird, plus laying hens on hand (estimated from GASTAT egg output) x manure per hen, both spread by the GLW4
chicken pattern. Camels are excluded (no gridded layer, no collectable share).

Output: data/national/manure_points.csv  (lon, lat, litter_t_dry_<lvl>, manure_t_dry_<lvl>)
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
from rasterio.windows import from_bounds
from shapely.geometry import shape

ROOT = Path(__file__).resolve().parents[1]
G = ROOT / "data" / "glw"
KSA = [34.4, 16.3, 55.8, 32.3]
LV = ("low", "central", "high")


def main():
    raw = json.loads((ROOT / "model" / "params.json").read_text())
    p = {k: v for k, v in raw.items() if not k.startswith("_")}
    tot = raw["gastat_2024_totals"]["values"]
    ne = json.loads((ROOT / "data" / "national" / "ne_50m_countries.geojson").read_text())
    sau = next(shape(f["geometry"]) for f in ne["features"] if f["properties"].get("ADM0_A3") == "SAU")

    heads = {}
    for sp in ("CHK", "CTL", "SHP", "GTS"):
        with rasterio.open(G / f"GLW4-2020.D-DA.{sp}.tif") as src:
            win = from_bounds(*KSA, transform=src.transform).round_offsets().round_lengths()
            dens = src.read(1, window=win).astype("float64")
            tf = src.window_transform(win)
            nod = src.nodata
        dens = np.where((dens > 0) & (dens != nod), dens, 0)
        mask = rasterize([(sau, 1)], out_shape=dens.shape, transform=tf, dtype="uint8").astype(bool)
        rows, cols = np.indices(dens.shape)
        lat = tf.f + (rows + 0.5) * tf.e
        cell_km2 = (abs(tf.a) * 111.32 * np.cos(np.radians(lat))) * (abs(tf.e) * 110.57)
        heads[sp] = np.where(mask, dens * cell_km2, 0)
    target = {"CTL": tot["cattle"], "SHP": tot["sheep"], "GTS": tot["goats"]}
    scale = {sp: target[sp] / heads[sp].sum() for sp in target}
    print("GLW4 2020 totals inside Saudi Arabia vs GASTAT 2024:",
          {sp: f"{heads[sp].sum():,.0f} -> {target[sp]:,.0f} (x{scale[sp]:.2f})" for sp in target})

    rows, cols = np.indices(heads["CHK"].shape)
    lon = tf.c + (cols + 0.5) * tf.a
    lat = tf.f + (rows + 0.5) * tf.e
    out = pd.DataFrame({"lon": lon.ravel(), "lat": lat.ravel()})
    for sp in target:
        out[f"heads_{sp}"] = (heads[sp] * scale[sp]).ravel()
    out["chk_share"] = (heads["CHK"] / heads["CHK"].sum()).ravel()  # share of the national chicken flock (GLW4 pattern)
    for l in LV:
        poultry_kg = (tot["broilers_produced"] * p["broiler_litter_kg_dry_per_bird"][l]
                      + p["layers_on_hand"][l] * p["layer_manure_kg_dry_per_hen"][l])
        litter = out.chk_share * poultry_kg * p["collectable_share_poultry"][l] / 1000
        manure = (out.heads_CTL * p["cattle_manure_kg_dry_per_head"][l] * p["collectable_share_cattle"][l]
                  + (out.heads_SHP + out.heads_GTS) * p["small_ruminant_manure_kg_dry_per_head"][l]
                  * p["collectable_share_small_ruminants"][l]) / 1000
        out[f"litter_t_dry_{l}"] = litter.round(1)
        out[f"manure_t_dry_{l}"] = manure.round(1)
    total = {k: out[f"{k}_t_dry_central"].sum() for k in ("litter", "manure")}
    out = out[(out.litter_t_dry_central + out.manure_t_dry_central) > 20].reset_index(drop=True)  # skip near-empty cells
    print("kept after the 20 t cell cut:", {k: f"{out[f'{k}_t_dry_central'].sum() / total[k]:.1%}" for k in total})
    out.to_csv(ROOT / "data" / "national" / "manure_points.csv", index=False)
    print(len(out), "cells;", {f"{k}_{l}": f"{out[f'{k}_t_dry_{l}'].sum() / 1e6:.2f} Mt" for k in ("litter", "manure") for l in LV})


if __name__ == "__main__":
    main()
