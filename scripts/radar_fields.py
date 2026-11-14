"""Per-field NISAR time series, radar-only activity classification, and Sentinel-2 validation.

Inputs
  data/fields/fields_labels.tif, data/fields/fields.csv     (from s2_fields.py)
  data/nisar/GCOV/*_HHHH.tif, *_HVHV.tif                     backscatter (gamma0, linear)
  data/nisar/GUNW/*_coherenceMagnitude.tif                   12-day coherence (0..1)
  data/nisar/SME2/*_soilMoisture.tif                         soil moisture (m3/m3)

Outputs
  data/fields/radar_timeseries.csv   field_id, date, layer, value
  data/fields/fields_radar.csv       per-field radar stats + radar winter/summer activity
  out/validation.json                radar vs Sentinel-2 agreement per season
  out/radar_preview.png

Radar rule (set from the data, not tuned to Sentinel-2):
  a field is "active" in a season if its seasonal peak HV backscatter (dB) is above
  an Otsu threshold computed over all fields, i.e. the natural break between
  crop canopy (volume scattering, high HV) and bare soil (low HV).
"""
import json
import re
from collections import defaultdict
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import rasterio
from rasterio.warp import Resampling, reproject
from scipy import ndimage as ndi
from skimage.filters import threshold_otsu

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "config.json").read_text())
FD = ROOT / "data" / "fields"
ND = ROOT / "data" / "nisar"


def season_of(date):
    for name, (s, e) in CFG["seasons"].items():
        if s <= date <= e:
            return name
    return None


def to_grid(path, ref, resampling):
    with rasterio.open(path) as src:
        out = np.full((ref.height, ref.width), np.nan, dtype="float32")
        reproject(rasterio.band(src, 1), out, src_nodata=src.nodata, dst_transform=ref.transform,
                  dst_crs=ref.crs, dst_nodata=np.nan, resampling=resampling)
    return out


def field_means(arr, labels, ids):
    ok = np.isfinite(arr) & (labels > 0)
    s = ndi.sum(np.where(ok, arr, 0), labels, ids)
    n = ndi.sum(ok, labels, ids)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(n > 0, s / n, np.nan)


def main():
    fields = pd.read_csv(FD / "fields.csv")
    ids = fields.id.values
    ref = rasterio.open(FD / "fields_labels.tif")
    labels = ref.read(1)

    rows = []
    layers = [("GCOV", "HHHH", Resampling.average), ("GCOV", "HVHV", Resampling.average),
              ("GUNW", "coherenceMagnitude", Resampling.bilinear), ("SME2", "soilMoisture", Resampling.bilinear)]
    for prod, layer, rs in layers:
        for p in sorted((ND / prod).glob(f"*_{layer}.tif")) if (ND / prod).exists() else []:
            date = p.name[:10]
            arr = to_grid(p, ref, rs)
            if layer in ("HHHH", "HVHV"):
                arr = np.where(arr > 0, arr, np.nan)
            else:  # coherence and soil moisture are 0..1; anything else is a fill value
                arr = np.where((arr >= 0) & (arr <= 1), arr, np.nan)
            vals = field_means(arr, labels, ids)
            if layer in ("HHHH", "HVHV"):
                vals = 10 * np.log10(vals)
            rows += [{"field_id": i, "date": date, "layer": layer, "value": float(v)} for i, v in zip(ids, vals)]
            print(f"{prod} {layer} {date}: {np.isfinite(vals).sum()} fields")
    ts = pd.DataFrame(rows)
    ts.to_csv(FD / "radar_timeseries.csv", index=False)

    ts["season"] = ts.date.map(season_of)
    hv_peak = ts[ts.layer == "HVHV"].dropna(subset=["season"]).groupby(["field_id", "season"]).value.max().unstack()
    coh_min = ts[ts.layer == "coherenceMagnitude"].dropna(subset=["season"]).groupby(["field_id", "season"]).value.min().unstack()
    sm_max = ts[ts.layer == "soilMoisture"].dropna(subset=["season"]).groupby(["field_id", "season"]).value.max().unstack()

    # Desert background: per-date median HV away from fields, and field-sized desert patches
    # to measure how high bare ground reaches by chance (sets the threshold; no Sentinel-2 input).
    far = ~ndi.binary_dilation(labels > 0, iterations=10)
    B = 16
    H, W = labels.shape
    hb, wb = H // B, W // B
    okp = far[:hb * B, :wb * B].reshape(hb, B, wb, B).all(axis=(1, 3))
    bg, patch, pdates = {}, [], []
    for p in sorted((ND / "GCOV").glob("*_HVHV.tif")):
        a = to_grid(p, ref, Resampling.average)
        a = np.where(a > 0, a, np.nan)
        d = p.name[:10]
        bg[d] = float(np.nanmedian(10 * np.log10(a[far])))
        with np.errstate(all="ignore"):
            bm = 10 * np.log10(np.nanmean(a[:hb * B, :wb * B].reshape(hb, B, wb, B), axis=(1, 3)))
        patch.append(bm[okp] - bg[d])
        pdates.append(d)
    patch = np.array(patch)
    pseason = np.array([season_of(d) for d in pdates])

    hvn = ts[ts.layer == "HVHV"].dropna(subset=["season"]).copy()
    hvn["norm"] = hvn.value - hvn.date.map(bg)
    hv_norm_peak = hvn.groupby(["field_id", "season"]).norm.max().unstack()

    thr = {}
    out = fields[["id", "lon", "lat", "area_ha", "circularity", "is_pivot", "s2_winter_active", "s2_summer_active"]].copy()
    for season in CFG["seasons"]:
        pk = patch[pseason == season].max(axis=0)
        p16, p50 = np.percentile(pk, [16, 50])
        thr[season] = float(p50 + 3 * (p50 - p16))
        out[f"hv_peak_db_{season}"] = out.id.map(hv_peak.get(season, pd.Series(dtype=float)))
        out[f"hv_above_desert_db_{season}"] = out.id.map(hv_norm_peak.get(season, pd.Series(dtype=float)))
        out[f"coh_min_{season}"] = out.id.map(coh_min.get(season, pd.Series(dtype=float))) if len(coh_min) else np.nan
        out[f"sm_max_{season}"] = out.id.map(sm_max.get(season, pd.Series(dtype=float))) if len(sm_max) else np.nan
        out[f"hv_{season}"] = out[f"hv_above_desert_db_{season}"] > thr[season]

    # Other witnesses, each with a threshold from field-sized bare-desert patches only:
    #   coherence: farmed if the field's lowest 12-day coherence falls below desert median - 3 sigma
    #   soil moisture: farmed if the field's wettest date exceeds desert median + 3 sigma
    def desert_patches(files, season_files):
        vals, seas = [], []
        for p in files:
            a = to_grid(p, ref, Resampling.bilinear)
            a = np.where((a >= 0) & (a <= 1), a, np.nan)
            if np.isnan(a).mean() > 0.5:
                continue
            with np.errstate(all="ignore"):
                vals.append(np.nanmean(a[:hb * B, :wb * B].reshape(hb, B, wb, B), axis=(1, 3))[okp])
            seas.append(season_of(p.name[:10]))
        return np.array(vals), np.array(seas)

    coh_thr, sm_thr = {}, {}
    coh_files = [p for p in sorted((ND / "GUNW").glob("*_coherenceMagnitude.tif")) if "__wrappedInterferogram" in p.name] \
        if (ND / "GUNW").exists() else []
    sm_files = sorted((ND / "SME2").glob("*_soilMoisture.tif")) if (ND / "SME2").exists() else []
    if coh_files:
        cp, cs = desert_patches(coh_files, None)
        for season in CFG["seasons"]:
            if (cs == season).sum():
                mn = np.nanmin(cp[cs == season], axis=0)
                p50, p84 = np.nanpercentile(mn, [50, 84])
                coh_thr[season] = float(p50 - 3 * (p84 - p50))
                out[f"coh_{season}"] = out[f"coh_min_{season}"] < coh_thr[season]
    if sm_files:
        sp, ss = desert_patches(sm_files, None)
        for season in CFG["seasons"]:
            if (ss == season).sum():
                mx = np.nanmax(sp[ss == season], axis=0)
                p16, p50 = np.nanpercentile(mx, [16, 50])
                sm_thr[season] = float(p50 + 3 * (p50 - p16))
                out[f"sm_{season}"] = out[f"sm_max_{season}"] > sm_thr[season]
    # Classifier used downstream: backscatter (the physical crop-canopy signal, best kappa).
    for season in CFG["seasons"]:
        out[f"{season}_active"] = out[f"hv_{season}"]

    for c in ("s2_winter_check", "s2_summer_check"):
        if c in fields:
            out[c] = fields[c].values
    out.to_csv(FD / "fields_radar.csv", index=False)
    (ROOT / "out").mkdir(exist_ok=True)
    (ROOT / "out" / "background.json").write_text(json.dumps({"bg_median_db": bg, "hv_threshold_db": thr, "coh_threshold": coh_thr, "sm_threshold": sm_thr}, indent=1))

    def agree(m, r, s):
        w = m.area_ha
        tp, tn = float(w[r & s].sum()), float(w[~r & ~s].sum())
        fp, fn = float(w[r & ~s].sum()), float(w[~r & s].sum())
        tot = tp + tn + fp + fn
        po = (tp + tn) / tot
        pe = ((tp + fp) * (tp + fn) + (fn + tn) * (fp + tn)) / tot ** 2
        return {"fields": int(len(m)), "area_agreement": round(po, 3), "kappa": round((po - pe) / (1 - pe), 3),
                "ha": {"both_active": round(tp), "both_inactive": round(tn), "radar_only": round(fp), "s2_only": round(fn)},
                "radar_active_ha": round(tp + fp), "s2_active_ha": round(tp + fn)}

    val = {"hv_threshold_db": {k: round(v, 2) for k, v in thr.items()},
           "coh_threshold": {k: round(v, 3) for k, v in coh_thr.items()},
           "sm_threshold": {k: round(v, 3) for k, v in sm_thr.items()},
           "rule": "farmed if the field's seasonal peak HV, measured against the bare-desert median of the same date, beats the desert noise level (median + 3 sigma of field-sized desert patches). No Sentinel-2 input.",
           "reference": "Sentinel-2 max NDVI > 0.40 over the same date windows as the radar"}
    for season in CFG["seasons"]:
        m = out.dropna(subset=[f"hv_peak_db_{season}"])
        ref_col = f"s2_{season}_check" if f"s2_{season}_check" in m else f"s2_{season}_active"
        s = m[ref_col].astype(bool)
        val[season] = agree(m, m[f"{season}_active"].astype(bool), s)
        wit = {"backscatter (used)": m[f"hv_{season}"].astype(bool)}
        if f"coh_{season}" in m:
            wit["coherence"] = m[f"coh_{season}"].astype(bool)
        if f"sm_{season}" in m:
            wit["soil moisture"] = m[f"sm_{season}"].astype(bool)
            wit["backscatter or soil moisture"] = m[f"hv_{season}"].astype(bool) | m[f"sm_{season}"].astype(bool)
        val[season]["by_witness"] = {k: {kk: agree(m, r, s)[kk] for kk in ("area_agreement", "kappa", "radar_active_ha")}
                                     for k, r in wit.items()}
    (ROOT / "out").mkdir(exist_ok=True)
    (ROOT / "out" / "validation.json").write_text(json.dumps(val, indent=2))
    print(json.dumps(val, indent=2))

    # Preview: HV time series for a few fields of each Sentinel-2 class
    fig, ax = plt.subplots(1, 2, figsize=(14, 5))
    hv = ts[ts.layer == "HVHV"].copy()
    hv["d"] = pd.to_datetime(hv.date)
    for (w_, s_), col in (((True, False), "tab:orange"), ((True, True), "tab:green"), ((False, True), "tab:blue")):
        pick = out[(out.s2_winter_active == w_) & (out.s2_summer_active == s_) & out.is_pivot].id.head(12)
        for i in pick:
            d = hv[hv.field_id == i].sort_values("d")
            ax[0].plot(d.d, d.value, color=col, alpha=0.5, lw=1)
    ax[0].set_title("NISAR HV per pivot (orange winter-only, green both, blue summer-only by Sentinel-2)")
    ax[0].set_ylabel("HV backscatter (dB)")
    for season, col in (("winter", "tab:orange"), ("summer", "tab:blue")):
        ax[1].hist(out[f"hv_above_desert_db_{season}"].dropna(), bins=60, alpha=0.5, color=col, label=season)
    [ax[1].axvline(t, ls="--", color="k") for t in thr.values()]; ax[1].legend(); ax[1].set_title("Seasonal peak HV above desert (dB) per field")
    fig.tight_layout()
    fig.savefig(ROOT / "out" / "radar_preview.png", dpi=100)


if __name__ == "__main__":
    main()
