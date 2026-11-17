"""Daily reference evapotranspiration (FAO-56 Penman-Monteith, grass) for each region from NASA POWER.

NASA POWER (power.larc.nasa.gov, community AG) gives daily 2 m air temperature max/min, relative humidity,
2 m wind speed, all-sky surface shortwave radiation and corrected precipitation from MERRA-2 / CERES at
~0.5 x 0.625 deg. It is requested at each region's centre (data/national/regions.json).

POWER describes the regional (mostly desert) air, not air over a well-watered reference crop, so it
overstates ETo in irrigated oases (the 'aridity' effect, FAO-56 Annex 6). ETo is computed two ways:
  eto_mm        RH-based actual vapour pressure (POWER as given)
  eto_adj_mm    FAO-56 Annex 6 style: dew point = Tmin - K0 (K0 = 2 C, arid/semi-arid), i.e. the humidity a
                reference site would have; the max/min temperatures are left unchanged
Downstream ET uses ETo_adj as the central case and the unadjusted value as an upper bound.

Outputs: data/national/power/<R>.json (raw API responses), data/national/eto_daily.csv
Usage: .venv/bin/python model/eto_power.py [R01 R02 ... | all]
"""
import json
import math
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "national"
START, END = "20250801", "20261130"      # covers the Landsat window (Aug 2025 - Nov 2026) around the season year
PARAMS = "T2M_MAX,T2M_MIN,RH2M,WS2M,ALLSKY_SFC_SW_DWN,PRECTOTCORR"
K0 = 2.0
SIGMA = 4.903e-9                         # MJ K-4 m-2 day-1


def fetch(rid, lat, lon):
    f = OUT / "power" / f"{rid}.json"
    if f.exists():
        return json.loads(f.read_text())
    url = (f"https://power.larc.nasa.gov/api/temporal/daily/point?parameters={PARAMS}&community=AG"
           f"&longitude={lon:.4f}&latitude={lat:.4f}&start={START}&end={END}&format=JSON")
    for attempt in range(5):
        try:
            d = json.load(urllib.request.urlopen(url, timeout=120))
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(d))
            return d
        except Exception as e:
            print(rid, "POWER retry", attempt + 1, repr(e)[:120], flush=True)
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"{rid}: NASA POWER request failed")


def esat(t):
    return 0.6108 * np.exp(17.27 * t / (t + 237.3))


def eto_fao56(df, lat, z):
    """FAO-56 eq. 6 with daily data; G = 0. Returns (eto_rh, eto_adj) in mm/day."""
    tx, tn, rh, u2, rs = df.T2M_MAX, df.T2M_MIN, df.RH2M, df.WS2M, df.ALLSKY_SFC_SW_DWN
    t = (tx + tn) / 2
    delta = 4098 * esat(t) / (t + 237.3) ** 2
    p = 101.3 * ((293 - 0.0065 * z) / 293) ** 5.26
    gamma = 0.000665 * p
    es = (esat(tx) + esat(tn)) / 2
    j = df.index.day_of_year.values
    phi = math.radians(lat)
    dr = 1 + 0.033 * np.cos(2 * np.pi * j / 365)
    dec = 0.409 * np.sin(2 * np.pi * j / 365 - 1.39)
    ws = np.arccos(-np.tan(phi) * np.tan(dec))
    ra = 24 * 60 / np.pi * 0.0820 * dr * (ws * np.sin(phi) * np.sin(dec) + np.cos(phi) * np.cos(dec) * np.sin(ws))
    rso = (0.75 + 2e-5 * z) * ra
    rns = (1 - 0.23) * rs
    out = []
    for ea in (rh / 100 * es, esat(tn - K0)):
        rnl = SIGMA * (((tx + 273.16) ** 4 + (tn + 273.16) ** 4) / 2) * (0.34 - 0.14 * np.sqrt(ea)) \
            * (1.35 * np.clip(rs / rso, 0.25, 1.0) - 0.35)
        rn = rns - rnl
        e = (0.408 * delta * rn + gamma * 900 / (t + 273) * u2 * (es - ea)) / (delta + gamma * (1 + 0.34 * u2))
        out.append(np.maximum(e, 0))
    return out


def main(rids):
    regions = {r["id"]: r for r in json.loads((OUT / "regions.json").read_text())}
    if rids in ([], ["all"]):
        rids = sorted(p.parent.name for p in (ROOT / "data" / "regions").glob("R*/fields_labels.tif"))
    rows = []
    for rid in rids:
        lat, lon = regions[rid]["center"]
        d = fetch(rid, lat, lon)
        z = float(d["geometry"]["coordinates"][2])
        par = d["properties"]["parameter"]
        df = pd.DataFrame({k: pd.Series(v) for k, v in par.items()})
        df.index = pd.to_datetime(df.index, format="%Y%m%d")
        df = df.replace(-999.0, np.nan).interpolate(limit=3)
        eto, eto_adj = eto_fao56(df, lat, z)
        r = pd.DataFrame({"region": rid, "date": df.index.strftime("%Y-%m-%d"), "tmax_c": df.T2M_MAX.round(2),
                          "tmin_c": df.T2M_MIN.round(2), "rh_pct": df.RH2M.round(1), "u2_ms": df.WS2M.round(2),
                          "rs_mj": df.ALLSKY_SFC_SW_DWN.round(2), "precip_mm": df.PRECTOTCORR.round(2),
                          "eto_mm": np.round(eto, 3), "eto_adj_mm": np.round(eto_adj, 3), "elev_m": round(z, 1)})
        rows.append(r)
        yr = r[(r.date >= "2025-11-01") & (r.date <= "2026-10-31")]
        print(f"{rid} lat {lat:.2f} z {z:.0f} m: ETo {yr.eto_mm.sum():.0f} mm/yr (adj {yr.eto_adj_mm.sum():.0f}), "
              f"rain {yr.precip_mm.sum():.0f} mm", flush=True)
    out = pd.concat(rows, ignore_index=True)
    out.to_csv(OUT / "eto_daily.csv", index=False)
    print("wrote", OUT / "eto_daily.csv", len(out), "rows")


if __name__ == "__main__":
    main(sys.argv[1:])
