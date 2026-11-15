"""National biochar siting with mixed feedstocks (greedy facility location).

Supply points
  straw   radar wheat fields: winter-only and wheat rotations (data/national/fields_national.csv)
  fronds  radar palm-grove fields (same file)
  litter  poultry litter, ~10 km cells (data/national/manure_points.csv, modelled)
  manure  cattle/sheep/goat manure, ~10 km cells (same file, modelled)
Each feedstock has its own char yield, organic C and H/C_org (model/params.json).
Residue tiers (supply(tier=...)): 'radar' reads the radar-only columns straw_t_dry_<level> and fronds_t_dry_<level>;
'radar_s2' reads the radar + Sentinel-2 tier straw_t_dry_s2_<level> and fronds_t_dry_s2_<level> (Sentinel-2 adds
winter crops the radar missed and classifies seasons and fields the radar could not observe; straw on Sentinel-2-filled
wheat is capped per administrative region at GASTAT 2024 wheat area, model/national_supply.py).
Coverage: straw and fronds exist only on the mapped fields of the 60 processed region boxes; litter and manure
are modelled for all of Saudi Arabia. The *_boxes_* runs cut litter and manure to the same 60 boxes.

Crediting (Puro.earth Biochar Methodology 2025 v2)
  Persistence PF = (M - a x H/C_org) / 100 with M, a for the soil temperature (Table 6.1; one national value,
  30 C central, 33 C in the low corner and 25 C in the high corner, not yet set per region of first use); a stream
  with H/C_org >= 0.70 earns nothing (rule 3.5.1) and is left out of the supply (its tonnage is reported as
  uncredited_supply_by_feed_t). Poultry litter's H/C_org (organic-carbon basis, rule 6.1.6) is at or above 0.70 at
  every level, so no credited run includes it; the litter upside runs are hypothetical totals at its total-carbon
  H/C (h_c_org_litter "upside" in params.json), never credited. Char in cement is credited with the same soil model
  (rule 6.2.4), so both outlets earn the same credit and the outlet is chosen by haul. No contaminant screen: each
  feed's soil-use status (Table 3.3 limits, rule 3.6.9) is listed for the page in params.json "_soil_use".
  Production and embodied emissions and leakage are not subtracted (a technical potential, not a credit volume).
  In-service retention in cement (cement_retention) is reported, not credited. Soil absorption is not limited here
  (gross technical framing); constrained cases are in model/national_scenarios.py.

Method
  Candidate sites: the operating cement plants + a 0.25 degree grid over cells with supply.
  A plant of capacity C draws the nearest supply within RADIUS_KM until C is met
  (needs >= 80% of C). Its net removal = credited char C x 44/12 x PF, minus truck emissions for feed
  in and char out (to the fields it came from, or to the nearest cement plant if that haul is shorter).
  Place the plant with the largest net removal, remove its supply, repeat. The greedy order is path-dependent: a
  near-tie between two sites can add or drop a whole plant later, so removal need not fall steadily with plant size.

Runs (main; each summary entry carries a "basis" note)
  central_<size>kt                  every factor central; straw, fronds and manure (litter not credited)
  central_radar_<size>kt            the same, radar-measured residues only (straw + fronds)
  central_radar_s2_50kt             radar + Sentinel-2 residues only (Sentinel-2 fills capped at GASTAT wheat); an
                                    upper value: fields with no usable radar season count as farmed, and only wheat
                                    straw is capped at GASTAT (fronds are not)
  central_boxes_<size>kt            manure cut to the 60 processed region boxes (the radar coverage)
  central_litter_upside_50kt        hypothetical total with litter at its total-carbon H/C (0.69); not credited,
                                    upside_of central_50kt
  central_litter_upside_boxes_50kt  the same on the boxes coverage; upside_of central_boxes_50kt
  low_<size>kt, high_<size>kt       corners: the level factors at their least (most) favourable values at once, not
                                    a probability interval; road circuity and truck factor held central so the
                                    corners bracket removal
  low_radar_50kt, high_radar_50kt   the corners, radar-measured residues only
  (<size> = 10, 25, 50 kt)

Output: out/national_plants_<tag>.csv and summary in out/national_siting.json (keys: summarize())
Usage:  .venv/bin/python model/national_siting.py [central] [low] [high]   (default all three; each call replaces the last)
        It stops before any run if data/national/manure_points.csv does not match params.json or the placement inputs
        recorded in its sidecar manure_points.meta.json (check_manure_points): rerun model/manure.py first.
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CO2_PER_C = 44 / 12
RADIUS_KM = 100.0  # assumption: farthest a plant draws feedstock from (sensitivity-tested)
MAX_PLANTS = 600   # safety stop, above the largest run (high_10kt needs more than 400 plants); reported if reached
FEEDS = ("straw", "fronds", "litter", "manure")
RADAR = ("straw", "fronds")  # radar-measured streams; litter and manure are modelled
LEVELS = ("central", "low", "high")
SIZES = (10000, 25000, 50000)
TIERS = {"radar": "", "radar_s2": "_s2"}  # residue tier -> column infix in fields_national.csv (straw_t_dry<infix>_<level>)
MANURE_TOL = 0.005  # largest share by which manure_points.csv totals may differ from params.json (check_manure_points)
# greedy-siting note on the central_radar_<size>kt runs; main() drops NOT_MONOTONIC if a run's removals say otherwise
PATH_DEPENDENT = "Greedy siting is path-dependent: a near-tie between sites can add or drop a whole plant"
NOT_MONOTONIC = ", which is why radar-only removal is not monotonic in plant size"


def params(level):
    raw = json.loads((ROOT / "model" / "params.json").read_text())
    return {k: v[level] for k, v in raw.items() if not k.startswith("_") and isinstance(v, dict) and level in v}


def hav(lon1, lat1, lon2, lat2):
    lon1, lat1, lon2, lat2 = map(np.radians, (lon1, lat1, lon2, lat2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * np.arcsin(np.sqrt(a))


def region_boxes(n=60):
    """Bounding boxes [lon0, lat0, lon1, lat1] of the processed regions R01..R<n> (data/national/regions.json)."""
    ids = {f"R{i:02d}" for i in range(1, n + 1)}
    return [r["bbox"] for r in json.loads((ROOT / "data" / "national" / "regions.json").read_text()) if r["id"] in ids]


def in_boxes(lon, lat, boxes):
    """True where a point lies in any of the boxes (edges included)."""
    lon, lat = np.asarray(lon, float), np.asarray(lat, float)
    inside = np.zeros(len(lon), bool)
    for x0, y0, x1, y1 in boxes:
        inside |= (lon >= x0) & (lon <= x1) & (lat >= y0) & (lat <= y1)
    return inside


def supply(level, p, feeds=None, boxes=None, tier="radar"):
    """Supply points with their char factors. boxes: if given, litter and manure are kept only inside them
    (straw and fronds come from the mapped fields of the processed boxes already and are left as they are).
    tier: which straw and fronds columns to read (TIERS). Streams that fail the H/C_org gate are left out; their
    tonnage in this coverage is kept in attrs["uncredited_supply_by_feed_t"] (litter always listed)."""
    if tier not in TIERS:
        raise ValueError(f"unknown residue tier {tier!r}; use one of {list(TIERS)}")
    cols = {feed: f"{feed}_t_dry{TIERS[tier]}_{level}" for feed in RADAR}
    f = pd.read_csv(ROOT / "data" / "national" / "fields_national.csv", usecols=["lon", "lat", "region", *cols.values()],
                    low_memory=False)
    parts = []
    for feed, col in cols.items():
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
    if boxes is not None:  # modelled streams cut to the radar coverage
        s = s[s.feed.isin(RADAR).values | in_boxes(s.lon.values, s.lat.values, boxes)].reset_index(drop=True)
    yld = {"straw": p["char_yield_dry"], "fronds": p["palm_char_yield_dry"], "litter": p["litter_char_yield_dry"], "manure": p["manure_char_yield_dry"]}
    cor = {"straw": p["char_c_org"], "fronds": p["palm_char_c_org"], "litter": p["litter_char_c_org"], "manure": p["manure_char_c_org"]}
    per = {f: persistence(p, f) for f in FEEDS}
    dm = {"straw": p["straw_dry_matter"], "fronds": p["palm_frond_dry_matter"], "litter": p["litter_dry_matter"],
          "manure": p["manure_dry_matter"]}  # wet tonnes hauled per dry tonne = 1 / DM
    s["char_t_per_t"] = s.feed.map(yld)
    s["c_per_t"] = s.feed.map(yld) * s.feed.map(cor)
    s["soil_perm"] = s.feed.map(per)
    s["wet_per_dry"] = 1 / s.feed.map(dm)
    ok = s.soil_perm > 0
    gated = s[~ok].groupby("feed").dry_t.sum()
    out = s[ok].reset_index(drop=True)  # streams failing the H/C_org gate earn nothing: left out
    out.attrs["uncredited_supply_by_feed_t"] = {"litter": 0.0} | {k: float(v) for k, v in gated.items()}
    return out


def persistence(p, feed):
    """Puro 2025 v2 persistence fraction for a feed at the level's soil temperature; 0 if H/C_org >= 0.70."""
    raw = json.loads((ROOT / "model" / "params.json").read_text())
    m, a = raw["puro_pf_table"]["values"][str(int(p["soil_temp_c"]))]
    hc = p[f"h_c_org_{feed}"]
    return 0.0 if hc >= 0.70 else (m - a * hc) / 100


def manure_points_gaps(m, levels=LEVELS):
    """{"<feed>_<level>": (t in the file, t params.json gives now, relative gap)} for litter and manure in a
    data/national/manure_points.csv frame m. Recomputed with model/manure.py's own steps (tonnes()) on the file's own
    inputs, the factor-free shares of the national herds placed in each cell (share_CTL, share_SHP, share_GTS,
    share_BRL, share_LAY): heads = share x the GASTAT 2024 totals (or layers_on_hand) in params.json, per-cell tonnes
    from params.json, rounded to 0.1 t as written, then its cell cut (model/manure.py CUT_T) on central litter +
    manure. A change to the head totals or to any factor is caught. The file keeps only the cells that passed the cut
    when it was written, so a cell a new cut would add is not seen (check_manure_points catches a changed CUT_T through
    the sidecar), and a change to model/manure.py's regional tables or placement code is not (rerun model/manure.py
    after editing it)."""
    import manure  # model/manure.py, next to this file: its CUT_T
    raw = json.loads((ROOT / "model" / "params.json").read_text())
    p = {k: v for k, v in raw.items() if not k.startswith("_")}
    tot = raw["gastat_2024_totals"]["values"]

    def cells(lv):  # as model/manure.py tonnes(), term by term
        litter = (m.share_BRL * tot["broilers_produced"] * p["broiler_litter_kg_dry_per_bird"][lv]
                  + m.share_LAY * p["layers_on_hand"][lv] * p["layer_manure_kg_dry_per_hen"][lv]) \
            * p["collectable_share_poultry"][lv] / 1000
        manure = (m.share_CTL * tot["cattle"] * p["cattle_manure_kg_dry_per_head"][lv] * p["collectable_share_cattle"][lv]
                  + (m.share_SHP * tot["sheep"] + m.share_GTS * tot["goats"])
                  * p["small_ruminant_manure_kg_dry_per_head"][lv] * p["collectable_share_small_ruminants"][lv]) / 1000
        return {"litter": litter.round(1), "manure": manure.round(1)}

    cen = cells("central")
    keep = (cen["litter"] + cen["manure"]) > manure.CUT_T  # model/manure.py's cut of near-empty cells, central level
    gaps = {}
    for lv in levels:
        for feed, t in cells(lv).items():
            have, want = float(m[f"{feed}_t_dry_{lv}"].sum()), float(t[keep].sum())
            gaps[f"{feed}_{lv}"] = (have, want, (have - want) / want if want else (0.0 if have == 0 else float("inf")))
    return gaps


def check_manure_points(levels=LEVELS):
    """Stop (RuntimeError) unless data/national/manure_points.csv exists, its sidecar manure_points.meta.json (written
    with it by model/manure.py) matches the current placement inputs and the CSV itself, and its litter and manure
    totals at each of levels are within MANURE_TOL of what params.json gives now (manure_points_gaps). The sidecar
    check catches a change to fields_national.csv's placement columns, to osm_places.csv, or to model/manure.py's
    NEAR_KM or CUT_T since the run (manure.placement_inputs), and a CSV that is not the one that run wrote. A stale
    file would otherwise be sited as it is. Returns the largest gap."""
    import manure  # model/manure.py, next to this file: the placement fingerprint and CUT_T
    nat = ROOT / "data" / "national"
    mp = nat / "manure_points.csv"
    if not mp.exists():
        raise RuntimeError("data/national/manure_points.csv not found: run model/manure.py first")
    meta = nat / manure.META
    if not meta.exists():
        raise RuntimeError(f"data/national/{manure.META} not found: rerun model/manure.py")
    have = json.loads(meta.read_text())
    want = json.loads(json.dumps(manure.placement_inputs(nat) | {"manure_points_sha256": manure.sha256_file(mp)}))
    moved = [k if k.endswith("sha256") else f"{k} ({have.get(k)!r} recorded, {want[k]!r} now)" for k in want
             if have.get(k) != want[k]]
    if moved:
        raise RuntimeError(f"data/national/manure_points.csv does not match data/national/{manure.META}: "
                           f"{'; '.join(moved)} changed since model/manure.py ran: rerun model/manure.py, then "
                           "model/national_siting.py.")
    m = pd.read_csv(mp)
    need = [f"share_{sp}" for sp in ("CTL", "SHP", "GTS", "BRL", "LAY")] + [f"{f}_t_dry_{lv}" for lv in levels
                                                                            for f in ("litter", "manure")]
    miss = [c for c in need if c not in m.columns]
    if miss:
        raise RuntimeError(f"data/national/manure_points.csv lacks {miss}: rerun model/manure.py")
    gaps = manure_points_gaps(m, levels)
    bad = {k: g for k, g in gaps.items() if not abs(g[2]) <= MANURE_TOL}
    if bad:
        raise RuntimeError(
            "data/national/manure_points.csv is stale: its totals differ by more than "
            f"{MANURE_TOL:.1%} from what model/params.json gives now through model/manure.py's formula (same "
            f"{manure.CUT_T} t cell cut), so model/manure.py was not rerun after a change: "
            + "; ".join(f"{k} {h:,.0f} t in the file against {w:,.0f} t ({g:+.2%})" for k, (h, w, g) in bad.items())
            + ". Rerun model/manure.py, then model/national_siting.py.")
    return max((abs(g[2]) for g in gaps.values()), default=0.0)


def _inside_regions(s):
    """Per supply point of s: inside any of the 60 processed boxes? None when data/national/regions.json is absent
    (e.g. the temporary ROOT model/national_scenarios.py builds for its supply)."""
    if not (ROOT / "data" / "national" / "regions.json").exists():
        return None
    return in_boxes(s.lon.values, s.lat.values, region_boxes())


def run(level, size_t, cement, p, feeds=None, boxes=None, tier="radar"):
    s = supply(level, p, feeds, boxes, tier)
    pool = s.copy()
    pool.attrs = {}  # the supply's notes stay on s; the pool is sliced in the loop
    inside = _inside_regions(s)  # aligned with s's row labels, which the pool keeps
    ef = p["truck_kgco2e_per_tkm"] / 1000
    circ = p["road_circuity"]
    grid = pool.assign(gx=(pool.lon / 0.25).round() * 0.25, gy=(pool.lat / 0.25).round() * 0.25)[["gx", "gy"]].drop_duplicates()
    sites = pd.concat([pd.DataFrame({"lon": cement.lon, "lat": cement.lat, "kind": "cement", "name": cement.city.fillna("") + " cement"}),
                       pd.DataFrame({"lon": grid.gx, "lat": grid.gy, "kind": "grid", "name": ""})], ignore_index=True)
    plants = []
    fed = {f: 0.0 for f in FEEDS}  # unrounded feed used, by stream
    credited = {f: 0.0 for f in fed}  # credited removal by stream before haulage (t CO2)
    outside = 0.0  # feed taken from supply points outside every processed box (t dry)
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
                mix = {f: float(w[sub.feed.values == f].sum()) for f in FEEDS}
                cred = {f: float((w * sub.c_per_t.values * sub.soil_perm.values)[sub.feed.values == f].sum()) * CO2_PER_C
                        for f in FEEDS}  # credited removal by stream, before haulage
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
        if inside is not None:
            outside += float(used[~inside[idx]].sum())
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
                  "credited_by_feed_tco2": credited, "feed_outside_boxes_t": outside if inside is not None else None}
    return out, s


def _join(words):
    words = list(words)
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def plan(levels=LEVELS, sizes=SIZES):
    """The runs main() makes, as dicts: tag, level, size_t, feeds (None = all), overrides (params.json values
    replaced on top of the level), boxed (litter and manure cut to the 60 boxes), tier (residue tier, TIERS),
    upside_of (for an uncredited upside: the credited tag it adds to; None otherwise) and basis (the label note)."""
    raw = json.loads((ROOT / "model" / "params.json").read_text())
    temp = raw["soil_temp_c"]
    held = {k: raw[k]["central"] for k in ("road_circuity", "truck_kgco2e_per_tkm")}  # transport in the corners
    hc_up = raw["h_c_org_litter"]["upside"]
    upside = {"h_c_org_litter": hc_up}
    hc_moves = {f: len({raw[f"h_c_org_{f}"][lv] for lv in LEVELS}) > 1 for f in FEEDS}
    label = {"straw": "straw", "fronds": "palm-frond", "manure": "manure"}
    no_litter = ("poultry litter is not credited (its char's H/C_org is at or above 0.70 on the organic-carbon basis, "
                 "rule 3.5.1)")
    all_feeds = ("Feeds: wheat straw and palm fronds from the radar-mapped fields of the 60 processed region boxes, and "
                 f"cattle, sheep and goat manure modelled for all of Saudi Arabia; {no_litter}.")
    mapped = "wheat straw and palm fronds from the mapped fields of the 60 processed region boxes"
    radar = f"radar-measured residues only: {mapped}; no modelled manure or litter."
    radar_s2 = (f"radar + Sentinel-2 residues (Sentinel-2 fills capped at GASTAT wheat): {mapped}, where Sentinel-2 adds "
                "winter crops the radar missed and classifies seasons and fields the radar could not observe; no "
                "modelled manure or litter; an upper value: fields with no usable radar season count as farmed, and "
                "only wheat straw is capped at GASTAT (fronds are not).")
    boxes = "the 60 processed region boxes (bounding boxes of R01-R60), where the radar maps straw and fronds"

    def upside_note(of, coverage):
        return (f"Total if litter char were credited (hypothetical upper bound: litter at H/C {hc_up}, its total-carbon "
                "value; a char that met Puro's organic-carbon gate would be made hotter and yield less); subtract "
                f"{of} for the increment. {coverage}")

    def corner(lvl, fs):
        what = ["crop-residue and manure supply" if "manure" in fs else "straw and frond supply",
                "char yields and organic carbon"]
        moving = [label[f] for f in fs if hc_moves[f]]
        fixed = [label[f] for f in fs if not hc_moves[f]]
        if moving:
            what.append(f"char H/C_org of {_join(moving)}")
        what += ["straw dry matter", f"soil temperature ({'hottest' if temp[lvl] > temp['central'] else 'coolest'}, "
                                     f"{temp[lvl]} C)"]
        note = (f"{lvl.capitalize()} corner: {_join(what)} all take their {'least' if lvl == 'low' else 'most'} "
                "favourable values at once")
        if fixed:
            note += f"; {_join(fixed)} char {'has' if len(fixed) == 1 else 'have'} one H/C_org value at every level"
        return (f"{note}. This is not a probability interval. Road circuity and the truck emission factor are held at "
                "central, so the corners bracket removal.")

    def entry(tag, lvl, z, basis, feeds=None, over=None, boxed=False, tier="radar", upside_of=None):
        return {"tag": tag, "level": lvl, "size_t": z, "feeds": feeds, "overrides": over or {}, "boxed": boxed,
                "tier": tier, "upside_of": upside_of, "basis": basis}

    runs = []
    for lvl in levels:
        if lvl == "central":
            runs += [entry(f"central_{z // 1000}kt", lvl, z, f"Central: every factor at its central value. {all_feeds}")
                     for z in sizes]
            runs += [entry(f"central_radar_{z // 1000}kt", lvl, z, f"Central, {radar} {PATH_DEPENDENT}{NOT_MONOTONIC}.",
                           RADAR) for z in sizes]
            if 50000 in sizes:
                runs.append(entry("central_radar_s2_50kt", lvl, 50000, f"Central, {radar_s2}", RADAR, tier="radar_s2"))
            runs += [entry(f"central_boxes_{z // 1000}kt", lvl, z,
                           f"Same coverage: central with manure cut to {boxes}, so every stream shares the radar "
                           f"coverage; {no_litter}.", boxed=True) for z in sizes]
            if 50000 in sizes:
                runs += [entry("central_litter_upside_50kt", lvl, 50000,
                               upside_note("central_50kt", "Litter and manure are modelled for all of Saudi Arabia."),
                               over=upside, upside_of="central_50kt"),
                         entry("central_litter_upside_boxes_50kt", lvl, 50000,
                               upside_note("central_boxes_50kt", f"Litter and manure cut to {boxes}."),
                               over=upside, boxed=True, upside_of="central_boxes_50kt")]
        else:
            runs += [entry(f"{lvl}_{z // 1000}kt", lvl, z, f"{corner(lvl, ('straw', 'fronds', 'manure'))} {all_feeds}",
                           over=held) for z in sizes]
            if 50000 in sizes:
                runs.append(entry(f"{lvl}_radar_50kt", lvl, 50000, f"{corner(lvl, RADAR)} {radar[0].upper()}{radar[1:]}",
                                  RADAR, over=held))
    return runs


def summarize(df, s, p, r, boxes):
    """One out/national_siting.json entry for plan() entry r; df, s are run()'s plants and supply, boxes the 60
    processed boxes. Keys, in order:
      basis, level, size_t, overrides   the label note, the level, plant size (t dry/yr), params.json values replaced
      credited             False for an upside (a hypothetical total, never credited), True otherwise
      upside_of            (upsides only) the credited tag to subtract for what litter would add
      residue_tier         'radar' or 'radar_s2': the straw and fronds columns read (supply())
      livestock_coverage   'kingdom', 'boxes', or None when the run has no litter or manure
      plants, plants_outside_boxes   plants, and plants whose SITE lies outside every R01-R60 box (this counts
                           sites: a plant just outside a box can draw all its feed from inside)
      distinct_sites       unique plant coordinates (several plants can share a site)
      feed_used_t, feed_outside_boxes_t   feed used (t dry/yr), and the part taken from supply points outside every
                           box (by where the points lie, not where the plant sits; None without regions.json)
      supply_t, supply_by_feed_t   credited supply in the run's coverage (t dry/yr)
      uncredited_supply_by_feed_t  (credited entries only) supply in the run's coverage that the H/C_org gate leaves
                           out, before the gate (t dry/yr); litter is always listed (0 when the run has no litter)
      net_removal_tco2, cement_outlet_plants, cement_retained_tco2   as before
      credited_basis       the crediting rule; for an upside 'not credited: hypothetical upper bound with litter at its
                           total-carbon H/C ...' (its removal keys, credited_by_feed_tco2 included, are hypothetical)
      persistence, median_transport_share, feed_used_by_feed_t, credited_by_feed_tco2, capped, supply_left_t, feeds,
      radius_km            as before"""
    n = len(df)
    feeds, boxed = r["feeds"], r["boxed"]
    livestock = feeds is None or bool(set(feeds) & {"litter", "manure"})
    out_t = df.attrs.get("feed_outside_boxes_t")
    e = {"basis": r["basis"], "level": r["level"], "size_t": r["size_t"], "overrides": r["overrides"],
         "credited": r["upside_of"] is None}
    if r["upside_of"] is not None:
        e["upside_of"] = r["upside_of"]
    e |= {"residue_tier": r["tier"], "livestock_coverage": ("boxes" if boxed else "kingdom") if livestock else None,
          "plants": int(n),
          "plants_outside_boxes": int((~in_boxes(df.lon.values, df.lat.values, boxes)).sum()) if n else 0,
          "distinct_sites": int(len(df[["lon", "lat"]].drop_duplicates())) if n else 0,
          "feed_used_t": round(float(df.feed_t_dry.sum())) if n else 0,
          "feed_outside_boxes_t": None if out_t is None else round(out_t),
          "supply_t": round(float(s.dry_t.sum())), "supply_by_feed_t": s.groupby("feed").dry_t.sum().round().to_dict()}
    if r["upside_of"] is None:
        e["uncredited_supply_by_feed_t"] = {f: round(v) for f, v in s.attrs.get("uncredited_supply_by_feed_t", {}).items()}
    e |= {"net_removal_tco2": round(float(df.net_removal_tco2.sum())) if n else 0,
          "cement_outlet_plants": int((df.best_outlet == "cement").sum()) if n else 0,
          "cement_retained_tco2": round(float(df.cement_retained_tco2.sum())) if n else 0,
          "credited_basis": (f"not credited: hypothetical upper bound with litter at its total-carbon H/C "
                             f"{p['h_c_org_litter']} (h_c_org_litter upside)" if r["upside_of"] is not None
                             else "Puro.earth 2025 v2: soil persistence model for soil and cement (rule 6.2.4), "
                                  "H/C_org < 0.70 gate; soil absorption not limited"),
          "persistence": {f: round(persistence(p, f), 4) for f in FEEDS},
          "median_transport_share": round(float(df.transport_share.median()), 4) if n else None,
          "feed_used_by_feed_t": {f: round(v) for f, v in df.attrs.get("feed_used_by_feed_t", {}).items()},
          "credited_by_feed_tco2": {f: round(v) for f, v in df.attrs.get("credited_by_feed_tco2", {}).items()},
          "capped": bool(df.attrs.get("capped", False)), "supply_left_t": round(df.attrs.get("supply_left_t", 0.0)),
          "feeds": list(feeds) if feeds else "all", "radius_km": RADIUS_KM}
    return e


def main(levels=LEVELS, sizes=SIZES):
    gap = check_manure_points(levels)  # stops before any run if model/manure.py was not rerun after a params change
    print(f"manure points match params.json (largest gap {gap:.3%}, limit {MANURE_TOL:.1%})", flush=True)
    cement = pd.read_csv(ROOT / "data" / "cement" / "saudi_cement.csv")
    cement = cement[cement.status != "Closed"].reset_index(drop=True)  # closed plants take no char
    boxes = region_boxes()
    summ = {}
    t_all = time.time()
    for r in plan(levels, sizes):
        t0 = time.time()
        p = params(r["level"]) | r["overrides"]
        df, s = run(r["level"], r["size_t"], cement, p, r["feeds"], boxes if r["boxed"] else None, r["tier"])
        df.to_csv(ROOT / "out" / f"national_plants_{r['tag']}.csv", index=False)
        summ[r["tag"]] = summarize(df, s, p, r, boxes)
        print(f"{r['tag']} ({time.time() - t0:.0f} s)", json.dumps(summ[r["tag"]]), flush=True)
    # the central_radar basis says radar-only removal is not monotonic in plant size: if this run's removals (two or
    # more sizes) fall or rise steadily after all, drop that clause and keep the path-dependence note
    rad = [summ[t]["net_removal_tco2"] for t in (f"central_radar_{z // 1000}kt" for z in sorted(sizes)) if t in summ]
    steps = list(zip(rad, rad[1:]))
    if steps and (all(a >= b for a, b in steps) or all(a <= b for a, b in steps)):
        for e in summ.values():
            e["basis"] = e["basis"].replace(NOT_MONOTONIC, "")
        print(f"radar-only removal is monotonic in plant size in this run ({rad} t): basis clause dropped", flush=True)
    # this run replaces the previous one: scenarios it did not produce (e.g. a run without the corners) are removed
    for f in (ROOT / "out").glob("national_plants_*.csv"):
        if f.stem.replace("national_plants_", "") not in summ:
            f.unlink()
    (ROOT / "out" / "national_siting.json").write_text(json.dumps(summ, indent=1))
    print(f"{len(summ)} runs in {time.time() - t_all:.0f} s", flush=True)


if __name__ == "__main__":
    lv = sys.argv[1:] or list(LEVELS)
    bad = [x for x in lv if x not in LEVELS]
    if bad:
        raise SystemExit(f"unknown level(s) {bad}; use any of {list(LEVELS)}")
    main(tuple(lv))
