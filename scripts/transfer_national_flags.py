"""Give the Qassim deep-dive fields the national run's spring check, and a WorldCover tree cover of their own.

The national run flags each of its 40 m fields with
  tree_frac           share of the field's pixels that ESA WorldCover v200 calls tree cover (class 10;
                      scripts/region_pipeline.py). Palm groves need >= 0.3 and radar activity in every season
                      (model/national_supply.py)
  spring_brown        Sentinel-2 median NDVI below 0.30 over 20 Apr - 5 Jun 2026 (scripts/s2_spring.py): a field
                      farmed in winter and summer that browns in late spring is wheat followed by a summer crop.
                      Empty = no clear look
  ndvi_spring_median  that median NDVI
The 20 m deep dive (data/fields/fields_labels.tif) has none of them.

tree_frac is computed here for every deep field from its own pixels, as region_pipeline does for national fields:
each deep pixel takes the WorldCover class of the national regions' cached rasters (data/regions/<R>/worldcover.tif,
40 m, the first region whose raster has data there); pixels without WorldCover data count as not tree, as in
region_pipeline. tree_frac_source records where the value comes from, as a short code (TREE_SRC):
wc = worldcover_deep_pixels; nat = national_field (no WorldCover pixel on the field, so the matched national field's
value); empty = neither.

spring_brown and ndvi_spring_median come from the national field covering at least half of the deep field's pixels
(the unrounded share is tested). The national grids nest exactly in the deep grid (both EPSG:32638, 40 m in 20 m), so
every deep pixel lies inside one national pixel. National copies dropped as duplicates (a field mapped by a second
region) are not used. Fields without such a match keep an empty spring flag, so model/supply.py leaves them
year-round when farmed in both seasons, as model/national_supply.py does when the spring check is missing.

Check (the script stops before writing anything): every fields_radar.csv id is in the label raster, and each
field's pixel count x pixel area equals its area_ha within 0.005 ha. The label raster is gitignored, so a stale copy
would otherwise give wrong flags without notice. scripts/export_web.py runs the same check (check_labels).

Input   data/fields/fields_labels.tif, data/fields/fields_radar.csv
        data/regions/<R>/fields_labels.tif and worldcover.tif for every national region whose box overlaps
        config.json's bbox
        data/national/fields_national.csv (or --national PATH)
Output  data/fields/national_flags.csv, one row per deep field:
        id, area_ha (as in fields_radar.csv; model/supply.py checks it to catch a stale file), national_uid
        (national field with the largest overlap, empty if none), overlap_frac (share of the deep field's pixels
        inside it, written to 4 decimals), matched (overlap share >= 0.5, unrounded), tree_frac (the deep field's
        own pixels), tree_frac_source (code, see above), tree_frac_national (the matched national field's value),
        spring_brown and ndvi_spring_median (the matched national field's values; empty unless matched)
        data/fields/national_flags.json, written once per run, after the csv: the national table used and its md5
        (model/supply.py compares it with the current table), the csv's md5 (so the two files can be checked to
        belong together), the match counts, the matched fields' spring flags and the tree_frac_source codes and counts
Usage   .venv/bin/python scripts/transfer_national_flags.py [--national PATH]
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[1]
MIN_OVERLAP = 0.5
AREA_TOL_HA = 0.005
TREE = 10  # ESA WorldCover v200 tree cover
SPRING = ("spring_brown", "ndvi_spring_median")
TREE_SRC = {"wc": "worldcover_deep_pixels", "nat": "national_field"}  # tree_frac_source codes; empty = neither


def tri(s):
    """True/False column that may have gaps, as object dtype: True, False or NaN (as model/national_supply.tri)."""
    return s.map({True: True, False: False, "True": True, "False": False}).astype(object)


def check_labels(lab, transform, table, name="data/fields/fields_labels.tif", table_name="data/fields/fields_radar.csv"):
    """Stop unless the label raster belongs to the field table: every table id has pixels, and pixel count x pixel
    area equals area_ha within AREA_TOL_HA. Returns the pixel count per table row (Series aligned with table)."""
    px_ha = abs(transform.a * transform.e - transform.b * transform.d) / 1e4
    ids, n = np.unique(lab[lab > 0], return_counts=True)
    px = table.id.map(pd.Series(n, index=ids))
    missing = table.id[px.isna()]
    diff = (px * px_ha - table.area_ha).abs()
    off = table[px.notna() & (diff > AREA_TOL_HA)]
    if len(missing) or len(off):
        eg = [f"id {i}: {a} ha in the table, {p * px_ha:.2f} ha in the raster"
              for i, a, p in zip(off.id[:3], off.area_ha[:3], px[off.index][:3])]
        raise SystemExit(f"{name} does not belong to {table_name}: {len(missing)} of {len(table)} ids have no pixels"
                         f"{' (e.g. ' + ', '.join(map(str, missing[:5])) + ')' if len(missing) else ''}, and "
                         f"{len(off)} field areas differ by more than {AREA_TOL_HA} ha{' (' + '; '.join(eg) + ')' if eg else ''}. "
                         f"Nothing written. Use the label raster made with this field table.")
    extra = np.setdiff1d(ids, table.id.values)
    print(f"{name}: all {len(table):,} field ids present, areas agree within {AREA_TOL_HA} ha"
          f"{f'; {len(extra)} raster ids are not in the table (ignored)' if len(extra) else ''}")
    return px.astype(int)


def overlapping_regions(cfg):
    """National regions (data/national/regions.json order) whose box overlaps config.json's bbox."""
    x0, y0, x1, y1 = cfg["bbox"]
    return [r["id"] for r in json.loads((ROOT / "data" / "national" / "regions.json").read_text())
            if r["bbox"][0] < x1 and r["bbox"][2] > x0 and r["bbox"][1] < y1 and r["bbox"][3] > y0]


def sample(path, xs, ys, crs):
    """Values of a single-band raster at points (xs, ys in crs), and which points it covers."""
    with rasterio.open(path) as src:
        a, t, rcrs = src.read(1), src.transform, src.crs
    px, py = (xs, ys) if rcrs == crs else Transformer.from_crs(crs, rcrs, always_xy=True).transform(xs, ys)
    c, r = ~t * (px, py)
    c, r = np.floor(c).astype(int), np.floor(r).astype(int)
    inside = (c >= 0) & (c < a.shape[1]) & (r >= 0) & (r < a.shape[0])
    v = np.zeros(len(xs), dtype=a.dtype)
    v[inside] = a[r[inside], c[inside]]
    return v, inside


def rel(p):
    """A path relative to the repository when it lies inside it, else as given."""
    try:
        return str(Path(p).resolve().relative_to(ROOT))
    except ValueError:
        return str(p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--national", default=str(ROOT / "data" / "national" / "fields_national.csv"),
                    help="national field table (model/national_supply.py output)")
    a = ap.parse_args()
    cfg = json.loads((ROOT / "config.json").read_text())

    fd = ROOT / "data" / "fields"
    ids = pd.read_csv(fd / "fields_radar.csv", usecols=["id", "area_ha"])
    with rasterio.open(fd / "fields_labels.tif") as src:
        lab, tf, crs = src.read(1), src.transform, src.crs
    check_labels(lab, tf, ids)
    rows, cols = np.nonzero(np.isin(lab, ids.id.values))
    deep = lab[rows, cols]
    xs, ys = tf * (cols + 0.5, rows + 0.5)  # deep pixel centres
    deep_px = pd.Series(deep).value_counts()

    nat_path = Path(a.national)
    nat_md5 = hashlib.md5(nat_path.read_bytes()).hexdigest()
    nat = pd.read_csv(nat_path, usecols=["uid", "region", "id", "tree_frac", *SPRING], low_memory=False)
    nat["spring_brown"] = tri(nat.spring_brown)
    kept = set(nat.uid)  # duplicates dropped by the national run are not in the table
    print(f"national table {nat_path} (md5 {nat_md5}): {len(nat)} fields")

    regions = overlapping_regions(cfg)
    hits = []
    wc = np.zeros(len(deep), dtype=np.uint8)  # WorldCover class per deep pixel; 0 = no data
    for rid in regions:
        rdir = ROOT / "data" / "regions" / rid
        if (rdir / "worldcover.tif").exists():
            v, inside = sample(rdir / "worldcover.tif", xs, ys, crs)
            fill = inside & (wc == 0) & (v > 0)
            wc[fill] = v[fill]
        else:
            print(f"{rid}: no WorldCover raster")
        p = rdir / "fields_labels.tif"
        if not p.exists():
            print(f"{rid}: no field labels, skipped")
            continue
        nid, _ = sample(p, xs, ys, crs)
        nid = nid.astype(np.int64)
        on = nid > 0
        h = pd.DataFrame({"id": deep[on], "national_uid": [f"{rid}_{i}" for i in nid[on]]})
        hits.append(h[h.national_uid.isin(kept)])
        print(f"{rid}: {int(on.sum()):,} deep pixels on national fields")
    hits = pd.concat(hits, ignore_index=True) if hits else pd.DataFrame({"id": [], "national_uid": []})

    cnt = hits.groupby(["id", "national_uid"]).size().rename("px").reset_index()
    best = cnt.sort_values(["px", "national_uid"], ascending=[False, True]).drop_duplicates("id").set_index("id")
    out = ids[["id", "area_ha"]].copy()
    out["national_uid"] = out.id.map(best.national_uid)
    share = out.id.map(best.px).fillna(0) / out.id.map(deep_px)
    out["overlap_frac"] = share.round(4)
    out["matched"] = share >= MIN_OVERLAP  # the unrounded share
    flags = nat.set_index("uid")
    uid_m = out.national_uid.where(out.matched)

    # tree cover from each deep field's own pixels (no-data pixels count as not tree, as in region_pipeline)
    px = pd.DataFrame({"id": deep, "tree": wc == TREE, "wc": wc > 0}).groupby("id").agg(tree=("tree", "mean"),
                                                                                       wc=("wc", "mean"))
    own = out.id.map(px.tree).where(out.id.map(px.wc) > 0)
    out["tree_frac_national"] = uid_m.map(flags.tree_frac)
    out["tree_frac"] = own.round(6).fillna(out.tree_frac_national)  # 6 decimals keep the >= 0.3 test exact
    out["tree_frac_source"] = np.select([own.notna(), out.tree_frac_national.notna()], list(TREE_SRC), "")
    for f in SPRING:
        out[f] = uid_m.map(flags[f])
    out["spring_brown"] = tri(out.spring_brown)
    out = out[["id", "area_ha", "national_uid", "overlap_frac", "matched", "tree_frac", "tree_frac_source",
               "tree_frac_national", *SPRING]]
    csv_path = fd / "national_flags.csv"
    out.to_csv(csv_path, index=False)

    any_ov = set(hits.id)  # deep fields touching any national field
    m = out.matched.values
    ha = ids.area_ha.values
    no_ov = ~out.id.isin(any_ov).values
    src = out.tree_frac_source.replace("", "none").value_counts()
    meta = {"csv": rel(csv_path), "csv_md5": hashlib.md5(csv_path.read_bytes()).hexdigest(),
            "national_table": rel(nat_path), "national_table_md5": nat_md5, "national_fields": int(len(nat)),
            "fields": int(len(out)), "field_ha": round(float(ha.sum()), 1), "min_overlap": MIN_OVERLAP,
            "matched_fields": int(m.sum()), "matched_ha": round(float(ha[m].sum()), 1),
            "unmatched_fields": int((~m).sum()), "unmatched_ha": round(float(ha[~m].sum()), 1),
            "no_national_overlap_fields": int(no_ov.sum()), "no_national_overlap_ha": round(float(ha[no_ov].sum()), 1),
            "matched_spring_brown": {"brown": int(out.spring_brown.eq(True).sum()),
                                     "not_brown": int(out.spring_brown.eq(False).sum()),
                                     "no_clear_look": int((m & out.spring_brown.isna()).sum())},
            "tree_frac_source_codes": TREE_SRC,
            "tree_frac_source": {k: int(src.get(k, 0)) for k in (*TREE_SRC, "none")}}
    (fd / "national_flags.json").write_text(json.dumps(meta, indent=1))

    print(f"matched (>= {MIN_OVERLAP:.0%} of pixels in one national field): {m.sum():,} of {len(out):,} fields, "
          f"{ha[m].sum():,.0f} of {ha.sum():,.0f} ha")
    print(f"unmatched: {(~m).sum():,} fields, {ha[~m].sum():,.0f} ha; of these with no national overlap at all: "
          f"{no_ov.sum():,} fields, {ha[no_ov].sum():,.0f} ha")
    sb = meta["matched_spring_brown"]
    print(f"matched flags: spring_brown True {sb['brown']:,}, False {sb['not_brown']:,}, no clear look {sb['no_clear_look']:,}")
    nodata = int((wc == 0).sum())
    print(f"tree cover: {meta['tree_frac_source']} ({TREE_SRC}); deep pixels without WorldCover data: {nodata:,}; "
          f"tree_frac >= 0.3: {int((out.tree_frac >= 0.3).sum()):,} fields (matched fields by the national field's "
          f"value: {int((out.tree_frac_national >= 0.3).sum()):,}; by their own pixels: "
          f"{int((m & (out.tree_frac >= 0.3)).sum()):,})")
    print("wrote", csv_path, "and", fd / "national_flags.json")


if __name__ == "__main__":
    main()
