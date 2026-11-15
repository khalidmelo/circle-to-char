"""Collectable manure and poultry litter as ~10 km supply points (modelled, not radar-measured).

Amounts: GASTAT Livestock Statistics 2024 head counts (national totals in model/params.json) x total solids per head
(ash included), or bedded litter per broiler produced and manure per laying hen, x the collectable share. Camels are
excluded (no gridded layer, no collectable share).

Placement: only the collectable part is placed, where the animals are housed. The rest (manure dropped while grazing)
is not placed and feeds nothing.
  1. Regional totals: GASTAT 2024 head counts by administrative region (tables below), scaled so that each species
     sums to its national value in params.json. Two tables group regions: specialized-project cattle (Riyadh, Eastern
     Region, 'other regions') and laying hens ('other administrative regions'). A group is split over its regions by
     the FAO GLW4 2020 pattern (cattle, chickens; head/km2, CC BY 4.0).
  2. Within each region, on the GLW4 grid (1/12 degree, about 9 km cells):
     cattle         92% are in barn-housed specialized projects: in proportion to the area of year-round (perennial
                    fodder) fields in data/national/fields_national.csv. The class is class_s2, the radar's class with
                    Sentinel-2 where the radar could not classify a season: the radar observed only one season on most
                    Eastern Region fields, so radar-only it would pile that region's project cattle (the second
                    largest herd) on a few hundred hectares. A region with no year-round field falls back to all its
                    mapped field area; one with no mapped field (Northern Borders) to GLW4 cattle density in cells near
                    fields and settlements (the sheep and goat mask below), then to GLW4 cattle density unmasked.
     sheep, goats   the collectable part is the penned part at holdings: GLW4 density, kept only in cells whose centre
                    is within NEAR_KM of a mapped field or an OpenStreetMap settlement of any kind (city, town, village
                    or hamlet in data/national/osm_places.csv, from scripts/osm_places.py), renormalised in the region
                    (all GLW4 in the region if no cell qualifies).
     poultry        broilers produced and laying hens: GLW4 chicken density, masked the same way but with cities,
                    towns and villages only (no hamlets): poultry houses are commercial farms.
  Laying hens per region = table eggs / 286 + hatching eggs / 232 (the rule behind layers_on_hand central).
  Distances are great-circle: the k-d tree works on 3D points on the sphere (xyz_km), so its chord distance is the
  great-circle distance to under 1 m at NEAR_KM.

Output: data/national/manure_points.csv, one row per cell with more than CUT_T t dry a year of central litter + manure:
  lon, lat
  share_CTL, share_SHP, share_GTS, share_BRL, share_LAY   the cell's share of the national cattle, sheep, goats, broilers
      produced and laying hens, as placed above (factor-free; model/national_siting.py check_manure_points recomputes
      the tonnes from these shares and params.json, so a later change to the head totals or the factors is caught)
  litter_t_dry_<lvl>, manure_t_dry_<lvl>   collectable dry tonnes a year (tonnes(), rounded to 0.1 t)
and its sidecar data/national/manure_points.meta.json (META): placement_inputs() at the time of the run, plus the
sha256 of the CSV written. model/national_siting.py check_manure_points compares it with the current files and stops
when the fields, the settlements, NEAR_KM or CUT_T have changed since (or the CSV is not the one this run wrote).
Run after model/national_supply.py, which writes fields_national.csv.
"""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
from rasterio.windows import from_bounds
from scipy.spatial import cKDTree
from shapely.geometry import shape

ROOT = Path(__file__).resolve().parents[1]
G = ROOT / "data" / "glw"
NAT = ROOT / "data" / "national"
KSA = [34.4, 16.3, 55.8, 32.3]
LV = ("low", "central", "high")
NEAR_KM = 10.0  # assumption: pens and poultry houses lie within this distance of a mapped field or a settlement
CUT_T = 20  # cells holding this many t dry a year or less (central litter + manure) are left out
OTHER = "other"
R_KM = 6371.0  # sphere radius for distances (km), as model/national_siting.py hav()
POULTRY_PLACES = ("city", "town", "village")  # OSM places poultry houses may sit near (sheep and goats: hamlets too)
FIELD_COLS = ["lon", "lat", "area_ha", "admin", "class_s2"]  # the fields_national.csv columns placement reads
META = "manure_points.meta.json"  # sidecar of manure_points.csv in data/national (placement_inputs + the CSV's sha256)

# GASTAT Livestock Statistics 2024 (Excel edition), 2024 columns, keyed by the shapeISO code of the region in
# data/national/sau_adm1.geojson. GASTAT's region names, for reading the tables:
GASTAT_NAME = {"SA-01": "Riyadh", "SA-02": "Makkah", "SA-03": "Madinah", "SA-05": "Qassim", "SA-04": "Eastern Region",
               "SA-14": "Aseer", "SA-07": "Tabuk", "SA-06": "Hail", "SA-08": "Northern Borders", "SA-09": "Jazan",
               "SA-10": "Najran", "SA-11": "Al-Baha", "SA-12": "Al-Jouf"}
# Table 4-1: sheep (column 'Lamb'), goats and cattle in traditional holdings
SHEEP = {"SA-01": 4474774, "SA-02": 3012622, "SA-03": 834683, "SA-05": 3043082, "SA-04": 2432014, "SA-14": 1655218,
         "SA-07": 554542, "SA-06": 1782098, "SA-08": 476049, "SA-09": 916213, "SA-10": 1646215, "SA-11": 459488,
         "SA-12": 768781}
GOATS = {"SA-01": 1095669, "SA-02": 1013835, "SA-03": 560980, "SA-05": 569609, "SA-04": 409788, "SA-14": 848581,
         "SA-07": 285515, "SA-06": 489509, "SA-08": 34521, "SA-09": 816144, "SA-10": 728762, "SA-11": 228098,
         "SA-12": 258738}
CATTLE_TRADITIONAL = {"SA-01": 3339, "SA-02": 6666, "SA-03": 449, "SA-05": 1425, "SA-04": 6502, "SA-14": 4735,
                      "SA-07": 1773, "SA-06": 61, "SA-08": 39, "SA-09": 13909, "SA-10": 776, "SA-11": 1190,
                      "SA-12": 1049}
# Table 1-4: cattle in specialized projects, males + females (Riyadh, Eastern Region, other regions)
CATTLE_PROJECTS = {"SA-01": 36528 + 228013, "SA-04": 28541 + 153055, OTHER: 14718 + 13555}
# Table 2-2: broilers produced in the year (the table has no Northern Borders row)
BROILERS = {"SA-01": 378652883, "SA-02": 94616536, "SA-03": 18572591, "SA-05": 210446736, "SA-04": 123333455,
            "SA-14": 150482290, "SA-07": 7233915, "SA-06": 310618080, "SA-09": 457425, "SA-10": 20016585,
            "SA-11": 1056000, "SA-12": 688552}
# Tables 3-2 (table eggs) and 3-3 (hatching eggs, parent and grandparent flocks)
TABLE_EGGS = {"SA-01": 3214053996, "SA-02": 1541502232, "SA-03": 392009417, "SA-05": 857207969, "SA-04": 1094621849,
              "SA-14": 764441685, "SA-07": 142540738, "SA-06": 335864000, OTHER: 78600000}
HATCHING_EGGS = {"SA-01": 525808704, "SA-02": 194202602, "SA-03": 17640000, "SA-05": 427656600, "SA-04": 150016975,
                 "SA-14": 129442622, "SA-07": 108148587, "SA-06": 311057240, OTHER: 26650000}
TABLE_EGGS_PER_HEN, HATCHING_EGGS_PER_HEN = 286, 232  # params.json layers_on_hand (central)
SPECIES = ("CTL", "SHP", "GTS", "BRL", "LAY")  # cattle, sheep, goats, broilers produced, laying hens


def tonnes(m, p, tot, lv):
    """Collectable (litter, manure) per cell, t dry a year at level lv, from a frame with the share_* columns.
    model/national_siting.py manure_points_gaps repeats these steps term by term."""
    litter = (m.share_BRL * tot["broilers_produced"] * p["broiler_litter_kg_dry_per_bird"][lv]
              + m.share_LAY * p["layers_on_hand"][lv] * p["layer_manure_kg_dry_per_hen"][lv]) \
        * p["collectable_share_poultry"][lv] / 1000
    manure = (m.share_CTL * tot["cattle"] * p["cattle_manure_kg_dry_per_head"][lv] * p["collectable_share_cattle"][lv]
              + (m.share_SHP * tot["sheep"] + m.share_GTS * tot["goats"]) * p["small_ruminant_manure_kg_dry_per_head"][lv]
              * p["collectable_share_small_ruminants"][lv]) / 1000
    return litter.round(1), manure.round(1)


def glw_heads():
    """GLW4 2020 heads per cell (density x cell area) for CHK, CTL, SHP, GTS over the KSA window, and its transform."""
    heads = {}
    for sp in ("CHK", "CTL", "SHP", "GTS"):
        with rasterio.open(G / f"GLW4-2020.D-DA.{sp}.tif") as src:
            win = from_bounds(*KSA, transform=src.transform).round_offsets().round_lengths()
            dens = src.read(1, window=win).astype("float64")
            tf = src.window_transform(win)
            nod = src.nodata
        dens = np.where((dens > 0) & (dens != nod), dens, 0)
        lat = tf.f + (np.indices(dens.shape)[0] + 0.5) * tf.e
        heads[sp] = dens * (abs(tf.a) * 111.32 * np.cos(np.radians(lat))) * (abs(tf.e) * 110.57)
    return heads, tf


def xyz_km(lon, lat):
    """3D coordinates (km) of points on a sphere of radius R_KM. The straight-line (chord) distance between two of them
    is 2 R sin(d / 2R) for their great-circle distance d: in the same order as d, and under 1 m short of it at 10 km,
    so a k-d tree on these finds the nearest point by great-circle distance and takes NEAR_KM as its bound."""
    lon, lat = np.radians(np.asarray(lon, float)), np.radians(np.asarray(lat, float))
    return R_KM * np.c_[np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)]


def within(pts, lon, lat, km=None):
    """True where the point (lon, lat) (arrays of one shape) has one of pts (n x 2 lon, lat) within km (NEAR_KM)."""
    km = NEAR_KM if km is None else km
    if not len(pts):
        return np.zeros(np.shape(lon), bool)
    d, _ = cKDTree(xyz_km(pts[:, 0], pts[:, 1])).query(xyz_km(np.ravel(lon), np.ravel(lat)), distance_upper_bound=km)
    return np.isfinite(d).reshape(np.shape(lon))  # no point within km comes back as inf


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def placement_inputs(nat=NAT):
    """The inputs, beyond this file and the GLW4 rasters, that decide where manure_points.csv places the herds:
    sha256 of fields_national.csv's FIELD_COLS (read as text, in file order, written as a canonical CSV: comma
    separated, minimal quoting, '\\n' line ends), sha256 of osm_places.csv, NEAR_KM and CUT_T. main() writes them to
    META; model/national_siting.py check_manure_points recomputes them from nat (its data/national) and compares."""
    places = nat / "osm_places.csv"
    if not places.exists():
        raise FileNotFoundError(f"{places} not found: run scripts/osm_places.py first")
    cols = pd.read_csv(nat / "fields_national.csv", usecols=FIELD_COLS, dtype=str, keep_default_na=False)[FIELD_COLS]
    return {"fields_national_columns": list(FIELD_COLS),
            "fields_national_sha256": hashlib.sha256(cols.to_csv(index=False, lineterminator="\n").encode()).hexdigest(),
            "osm_places_sha256": sha256_file(places), "NEAR_KM": NEAR_KM, "CUT_T": CUT_T}


def main():
    raw = json.loads((ROOT / "model" / "params.json").read_text())
    p = {k: v for k, v in raw.items() if not k.startswith("_")}
    tot = raw["gastat_2024_totals"]["values"]
    gj = json.loads((NAT / "sau_adm1.geojson").read_text())
    iso = [f["properties"]["shapeISO"] for f in gj["features"]]
    iso_of = {f["properties"]["shapeName"]: f["properties"]["shapeISO"] for f in gj["features"]}
    glw, tf = glw_heads()
    dims = glw["CHK"].shape
    reg = rasterize([(shape(f["geometry"]), k + 1) for k, f in enumerate(gj["features"])], out_shape=dims,
                    transform=tf, dtype="int16")  # region of each cell centre (0 = outside Saudi Arabia)
    inside = {c: reg == k + 1 for k, c in enumerate(iso)}
    rows, cols = np.indices(dims)
    lon, lat = tf.c + (cols + 0.5) * tf.a, tf.f + (rows + 0.5) * tf.e

    # mapped fields, summed to the grid
    f = pd.read_csv(NAT / "fields_national.csv", usecols=FIELD_COLS, low_memory=False)
    f["iso"] = f.admin.map(iso_of)
    fr = np.floor((f.lat.values - tf.f) / tf.e).astype(int)
    fc = np.floor((f.lon.values - tf.c) / tf.a).astype(int)
    if not ((fr >= 0) & (fr < dims[0]) & (fc >= 0) & (fc < dims[1])).all():
        raise RuntimeError("fields_national.csv has fields outside the GLW4 window KSA")

    def field_area(sel):
        a = np.zeros(dims)
        np.add.at(a, (fr[sel], fc[sel]), f.area_ha.values[sel])
        return a

    # cells near a mapped field or a settlement: poultry houses near fields, cities, towns and villages; sheep and
    # goat pens (and the fallback for cattle) near fields and any settlement, hamlets included
    places = NAT / "osm_places.csv"
    if not places.exists():
        raise SystemExit(f"{places.relative_to(ROOT)} not found: run scripts/osm_places.py first")
    pl = pd.read_csv(places)
    town = pl.place.isin(POULTRY_PLACES).values
    poultry_near = within(f[["lon", "lat"]].values, lon, lat) | within(pl.loc[town, ["lon", "lat"]].values, lon, lat)
    near = {"poultry": poultry_near, "pens": poultry_near | within(pl.loc[~town, ["lon", "lat"]].values, lon, lat)}
    mask_of = {"CTL": near["pens"], "SHP": near["pens"], "GTS": near["pens"], "BRL": near["poultry"],
               "LAY": near["poultry"]}
    print(f"Saudi cells within {NEAR_KM:g} km of one of {len(f):,} mapped fields or {town.sum():,} OSM cities, towns "
          f"and villages: {near['poultry'][reg > 0].mean():.1%} (poultry); with {(~town).sum():,} hamlets too: "
          f"{near['pens'][reg > 0].mean():.1%} (sheep, goats)")

    # 1. regional head counts
    def regional(table, sp):
        """GASTAT counts by region; a group row (OTHER) is split over the regions it covers by the GLW4 pattern of sp."""
        out = {c: float(v) for c, v in table.items() if c != OTHER}
        if OTHER in table:
            rest = [c for c in iso if c not in out]
            g = {c: glw[sp][inside[c]].sum() for c in rest}
            out |= {c: table[OTHER] * g[c] / sum(g.values()) for c in rest}
        return {c: out.get(c, 0.0) for c in iso}

    projects, traditional = regional(CATTLE_PROJECTS, "CTL"), regional(CATTLE_TRADITIONAL, "CTL")
    eggs = {k: TABLE_EGGS[k] / TABLE_EGGS_PER_HEN + HATCHING_EGGS[k] / HATCHING_EGGS_PER_HEN for k in TABLE_EGGS}
    heads = {"CTL": {c: projects[c] + traditional[c] for c in iso}, "SHP": regional(SHEEP, "SHP"),
             "GTS": regional(GOATS, "GTS"), "BRL": regional(BROILERS, "CHK"), "LAY": regional(eggs, "CHK")}
    target = {"CTL": tot["cattle"], "SHP": tot["sheep"], "GTS": tot["goats"], "BRL": tot["broilers_produced"],
              "LAY": p["layers_on_hand"]["central"]}
    scale = {sp: target[sp] / sum(heads[sp].values()) for sp in SPECIES}
    heads = {sp: {c: v * scale[sp] for c, v in h.items()} for sp, h in heads.items()}
    print("GASTAT 2024 regional tables scaled to the params.json totals:",
          {sp: f"x{scale[sp]:.6f}" for sp in SPECIES})

    # 2. placement within each region
    def weights(c, sp):
        """Where region c's collectable part of species sp is placed: (weights summing to 1, basis)."""
        r = inside[c]
        if sp == "CTL":
            mine = (f.iso == c).values
            tries = ((field_area(mine & (f.class_s2 == "year_round").values), "year-round fields"),
                     (field_area(mine), "all mapped fields"),
                     (glw["CTL"] * r * mask_of[sp], "GLW4 cattle near fields and settlements"),
                     (glw["CTL"] * r, "GLW4 cattle"))
        else:
            g = glw["CHK" if sp in ("BRL", "LAY") else sp]
            where = "fields, cities, towns and villages" if sp in ("BRL", "LAY") else "fields and settlements"
            tries = ((g * r * mask_of[sp], f"GLW4 near {where}"), (g * r, "GLW4, whole region"),
                     (r.astype(float), "evenly over the region"))
        for w, basis in tries:
            if w.sum() > 0:
                return w / w.sum(), basis
        raise RuntimeError(f"nowhere to place {sp} in {GASTAT_NAME[c]}")

    share = {}
    for sp in SPECIES:
        n = sum(heads[sp].values())
        share[sp] = np.zeros(dims)
        used = {}
        for c in iso:
            if heads[sp][c] > 0:
                w, basis = weights(c, sp)
                share[sp] += w * heads[sp][c] / n
                used.setdefault(basis, []).append(c)
        print(f"{sp} placed by", "; ".join(
            f"{basis}: {sum(heads[sp][c] for c in cs) / n:.1%} ({', '.join(GASTAT_NAME[c] for c in cs)})"
            for basis, cs in used.items()))
        if sp != "CTL":  # how much of the GLW4 pattern lay away from fields and settlements
            g = glw["CHK" if sp in ("BRL", "LAY") else sp]
            far = sum(heads[sp][c] / n * g[inside[c] & ~mask_of[sp]].sum() / g[inside[c]].sum() for c in iso
                      if heads[sp][c] > 0 and g[inside[c]].sum() > 0)
            print(f"  {far:.1%} sat in GLW4 cells farther than {NEAR_KM:g} km from the mask and was moved in")

    keep = np.zeros(dims, bool)
    for s in share.values():
        keep |= s > 0
    out = pd.DataFrame({"lon": lon[keep], "lat": lat[keep], **{f"share_{sp}": share[sp][keep] for sp in SPECIES}})
    for lv in LV:
        out[f"litter_t_dry_{lv}"], out[f"manure_t_dry_{lv}"] = tonnes(out, p, tot, lv)
    total = {k: out[f"{k}_t_dry_central"].sum() for k in ("litter", "manure")}
    out = out[(out.litter_t_dry_central + out.manure_t_dry_central) > CUT_T].reset_index(drop=True)
    print(f"kept after the {CUT_T} t cell cut:", {k: f"{out[f'{k}_t_dry_central'].sum() / total[k]:.2%}" for k in total})
    out.to_csv(NAT / "manure_points.csv", index=False)
    meta = placement_inputs(NAT) | {"manure_points_sha256": sha256_file(NAT / "manure_points.csv")}
    (NAT / META).write_text(json.dumps(meta, indent=1) + "\n")
    print(len(out), "cells;", {f"{k}_{lv}": f"{out[f'{k}_t_dry_{lv}'].sum() / 1e6:.3f} Mt" for k in ("litter", "manure")
                               for lv in LV})


if __name__ == "__main__":
    main()
