"""Per-field Landsat samples per overpass (v2): corrected surface temperature by distance from the field edge,
40 m NDVI, and hot/cold reference statistics with quality checks.

Inputs  data/landsat/<R>/<stem>_t.tif (120 m) and <stem>_o.tif (40 m) from scripts/landsat_c2.py,
        data/regions/<R>/fields_labels.tif, data/national/eto_daily.csv (NASA POWER), a Copernicus DEM read once.

Thermal (120 m). A 120 m pixel is a field pixel only if all 3 x 3 label pixels in it are the same field. Its
distance d to the nearest non-field 40 m pixel decides its edge band: <120 m (dropped), 120-160, 160-200, 200-280,
>=280 m. Landsat's thermal band is 100 m with a wider point-spread, so pixels near a hot desert edge read warm;
et_fields.py fits and removes that per region and season from these bands.
  Emissivity: the C2 ST product's emissivity (ASTER GED based) is ~0.95-0.96 over full-cover crops where
  ~0.98-0.99 is physical. Field pixels are re-solved with eps = eps_soil(1-fc) + 0.99 fc, fc = clip((NDVI-0.15)/0.65,0,1),
  eps_soil = the scene's desert median, keeping surface-leaving radiance fixed:
  B(T_new) = [eps_old B(T_old) + (eps_new - eps_old) drad] / eps_new   (OpenET-style C2 LST correction).
  Elevation: Ts + 0.0065 (z - z_fields_median) (dry adiabatic-ish lapse, as SSEBop).
Optical (40 m). Field NDVI = median over interior pixels (3x3 neighbourhood all the same field), used only when
at least half of them are clear; small fields with < 5 interior pixels use all their clear pixels (edge flag).

Anchors per overpass (all on corrected Ts):
  cold  median Ts of field pixels with d >= 200 m and NDVI >= 0.75 (>= 30 px): well-watered full cover, ETf = 1
  hot   median Ts of field pixels (d >= 120 m) with NDVI < 0.15 now AND at their previous clear look (fallow, not
        just ploughed or irrigated bare soil), >= 50 px; also the desert median for a fallback offset
  QC    hot p10-p90 spread, cold/hot counts, dT_obs vs SSEBop dT = Rn_clear * 110 / (rho * Cp), rain in last 5 days

Outputs data/regions/<R>/landsat_thermal.csv.gz, landsat_ndvi.csv.gz, landsat_anchors.csv, landsat_fieldinfo.csv
Usage: .venv/bin/python scripts/landsat_fields.py R04 [R05 ...] | all
"""
import math
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import planetary_computer
import pystac_client
import rasterio
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT
from scipy import ndimage as ndi

ROOT = Path(__file__).resolve().parents[1]
S = 3
NODATA = -32768
BANDS = [(120, 160), (160, 200), (200, 280), (280, 1e9)]
K12 = {"L8": (774.8853, 1321.0789), "L9": (799.0284, 1329.2405)}
EPS_VEG = 0.99
LAPSE = 0.0065
PERSIST = 0.5        # share of a pixel's looks flagged not-clear above which the flag is a bright-surface false alarm
SCENE_CLEAR = 0.8    # ...overridden only on scenes whose other pixels are at least this clear
MASK_AEROSOL = os.environ.get('V2_MASK_AEROSOL', '0') == '1'   # NDVI only; off by default (see landsat_c2.py)


def blocks(a, fill=0):
    h, w = a.shape
    H, W = -(-h // S), -(-w // S)
    p = np.full((H * S, W * S), fill, a.dtype)
    p[:h, :w] = a
    return p.reshape(H, S, W, S).transpose(0, 2, 1, 3).reshape(H, W, S * S)


def dem120(rid, crs, tf, w, h):
    f = ROOT / "data" / "landsat" / rid / "dem_120.tif"
    if f.exists():
        return rasterio.open(f).read(1).astype(np.float32)
    cat = pystac_client.Client.open("https://planetarycomputer.microsoft.com/api/stac/v1")
    import json
    bbox = json.loads((ROOT / "data" / "regions" / rid / "meta.json").read_text())["bbox"]
    items = list(cat.search(collections=["cop-dem-glo-90"], bbox=bbox).items())
    z = np.full((h, w), np.nan, np.float32)
    for it in items:   # one 1-degree tile each; outside a tile's extent the warp must be no-data, not 0
        with rasterio.open(planetary_computer.sign(it.assets["data"].href)) as src, \
                WarpedVRT(src, crs=crs, transform=tf, width=w, height=h, resampling=Resampling.average,
                          src_nodata=src.nodata if src.nodata is not None else -32767.0, nodata=np.nan, dtype="float32") as vrt:
            a = vrt.read(1).astype(np.float32)
        a[a <= -100] = np.nan
        z = np.where(np.isfinite(z), z, a)
    gap = ~np.isfinite(z)
    if gap.all():
        raise RuntimeError(f"{rid}: no DEM cells")
    if gap.any():   # open sea (no tile) or voids: copy the nearest valid height (none of these cells are fields)
        idx = ndi.distance_transform_edt(gap, return_distances=False, return_indices=True)
        z = z[tuple(idx)]
    with rasterio.open(f, "w", driver="GTiff", dtype="float32", count=1, width=w, height=h, crs=crs, transform=tf,
                       nodata=np.nan, compress="deflate") as dst:
        dst.write(z, 1)
    return z


def ssebop_dt(row, lat):
    """SSEBop dT (K) from clear-sky net radiation: dT = Rn * rah / (rho_a * Cp), rah = 110 s/m."""
    tx, tn, z = row.tmax_c, row.tmin_c, row.elev_m
    j = pd.Timestamp(row.date).day_of_year
    phi = math.radians(lat)
    dr = 1 + 0.033 * math.cos(2 * math.pi * j / 365)
    dec = 0.409 * math.sin(2 * math.pi * j / 365 - 1.39)
    ws = math.acos(-math.tan(phi) * math.tan(dec))
    ra = 24 * 60 / math.pi * 0.0820 * dr * (ws * math.sin(phi) * math.sin(dec) + math.cos(phi) * math.cos(dec) * math.sin(ws))
    rso = (0.75 + 2e-5 * z) * ra
    ea = 0.6108 * math.exp(17.27 * tn / (tn + 237.3))
    rnl = 4.903e-9 * (((tx + 273.16) ** 4 + (tn + 273.16) ** 4) / 2) * (0.34 - 0.14 * math.sqrt(ea)) * (1.35 * 1.0 - 0.35)
    rn = (0.77 * rso - rnl) * 1e6 / 86400            # W m-2, daily mean
    p = 101.3 * ((293 - 0.0065 * z) / 293) ** 5.26
    rho = 3.486 * p / (1.01 * ((tx + tn) / 2 + 273.16))
    return rn * 110 / (rho * 1013.0)


def run(rid):
    R = ROOT / "data" / "regions" / rid
    L = ROOT / "data" / "landsat" / rid
    tfiles = sorted(L.glob("*_t.tif")) if L.exists() else []
    if not tfiles:
        print(rid, "no Landsat cache; skipped", flush=True)
        return
    with rasterio.open(R / "fields_labels.tif") as src:
        lab, crs, tf40 = src.read(1), src.crs, src.transform
    with rasterio.open(tfiles[0]) as src:
        tf120, W, H = src.transform, src.width, src.height
    # --- static geometry
    dist40 = ndi.distance_transform_edt(lab > 0) * abs(tf40.a)          # m to nearest non-field pixel
    b = blocks(lab)
    core = np.where((b == b[..., :1]).all(-1) & (b[..., 0] > 0), b[..., 0], 0)
    dcen = blocks(dist40.astype(np.float32), 0)[..., 4]                 # block centre (pixel 1,1)
    band = np.zeros(core.shape, np.int8)
    for k, (lo, hi) in enumerate(BANDS, start=1):
        band[(core > 0) & (dcen >= lo) & (dcen < hi)] = k
    anyfield = (b > 0).any(-1)
    desert = ~anyfield & (ndi.distance_transform_edt(~anyfield) >= 4)
    ids_all = np.unique(lab[lab > 0])
    interior40 = (ndi.minimum_filter(lab, 3) == ndi.maximum_filter(lab, 3)) & (lab > 0)
    n_int = pd.Series(ndi.sum(interior40, lab, ids_all), index=ids_all).astype(int)
    n_all = pd.Series(ndi.sum(lab > 0, lab, ids_all), index=ids_all).astype(int)
    small = n_int < 5
    lab_int = np.where(interior40, lab, 0)
    lab_small = np.where(np.isin(lab, ids_all[small.values]), lab, 0)
    z = dem120(rid, crs, tf120, W, H)
    zref = float(np.nanmedian(z[core > 0])) if (core > 0).any() else float(np.nanmedian(z))
    dz = np.where(np.isfinite(z), z - zref, 0.0)
    info = pd.DataFrame({"id": ids_all, "px40": n_all.values, "int40": n_int.values})
    for k in range(1, len(BANDS) + 1):
        info[f"core_b{k}"] = pd.Series(ndi.sum(band == k, core, ids_all), index=ids_all).astype(int).values
    info["z_m"] = np.round(pd.Series(ndi.mean(np.where(core > 0, z, 0), core, ids_all), index=ids_all).values, 1)
    info.to_csv(R / "landsat_fieldinfo.csv", index=False)
    # --- weather for QC
    import json
    reg = {r["id"]: r for r in json.loads((ROOT / "data" / "national" / "regions.json").read_text())}
    lat = reg[rid]["center"][0]
    wx = pd.read_csv(ROOT / "data" / "national" / "eto_daily.csv")
    wx = wx[wx.region == rid].set_index("date")
    # Persistent false cloud: CFMask flags bright salt flats, sand and gravel as cloud on most dates. A 40 m pixel
    # flagged not-clear in >= PERSIST of its looks is a bright-surface false alarm (real cloud is nowhere near that
    # frequent over these farm belts); on a scene whose other pixels are >= SCENE_CLEAR clear it is treated as clear.
    nflag = np.zeros(lab.shape, np.int32); nval = np.zeros(lab.shape, np.int32)
    for f in tfiles:
        with rasterio.open(L / f"{f.name[:-6]}_o.tif") as src:
            nd_, c = src.read(1), src.read(2)
        v_ = (c >= 0) & (nd_ > NODATA)          # data present (outside a scene's footprint is not a look)
        nflag += v_ & (c == 0); nval += v_
    persist = (nval >= 10) & (nflag >= PERSIST * np.maximum(nval, 1))
    persist_share = float(persist[lab > 0].mean()) if (lab > 0).any() else 0.0
    last_nd = np.full(core.shape, np.nan, np.float32)
    trows, nrows, anchors = [], [], []
    for f in tfiles:
        stem = f.name[:-6]
        d, sensor, path = stem.split("_")
        date = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        with rasterio.open(f) as src:
            t, tags = src.read(), src.tags()
        with rasterio.open(L / f"{stem}_o.tif") as src:
            o = src.read()
        # ---- optical 40 m
        nd40 = np.where(o[0] > NODATA, o[0] / 1e4, np.nan)
        valid40 = (o[1] >= 0) & np.isfinite(nd40)
        other = valid40 & ~persist
        scene_clear = float((o[1][other] == 1).mean()) if other.any() else 0.0
        clear40 = (o[1] == 1) | (persist & valid40 & (scene_clear >= SCENE_CLEAR))
        c40 = clear40 & np.isfinite(nd40)
        if MASK_AEROSOL and o.shape[0] > 2:
            c40 &= o[2] != 1
        ci = ndi.sum(c40 & interior40, lab_int, ids_all)
        with np.errstate(all="ignore"):
            med = ndi.median(np.where(c40, nd40, np.nan), np.where(c40, lab_int, 0), ids_all)
            meds = ndi.mean(np.where(c40, nd40, 0), np.where(c40, lab_small, 0), ids_all)
        med = np.where(ci >= 0.5 * np.maximum(n_int.values, 1), med, np.nan)
        cs = ndi.sum(c40 & (lab_small > 0), lab_small, ids_all)
        use_small = small.values & (cs >= 0.5 * n_all.values)
        nd_f = np.where(small.values, np.where(use_small, meds, np.nan), med)
        ok = np.isfinite(nd_f)
        nrows.append(pd.DataFrame({"id": ids_all[ok], "date": date, "sensor": sensor, "path": int(path),
                                   "ndvi": np.round(nd_f[ok], 4), "edge": small.values[ok].astype(int)}))
        # ---- thermal 120 m
        st = np.where(t[0] > NODATA, t[0] / 100.0 + 200.0, np.nan)
        eps = np.where(t[1] > NODATA, t[1] / 1e4, np.nan)
        nd = np.where(t[2] > NODATA, t[2] / 1e4, np.nan)
        c9 = blocks(clear40.astype(np.int8), 0)
        nc9 = blocks((valid40 & ~clear40).astype(np.int8), 0)
        clear = (c9.min(-1) == 1) & np.isfinite(st) & np.isfinite(nd) & np.isfinite(eps)
        clear &= ~ndi.binary_dilation(nc9.max(-1) == 1, iterations=1)
        drad = float(tags.get("drad", "nan"))
        if not clear.any() or not np.isfinite(drad):
            continue
        dsel = desert & clear & (nd < 0.15)
        eps_soil = float(np.median(eps[dsel])) if dsel.sum() > 100 else float(np.nanmedian(eps[clear]))
        K1, K2 = K12[sensor]
        fc = np.clip((nd - 0.15) / 0.65, 0, 1)
        eps_new = eps_soil * (1 - fc) + EPS_VEG * fc
        with np.errstate(all="ignore"):
            B = K1 / (np.exp(K2 / st) - 1)
            Bn = (eps * B + (eps_new - eps) * drad) / eps_new
            st_c = K2 / np.log(K1 / Bn + 1)
        fieldpx = core > 0
        tsc = np.where(fieldpx, st_c, st) + LAPSE * dz
        good = clear & np.isfinite(tsc)
        fp = good & (band > 0)
        # anchors
        cold = good & (band >= 3) & (nd >= 0.75)
        hotm = good & (band > 0) & (nd < 0.15) & (last_nd < 0.15)
        tc = float(np.median(tsc[cold])) if cold.sum() >= 30 else np.nan
        th = float(np.median(tsc[hotm])) if hotm.sum() >= 50 else np.nan
        hp10, hp90 = (np.percentile(tsc[hotm], [10, 90]) if hotm.sum() >= 50 else (np.nan, np.nan))
        des = float(np.median(tsc[dsel])) if dsel.sum() >= 200 else np.nan
        w_ = wx.loc[date] if date in wx.index else None
        tmax_k = float(w_.tmax_c) + 273.15 if w_ is not None else np.nan
        dts = ssebop_dt(w_.reset_index() if False else pd.Series({**w_.to_dict(), "date": date}), lat) if w_ is not None else np.nan
        rain5 = float(wx.loc[(wx.index > str(pd.Timestamp(date) - pd.Timedelta(days=5))[:10]) & (wx.index <= date), "precip_mm"].sum()) if w_ is not None else np.nan
        # edge-band profile on large full-cover fields (for the mixing fit in et_fields.py)
        prof = {}
        fc_px = good & (nd >= 0.65)
        for k in range(1, len(BANDS) + 1):
            s = fc_px & (band == k)
            prof[f"fc_ts_b{k}"] = float(np.median(tsc[s])) if s.sum() >= 30 else np.nan
            prof[f"fc_n_b{k}"] = int(s.sum())
        anchors.append({"date": date, "sensor": sensor, "path": int(path), "clear_frac": round(float(clear.mean()), 4),
                        "tc": tc, "n_cold": int(cold.sum()), "th": th, "n_hot": int(hotm.sum()),
                        "hot_p10": float(hp10), "hot_p90": float(hp90), "desert_ts": des, "n_desert": int(dsel.sum()),
                        "eps_soil": eps_soil, "drad": drad, "tmax_k": tmax_k, "dt_ssebop": dts, "rain5_mm": rain5,
                        "field_px_clear": int(fp.sum()), **prof})
        # per-field band sums
        rec = {"id": ids_all}
        any_n = np.zeros(len(ids_all))
        for k in range(1, len(BANDS) + 1):
            m = fp & (band == k)
            n = ndi.sum(m, core, ids_all)
            with np.errstate(all="ignore"):
                rec[f"ts_b{k}"] = np.round(ndi.sum(np.where(m, tsc, 0), core, ids_all) / n, 2)
            rec[f"n_b{k}"] = n.astype(int)
            any_n += n
        m = fp
        with np.errstate(all="ignore"):
            rec["ndvi120"] = np.round(ndi.sum(np.where(m, nd, 0), core, ids_all) / np.maximum(any_n, 1), 4)
        df = pd.DataFrame(rec)
        df = df[any_n > 0]
        df.insert(1, "date", date); df.insert(2, "sensor", sensor); df.insert(3, "path", int(path))
        trows.append(df)
        last_nd = np.where(clear, nd, last_nd)
    th_df = pd.concat(trows, ignore_index=True) if trows else pd.DataFrame()
    th_df.to_csv(R / "landsat_thermal.csv.gz", index=False)
    pd.concat(nrows, ignore_index=True).to_csv(R / "landsat_ndvi.csv.gz", index=False)
    an = pd.DataFrame(anchors).round(4)
    an.to_csv(R / "landsat_anchors.csv", index=False)
    print(rid, f"{len(tfiles)} overpasses; thermal rows {len(th_df)}; fields with core px {int((info[[f'core_b{k}' for k in range(1, 5)]].sum(1) > 0).sum())}/{len(info)}; "
               f"persistent false cloud {persist_share:.1%} of field px; cold ok {an.tc.notna().sum()}, hot ok {an.th.notna().sum()}; z_ref {zref:.0f} m, z range {np.nanmin(z):.0f}-{np.nanmax(z):.0f}", flush=True)


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["all"]:
        args = sorted(p.name for p in (ROOT / "data" / "landsat").glob("R*") if any(p.glob("*_t.tif")))
    for rid in args:
        try:
            run(rid)
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(rid, "ERROR", repr(e)[:300], flush=True)
