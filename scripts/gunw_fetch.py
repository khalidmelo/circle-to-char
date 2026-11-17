"""Fetch the extra NISAR GUNW layers the InSAR pilot needs over the Qassim box.

scripts/nisar_fetch.py cropped only unwrappedPhase and coherenceMagnitude of the 14
GUNW pairs on track 42 / frame 15 (ascending) into data/nisar/GUNW, cast to float32,
without the secondary date. The ground-movement pilot (scripts/insar_qassim.py) also
needs the ionosphere screen, the unwrapping connected components, the validity mask,
the exact acquisition times, the radar wavelength and the line-of-sight geometry.

Method
  - Granules: ASF search (dataset NISAR, GUNW, Qassim bbox from config.json), kept to
    track 42 / frame 15. ASF holds 15 granules = 14 unique pairs plus a reprocessed _002
    copy of 2025-11-13 -> 2025-11-25; for duplicates the newest version (_NNN) is kept.
    GUNW is produced only as nearest-neighbour 12-day pairs (one 24-day pair where an
    acquisition is missing), so no pair bridges 2025-12-31 -> 2026-06-17.
  - Reads are HTTPS range requests through h5py on earthaccess/fsspec file objects
    (Earthdata login from ~/.netrc). Only the HDF5 chunks (512 x 512, gzip) that touch the
    box are transferred, a few tens of MB per 2.3 GB granule.
  - 80 m grid (frequencyA/unwrappedInterferogram), cropped with exactly the bbox rule of
    nisar_fetch.crop so the grid equals data/nisar/GUNW (632 x 818, EPSG:32638), but in
    the native dtypes:
        unwrappedPhase, coherenceMagnitude          float32, NaN fill (re-read from the
            same granule so every layer of a pair comes from one processing run; the
            connected components belong to one unwrapping)
        ionospherePhaseScreen, ...Uncertainty       float32 radians, NaN fill
        connectedComponents                         uint16, fill 65535 kept (0 = pixel
                                                    not assigned to a reliable component)
        mask                                        uint32, fill 255 kept. Bits 0-7 hold
            a 3-digit decimal subswath code (water flag, reference subswath, secondary
            subswath; 0 = invalid sample); bits 8-23 anomaly flags of the secondary and
            reference RSLC; bit 24 marks pixels where the ionosphere screen was
            interpolated. (BETA winter granules carry only the decimal code.)
  - radarGrid cubes (500 m posting, 20 heights): losUnitVectorX/Y (target -> sensor, ENU),
    incidenceAngle, wet and hydrostatic tropospheric phase screens and the slant-range
    solid-earth-tide phase. Sliced [k, rows, cols] (height axis first, the axis
    nisar_fetch.crop gets wrong) for heights 0-1500 m above WGS84, which bracket the
    Qassim terrain (GLO-90: 623-868 m) with one spare level on each side, plus 2 cells of
    margin round the box so interpolation at the box edge has neighbours. Saved as one
    multi-band GeoTIFF per cube (band i = height i, heights in the tags); the analysis
    interpolates them at the DEM height.
  - Scalars per pair (<ref>_<sec>_meta.json): reference/secondary zero-Doppler start
    times (dt_days comes from these; orbit/temporalBaseline is a truncated uint16),
    centerFrequency (wavelength = c / f), composite release id (CRID), ASF PGE version,
    product and spec versions, ISCE3 software version, looks, perpendicular baseline at
    the box centre.
  - DEM: Copernicus GLO-90 (Planetary Computer, cop-dem-glo-90) bilinearly resampled to
    the 80 m grid (dem_80m.tif, metres above the EGM2008 geoid). It is only used to pick
    the cube height; the geoid-ellipsoid separation in central Arabia is tens of metres,
    under 10% of the 500 m cube level spacing.

Outputs (data/nisar/gunw_insar/, gitignored through the data/nisar symlink; never
data/nisar/GUNW, which export_web.py and radar_fields.py glob):
  <ref>_<sec>_<layer>.tif   ref/sec = YYYYMMDD; tags ref, sec, dt_days, crid, pge, granule
  <ref>_<sec>_meta.json     scalars above plus the file list
  dem_80m.tif               terrain height on the 80 m grid
  power_ps_hourly.json      NASA POWER hourly surface pressure at the box centre (for the
                            independent sign check of the troposphere cube in insar_qassim.py)
  manifest.json             one entry per pair (rewritten after every granule)
Files are written to <name>.tmp and renamed, so an interrupted run never leaves a
truncated file; a pair whose meta.json and layers all exist is skipped unless --force.

Usage:
  .venv/bin/python scripts/gunw_fetch.py              # all 14 pairs (about 3-4 min each here)
  .venv/bin/python scripts/gunw_fetch.py --max 1      # first pair only (test)
  .venv/bin/python scripts/gunw_fetch.py --force      # refetch everything
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import earthaccess
import h5py
import numpy as np
import rasterio
import requests
from pyproj import Transformer
from rasterio.transform import from_origin

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import nisar_fetch as NF  # noqa: E402  helpers only (find_layers, sibling, epsg_of, CFG, ASF)

OUT = ROOT / "data" / "nisar" / "gunw_insar"
TRACK, FRAME = 42, 15
GUNW = "science/LSAR/GUNW/"
IDENT = "science/LSAR/identification/"
RGRID = GUNW + "metadata/radarGrid/"

# 80 m layers: name -> (regex for NF.find_layers, output dtype, nodata written to the GeoTIFF)
GRID_LAYERS = {
    "unwrappedPhase": (r"/unwrappedInterferogram/HH/unwrappedPhase$", "float32", np.nan),
    "coherenceMagnitude": (r"/unwrappedInterferogram/HH/coherenceMagnitude$", "float32", np.nan),
    "ionospherePhaseScreen": (r"/unwrappedInterferogram/HH/ionospherePhaseScreen$", "float32", np.nan),
    "ionospherePhaseScreenUncertainty": (r"/unwrappedInterferogram/HH/ionospherePhaseScreenUncertainty$", "float32", np.nan),
    "connectedComponents": (r"/unwrappedInterferogram/HH/connectedComponents$", "uint16", 65535),
    "mask": (r"/frequencyA/unwrappedInterferogram/mask$", "uint32", 255),
}
CUBES = ["losUnitVectorX", "losUnitVectorY", "incidenceAngle", "wetTroposphericPhaseScreen",
         "hydrostaticTroposphericPhaseScreen", "slantRangeSolidEarthTidesPhase"]
CUBE_HEIGHTS = (0.0, 500.0, 1000.0, 1500.0)  # m above WGS84; brackets the 623-868 m terrain
CUBE_MARGIN = 2  # cube cells (500 m) kept beyond the box on every side
EXPECTED_SHAPE = (632, 818)  # data/nisar/GUNW grid; a different crop means the bbox rule drifted
IDENT_KEYS = ["referenceZeroDopplerStartTime", "secondaryZeroDopplerStartTime", "compositeReleaseId",
              "productVersion", "productSpecificationVersion", "granuleId", "orbitPassDirection",
              "lookDirection", "processingDateTime", "trackNumber", "frameNumber"]


def list_pairs():
    """ASF GUNW granules on 42/15 over the box, one per (ref, sec) pair, newest version kept."""
    lon0, lat0, lon1, lat1 = NF.CFG["bbox"]
    params = {"dataset": "NISAR", "processingLevel": "GUNW", "maxResults": 500, "output": "geojson",
              "intersectsWith": f"POLYGON(({lon0} {lat0},{lon1} {lat0},{lon1} {lat1},{lon0} {lat1},{lon0} {lat0}))"}
    feats = requests.get(NF.ASF, params=params, timeout=120).json()["features"]
    best = {}
    for f in feats:
        p = f["properties"]
        if p.get("pathNumber") != TRACK or p.get("frameNumber") != FRAME:
            continue
        parts = p["fileName"].split("_")  # ..._<refStart>_<refEnd>_<secStart>_<secEnd>_<CRID>_N_F_J_<ver>.h5
        key = (parts[11][:8], parts[13][:8])
        rank = (int(re.sub(r"\D", "", parts[-1])), parts[15])  # version, then CRID
        if key not in best or rank > best[key]["rank"]:
            best[key] = {"ref": key[0], "sec": key[1], "url": p["url"], "file": p["fileName"],
                         "crid": p.get("crid", parts[15]), "pge": p.get("pgeVersion", ""),
                         "collection": p.get("collectionName", ""), "rank": rank}
    return [best[k] for k in sorted(best)]


def box_index(xs, ys, epsg):
    """Row/col slice of the bbox on a coordinate grid: the same rule as nisar_fetch.crop."""
    lon0, lat0, lon1, lat1 = NF.CFG["bbox"]
    tr = Transformer.from_crs(4326, epsg, always_xy=True)
    cx, cy = tr.transform([lon0, lon1, lon0, lon1], [lat0, lat0, lat1, lat1])
    xi = np.where((xs >= min(cx)) & (xs <= max(cx)))[0]
    yi = np.where((ys >= min(cy)) & (ys <= max(cy)))[0]
    return yi.min(), yi.max() + 1, xi.min(), xi.max() + 1


def grid_transform(xs, ys, r0, r1, c0, c1):
    """GeoTIFF transform from pixel-centre coordinates (north-up after an optional flip)."""
    dx, dy = float(xs[1] - xs[0]), float(ys[1] - ys[0])
    y_top = ys[r0] - dy / 2 if dy < 0 else ys[r1 - 1] + dy / 2
    return from_origin(xs[c0] - dx / 2, y_top, abs(dx), abs(dy)), dy > 0


def write_tif(arr, transform, epsg, path, nodata, tags):
    """Atomic GeoTIFF write (tmp file + rename); arr is (bands, h, w) or (h, w)."""
    arr = arr[None] if arr.ndim == 2 else arr
    tmp = path.with_name(path.name + ".tmp")
    with rasterio.open(tmp, "w", driver="GTiff", height=arr.shape[1], width=arr.shape[2], count=arr.shape[0],
                       dtype=arr.dtype.name, crs=f"EPSG:{epsg}", transform=transform, nodata=nodata,
                       compress="deflate", tiled=True) as dst:
        dst.write(arr)
        dst.update_tags(**{k: str(v) for k, v in tags.items()})
    os.replace(tmp, path)


def write_json(obj, path):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, allow_nan=False))
    os.replace(tmp, path)


def scalar(ds):
    v = ds[()]
    if isinstance(v, bytes):
        return v.decode()
    return v.item() if hasattr(v, "item") else v


def parse_time(s):
    return np.datetime64(s[:26])  # ISO with nanoseconds -> microsecond precision


def pair_files(g):
    stem = f"{g['ref']}_{g['sec']}"
    return {**{n: f"{stem}_{n}.tif" for n in list(GRID_LAYERS) + CUBES}, "meta": f"{stem}_meta.json"}


def fetch_pair(g, fobj):
    """Read every needed layer of one granule and write it under OUT; returns the meta dict."""
    t0 = time.time()
    files = pair_files(g)
    with h5py.File(fobj, "r") as h5:
        ident = {k: scalar(h5[IDENT + k]) for k in IDENT_KEYS if IDENT + k in h5}
        ref_t, sec_t = parse_time(ident["referenceZeroDopplerStartTime"]), parse_time(ident["secondaryZeroDopplerStartTime"])
        dt_days = float((sec_t - ref_t) / np.timedelta64(1, "s")) / 86400.0
        freq = float(scalar(h5[GUNW + "grids/frequencyA/centerFrequency"]))
        tags = {"ref": ident["referenceZeroDopplerStartTime"], "sec": ident["secondaryZeroDopplerStartTime"],
                "dt_days": round(dt_days, 6), "crid": ident.get("compositeReleaseId", g["crid"]), "pge": g["pge"],
                "granule": g["file"]}

        # 80 m layers, cropped by the nisar_fetch bbox rule, native dtypes
        grid_tf = None
        for name, (pattern, dtype, nodata) in GRID_LAYERS.items():
            hits = NF.find_layers(h5, re.compile(pattern))
            if len(hits) != 1:
                raise RuntimeError(f"{name}: expected one dataset, found {hits}")
            path = hits[0]
            xs, ys = h5[NF.sibling(h5, path, ["xCoordinates"])][()], h5[NF.sibling(h5, path, ["yCoordinates"])][()]
            epsg = NF.epsg_of(h5, path)
            r0, r1, c0, c1 = box_index(xs, ys, epsg)
            arr = h5[path][r0:r1, c0:c1]
            tf, flip = grid_transform(xs, ys, r0, r1, c0, c1)
            if flip:
                arr = arr[::-1]
            if arr.shape != EXPECTED_SHAPE:
                raise RuntimeError(f"{name}: crop {arr.shape} != {EXPECTED_SHAPE}")
            grid_tf = tf
            units = h5[path].attrs.get("units", b"")
            write_tif(np.ascontiguousarray(arr.astype(dtype)), tf, epsg, OUT / files[name], nodata,
                      {**tags, "layer": name, "units": units.decode() if isinstance(units, bytes) else str(units)})

        # radarGrid cubes: heights first, then the box (+ margin) on the 500 m grid
        cx, cy = h5[RGRID + "xCoordinates"][()], h5[RGRID + "yCoordinates"][()]
        hz = h5[RGRID + "heightAboveEllipsoid"][()]
        cepsg = NF.epsg_of(h5, RGRID + "losUnitVectorX")
        ks = [int(np.argmin(abs(hz - h))) for h in CUBE_HEIGHTS]
        if not np.allclose(hz[ks], CUBE_HEIGHTS) or ks != list(range(ks[0], ks[-1] + 1)):
            raise RuntimeError(f"cube heights {hz} do not contain {CUBE_HEIGHTS} contiguously")
        x0, y1 = grid_tf.c, grid_tf.f
        x1, y0 = x0 + EXPECTED_SHAPE[1] * grid_tf.a, y1 + EXPECTED_SHAPE[0] * grid_tf.e
        ci = np.where((cx >= x0) & (cx <= x1))[0]
        ri = np.where((cy >= y0) & (cy <= y1))[0]
        c0, c1 = max(ci.min() - CUBE_MARGIN, 0), min(ci.max() + 1 + CUBE_MARGIN, cx.size)
        r0, r1 = max(ri.min() - CUBE_MARGIN, 0), min(ri.max() + 1 + CUBE_MARGIN, cy.size)
        ctf, cflip = grid_transform(cx, cy, r0, r1, c0, c1)
        for name in CUBES:
            arr = h5[RGRID + name][ks[0]:ks[-1] + 1, r0:r1, c0:c1].astype("float32")
            if cflip:
                arr = arr[:, ::-1]
            write_tif(np.ascontiguousarray(arr), ctf, cepsg, OUT / files[name], np.nan,
                      {**tags, "layer": name, "heights_m": ",".join(f"{h:.0f}" for h in hz[ks]),
                       "height_datum": "WGS84 ellipsoid"})

        # perpendicular baseline at the box centre (only bottom and top cube levels are filled)
        ic, jc = int(np.argmin(abs(cx - (x0 + x1) / 2))), int(np.argmin(abs(cy - (y0 + y1) / 2)))
        bperp = [float(h5[RGRID + "perpendicularBaseline"][k, jc, ic]) for k in (0, hz.size - 1)]
        par = GUNW + "metadata/processingInformation/parameters/unwrappedInterferogram/frequencyA/"
        looks = {k: int(scalar(h5[par + k])) for k in ("numberOfAzimuthLooks", "numberOfRangeLooks") if par + k in h5}
        sw = GUNW + "metadata/processingInformation/algorithms/softwareVersion"
        meta = {"ref": g["ref"], "sec": g["sec"], "dt_days": round(dt_days, 6), "granule": g["file"], "url": g["url"],
                "collection": g["collection"], "crid": tags["crid"], "pge": g["pge"],
                "software_version": scalar(h5[sw]) if sw in h5 else None,
                "center_frequency_hz": freq, "wavelength_m": 299792458.0 / freq, **ident, **looks,
                "perpendicular_baseline_m_bottom_top": [round(b, 3) for b in bperp],
                "cube_heights_m": [float(h) for h in hz[ks]], "grid_transform": list(grid_tf)[:6],
                "grid_shape": list(EXPECTED_SHAPE), "epsg": int(cepsg), "files": files,
                "fetch_seconds": round(time.time() - t0, 1)}
    write_json(meta, OUT / files["meta"])
    return meta


def fetch_dem(transform, shape, epsg=32638):
    """Copernicus GLO-90 heights (EGM2008) bilinearly resampled onto the 80 m GUNW grid."""
    import planetary_computer
    import pystac_client
    from rasterio.enums import Resampling
    from rasterio.vrt import WarpedVRT

    cat = pystac_client.Client.open("https://planetarycomputer.microsoft.com/api/stac/v1",
                                    modifier=planetary_computer.sign_inplace)
    lon0, lat0, lon1, lat1 = NF.CFG["bbox"]
    items = list(cat.search(collections=["cop-dem-glo-90"], bbox=[lon0 - 0.05, lat0 - 0.05, lon1 + 0.05, lat1 + 0.05]).items())
    dem = np.full(shape, np.nan, "float32")
    for it in items:
        with rasterio.open(it.assets["data"].href) as src, WarpedVRT(
                src, crs=f"EPSG:{epsg}", transform=transform, width=shape[1], height=shape[0],
                resampling=Resampling.bilinear, src_nodata=src.nodata, nodata=np.nan) as vrt:
            a = vrt.read(1).astype("float32")
        dem = np.where(np.isnan(dem), a, dem)
    write_tif(dem, transform, epsg, OUT / "dem_80m.tif", np.nan,
              {"source": "Copernicus DEM GLO-90 (Planetary Computer cop-dem-glo-90)", "items": ",".join(i.id for i in items),
               "vertical_datum": "EGM2008 geoid (orthometric)", "resampling": "bilinear"})
    return dem


def fetch_pressure():
    """NASA POWER hourly surface pressure (MERRA-2, kPa, UTC) at the box centre.

    Used only for the sign check in insar_qassim.py: the hydrostatic troposphere cube must
    follow the surface-pressure change between the two dates (about 2.28 mm of zenith
    delay per hPa), which fixes the cube's sign convention independently of the spec.
    """
    lon0, lat0, lon1, lat1 = NF.CFG["bbox"]
    params = {"parameters": "PS", "community": "AG", "longitude": round((lon0 + lon1) / 2, 3),
              "latitude": round((lat0 + lat1) / 2, 3), "start": "20251101", "end": "20261031",
              "format": "JSON", "time-standard": "UTC"}
    r = requests.get("https://power.larc.nasa.gov/api/temporal/hourly/point", params=params, timeout=180)
    r.raise_for_status()
    js = r.json()
    write_json({"source": "NASA POWER hourly (MERRA-2), parameter PS, kPa, UTC hours YYYYMMDDHH",
                "point_lonlat_elev": js["geometry"]["coordinates"], "ps_kpa": js["properties"]["parameter"]["PS"]},
               OUT / "power_ps_hourly.json")
    return len(js["properties"]["parameter"]["PS"])


def complete(g):
    return all((OUT / f).exists() for f in pair_files(g).values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=0, help="fetch only the first N pairs")
    ap.add_argument("--force", action="store_true", help="refetch pairs that are already complete")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    pairs = list_pairs()
    if a.max:
        pairs = pairs[: a.max]
    print(f"{len(pairs)} unique GUNW pairs on {TRACK}/{FRAME}")
    earthaccess.login(strategy="netrc")
    manifest = {}
    mpath = OUT / "manifest.json"
    if mpath.exists():
        manifest = {f"{p['ref']}_{p['sec']}": p for p in json.loads(mpath.read_text())["pairs"]}

    for g in pairs:
        stem = f"{g['ref']}_{g['sec']}"
        if complete(g) and not a.force:
            meta = json.loads((OUT / pair_files(g)["meta"]).read_text())
            print(f"  {stem} cached ({meta['dt_days']:.2f} d, {meta['crid']})")
        else:
            for attempt in range(3):
                try:
                    fobj = earthaccess.open([g["url"]])[0]
                    meta = fetch_pair(g, fobj)
                    break
                except Exception as e:  # network hiccups on 2 GB remote files: retry twice
                    print(f"  {stem} attempt {attempt + 1} failed: {e}")
                    if attempt == 2:
                        raise
                    time.sleep(20 * (attempt + 1))
            print(f"  {stem} dt={meta['dt_days']:.2f} d {meta['crid']} lambda={meta['wavelength_m']:.5f} m "
                  f"bperp={meta['perpendicular_baseline_m_bottom_top'][0]:.1f} m in {meta['fetch_seconds']:.0f} s")
        manifest[stem] = {k: meta[k] for k in ("ref", "sec", "dt_days", "crid", "pge", "granule", "collection",
                                              "center_frequency_hz", "wavelength_m", "files")}
        write_json({"track": TRACK, "frame": FRAME, "bbox": NF.CFG["bbox"],
                    "pairs": [manifest[k] for k in sorted(manifest)]}, mpath)

    if not (OUT / "dem_80m.tif").exists():
        meta = json.loads((OUT / pair_files(pairs[0])["meta"]).read_text())
        dem = fetch_dem(rasterio.Affine(*meta["grid_transform"]), tuple(meta["grid_shape"]), meta["epsg"])
        print(f"  DEM 80 m: {np.nanmin(dem):.0f}-{np.nanmax(dem):.0f} m (median {np.nanmedian(dem):.0f})")
    if not (OUT / "power_ps_hourly.json").exists():
        print(f"  POWER hourly surface pressure: {fetch_pressure()} hours")


if __name__ == "__main__":
    main()
