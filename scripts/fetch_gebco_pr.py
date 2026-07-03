#!/usr/bin/env python3
"""Fetch real GEBCO bathymetry for the Puerto Rico extent via OpenTopography.

GEBCO is the OPTIONAL terrain-enrichment layer (see requirements-geo.txt and
federation.json's optional_terrain_layer) — it does not gate the federation
export contract. This script makes the layer available without the operator
manually downloading the full multi-GB global GEBCO grid:

  1. Pull the PR-extent subset (the hardcoded region in gebco/io.py:
     lat 17.92–18.65 N, lon −67.30 to −65.20 W) from OpenTopography's Global
     DEM API (demtype=GEBCOIceTopo — the GEBCO ice-surface elevation grid,
     real public bathymetry/topography) as GeoTIFF.
  2. Convert to the NetCDF layout gebco/io.py requires: an ``elevation``
     variable (int16, metres) on ascending ``lat``/``lon`` coordinates.
  3. Verify the result opens through gebco.io.open_gebco().

The API key is read from OpenTopography_API_KEY (or OPENTOPOGRAPHY_API_KEY).
Output default: data/gebco/gebco_pr_subset.nc (*.nc is git-ignored; the layer
is fetched, not committed). Point GEBCO_PATH at the output:

    python scripts/fetch_gebco_pr.py
    export GEBCO_PATH=data/gebco/gebco_pr_subset.nc
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# PR extent must match gebco/io.py's hardcoded subset bounds.
PR_LAT = (17.92, 18.65)
PR_LON = (-67.30, -65.20)
API_URL = "https://portal.opentopography.org/API/globaldem"
DEFAULT_OUT = REPO_ROOT / "data" / "gebco" / "gebco_pr_subset.nc"


def _api_key() -> str:
    for var in ("OpenTopography_API_KEY", "OPENTOPOGRAPHY_API_KEY"):
        key = os.environ.get(var, "").strip()
        if key:
            return key
    raise SystemExit("FAIL — OpenTopography_API_KEY is not set")


def fetch_geotiff(dest: Path, demtype: str = "GEBCOIceTopo") -> Path:
    import requests

    params = {
        "demtype": demtype,
        "south": PR_LAT[0],
        "north": PR_LAT[1],
        "west": PR_LON[0],
        "east": PR_LON[1],
        "outputFormat": "GTiff",
        "API_Key": _api_key(),
    }
    print(f"fetching {demtype} {PR_LAT} x {PR_LON} from OpenTopography...")
    resp = requests.get(API_URL, params=params, timeout=300)
    if resp.status_code != 200:
        raise SystemExit(f"FAIL — OpenTopography HTTP {resp.status_code}: {resp.text[:200]}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)
    print(f"wrote {dest} ({len(resp.content)} bytes)")
    return dest


def convert_to_gebco_netcdf(geotiff: Path, out_nc: Path) -> Path:
    """GeoTIFF -> NetCDF with the exact layout gebco/io.open_gebco requires."""
    import numpy as np
    import rioxarray  # noqa: F401 — registers the rio accessor
    import xarray as xr

    da = xr.open_dataarray(geotiff, engine="rasterio")
    da = da.squeeze("band", drop=True).rename({"x": "lon", "y": "lat"})
    da = da.sortby("lat")  # open_gebco expects ascending latitude
    da = da.astype(np.int16)
    da.name = "elevation"
    da.attrs.update({"units": "m", "long_name": "Elevation relative to sea level"})
    ds = da.to_dataset()
    # rioxarray attaches grid_mapping metadata pointing at a variable we drop;
    # strip it so plain netcdf4 consumers do not chase a missing reference.
    ds["elevation"].attrs.pop("grid_mapping", None)
    ds = ds.drop_vars("spatial_ref", errors="ignore")
    out_nc.parent.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(out_nc, engine="netcdf4")
    print(f"wrote {out_nc}")
    return out_nc


def verify(out_nc: Path) -> None:
    from gebco.io import GebcoIO, open_gebco

    ds = open_gebco(str(out_nc))
    assert "elevation" in ds
    lat0, lat1 = float(ds.lat.values[0]), float(ds.lat.values[-1])
    assert lat0 < lat1, "latitude must be ascending"
    gio = GebcoIO(path=str(out_nc))
    # Real sanity probes: deep water in the Puerto Rico Trench (north of PR),
    # land elevation in the Cordillera Central.
    trench = gio.depth_at(18.60, -66.50)
    cordillera = gio.depth_at(18.15, -66.59)
    print(f"verify: trench(18.60,-66.50)={trench} m, cordillera(18.15,-66.59)={cordillera} m")
    assert trench < -1000, f"expected deep water north of PR, got {trench}"
    assert cordillera > 0, f"expected land in the Cordillera Central, got {cordillera}"
    print("verify: open_gebco + depth_at OK")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Fetch the PR-extent GEBCO layer via OpenTopography.")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--demtype", default="GEBCOIceTopo")
    ap.add_argument("--keep-geotiff", action="store_true")
    args = ap.parse_args(argv)

    out_nc = Path(args.out)
    geotiff = out_nc.with_suffix(".tif")
    fetch_geotiff(geotiff, demtype=args.demtype)
    convert_to_gebco_netcdf(geotiff, out_nc)
    if not args.keep_geotiff:
        geotiff.unlink(missing_ok=True)
    verify(out_nc)
    print(f"GEBCO_PATH={out_nc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
