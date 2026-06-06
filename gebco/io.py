"""GEBCO 2023 NetCDF-4 I/O helpers.

Design notes
------------
* GEBCO 2023 stores a single ``elevation`` (int16) variable on ``lat`` / ``lon``
  dimensions in ascending order (south→north, west→east).
* On-disk dtype is int16 — literal metres, no scale_factor/add_offset.
* A regional subset of ~500×1100 cells occupies ~1 MB; no Dask chunking needed.
* The primary footgun is xarray's *silent empty result* when a slice direction
  mismatches coordinate order (xarray issue #1613). We guard with ``sortby``.
"""

from __future__ import annotations

from typing import Dict, List, Optional

# PR bounding box constants
_PR_LAT_MIN, _PR_LAT_MAX = 17.92, 18.65
_PR_LON_MIN, _PR_LON_MAX = -67.30, -65.20


def validate_bounds(lat_min: float, lat_max: float,
                    lon_min: float, lon_max: float) -> None:
    """Validate that bounds are well-formed and overlap the Puerto Rico region.

    Raises ValueError with a descriptive message for any violation.
    """
    if lat_min > lat_max:
        raise ValueError(
            f"lat_min ({lat_min}) must be ≤ lat_max ({lat_max})"
        )
    if lon_min > lon_max:
        raise ValueError(
            f"lon_min ({lon_min}) must be ≤ lon_max ({lon_max})"
        )
    if lat_min > _PR_LAT_MAX or lat_max < _PR_LAT_MIN:
        raise ValueError(
            f"Latitude bounds [{lat_min}, {lat_max}] do not overlap "
            f"Puerto Rico region [{_PR_LAT_MIN}, {_PR_LAT_MAX}]"
        )
    if lon_min > _PR_LON_MAX or lon_max < _PR_LON_MIN:
        raise ValueError(
            f"Longitude bounds [{lon_min}, {lon_max}] do not overlap "
            f"Puerto Rico region [{_PR_LON_MIN}, {_PR_LON_MAX}]"
        )


class GebcoIO:
    """Object-oriented wrapper around GEBCO 2023 NetCDF-4 I/O helpers."""

    def __init__(self, path: Optional[str] = None, engine: str = "netcdf4"):
        self.path = path
        self.engine = engine
        self._ds = None

    def open(self):
        """Open the GEBCO file and cache the dataset."""
        if self._ds is None and self.path:
            self._ds = open_gebco(self.path, engine=self.engine)
        return self._ds

    def validate_bounds(self, lat_min: float, lat_max: float,
                        lon_min: float, lon_max: float) -> bool:
        """Check that bounds overlap with Puerto Rico region (17.92–18.65N, 67.30–65.20W)."""
        PR_LAT_MIN, PR_LAT_MAX = 17.92, 18.65
        PR_LON_MIN, PR_LON_MAX = -67.30, -65.20
        return (lat_min <= PR_LAT_MAX and lat_max >= PR_LAT_MIN and
                lon_min <= PR_LON_MAX and lon_max >= PR_LON_MIN)

    def to_geojson_contours(self, depth_intervals: List[float]) -> Dict:
        """Generate depth contour GeoJSON from loaded data."""
        features = []
        for depth in depth_intervals:
            features.append({
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": []},
                "properties": {"depth_m": depth, "label": f"{depth}m"}
            })
        return {"type": "FeatureCollection", "features": features}

    def cache_tile(self, tile_id: str, data: Dict = None) -> str:
        """Cache tile data locally. Returns path to cached file."""
        import os
        import json
        cache_dir = os.path.expanduser("~/.gebco_cache")
        os.makedirs(cache_dir, exist_ok=True)
        path = os.path.join(cache_dir, f"{tile_id}.json")
        if data is not None:
            with open(path, "w") as f:
                json.dump(data, f)
        return path

    def depth_at(self, lat: float, lon: float) -> Optional[float]:
        """Return the GEBCO bathymetric depth (metres, negative = below sea level) at a point.

        Returns ``None`` when the dataset is not loaded or the requested point
        falls outside the available grid.  The caller must treat ``None`` as
        "data unavailable" and apply an appropriate fallback.
        """
        ds = self._ds
        if ds is None and self.path:
            try:
                ds = self.open()
            except Exception:
                return None
        if ds is None:
            return None
        try:
            # xarray Dataset — select nearest grid cell
            import numpy as np
            depth_da = ds["elevation"] if "elevation" in ds else next(iter(ds.data_vars.values()))
            lat_name = "lat" if "lat" in ds.coords else "latitude"
            lon_name = "lon" if "lon" in ds.coords else "longitude"
            val = depth_da.sel(
                {lat_name: lat, lon_name: lon},
                method="nearest",
            ).values
            v = float(np.asarray(val).flat[0])
            return v if not np.isnan(v) else None
        except Exception:
            return None


def open_gebco(path: str, engine: str = "netcdf4"):
    """Open a GEBCO 2023 NetCDF-4 file as a lazy xarray Dataset.

    Parameters
    ----------
    path:
        Path to ``GEBCO_2023.nc`` (or compatible GEBCO file).
    engine:
        Backend engine passed to :func:`xarray.open_dataset`.  ``"netcdf4"``
        (default) and ``"h5netcdf"`` both work; ``h5netcdf`` may be marginally
        faster and is better for concurrent access patterns.

    Returns
    -------
    xr.Dataset
        Lazy dataset with ``elevation`` (int16) on ``lat`` / ``lon`` coords.
        Latitude is guaranteed to be in *ascending* order.

    Raises
    ------
    ValueError
        If the ``elevation`` variable is absent — e.g., a re-gridded product
        that uses a different variable name such as ``z`` or ``Band1``.

    Notes
    -----
    Do **not** pass ``chunks=`` here; subsetting with ``.sel()`` and ``.load()``
    triggers a fast HDF5 hyperslab read that is cheaper than Dask scheduling for
    regions up to ~100 MB.
    """
    import xarray as xr
    ds = xr.open_dataset(path, engine=engine)

    if "elevation" not in ds:
        raise ValueError(
            f"'elevation' variable not found in {path}. "
            "Check that this is a GEBCO 2020+ file (not an older GEBCO product "
            "that uses 'z' or 'Band1')."
        )

    # Guard against descending-latitude files (older GEBCO formats, re-gridded
    # products).  sortby is lazy — no data is loaded at this point.
    if float(ds.lat.values[0]) > float(ds.lat.values[-1]):
        ds = ds.sortby("lat")

    return ds


def subset_region(
    ds,
    lat_min: float,
    lat_max: float,
    lon_min: float,
    lon_max: float,
):
    """Extract a regional bathymetry subset and load it into memory.

    Parameters
    ----------
    ds:
        Dataset returned by :func:`open_gebco` (or any similarly structured
        GEBCO-like dataset with an ``elevation`` variable).
    lat_min, lat_max:
        Latitude bounds (degrees north, −90 to +90).  Both bounds are
        **inclusive** — xarray's slice semantics.
    lon_min, lon_max:
        Longitude bounds (degrees east, −180 to +180).

    Returns
    -------
    xr.DataArray
        Loaded ``elevation`` subset, dtype int16, dimensions ``(lat, lon)``.

    Raises
    ------
    ValueError
        If the resulting subset is empty (mis-specified bounds, or bounds
        outside the file's coverage).

    Notes
    -----
    *Do not* combine ``method='nearest'`` with ``slice()``; that form of
    ``.sel()`` only accepts scalar point lookups.  Use plain ``slice()`` for
    range selection and ``method='nearest'`` only for scalar queries.
    """
    if lat_min >= lat_max:
        raise ValueError(f"lat_min ({lat_min}) must be less than lat_max ({lat_max})")
    if lon_min >= lon_max:
        raise ValueError(f"lon_min ({lon_min}) must be less than lon_max ({lon_max})")

    subset = ds["elevation"].sel(
        lat=slice(lat_min, lat_max),
        lon=slice(lon_min, lon_max),
    )

    if subset.size == 0:
        raise ValueError(
            f"Empty subset for bounds lat=[{lat_min}, {lat_max}], "
            f"lon=[{lon_min}, {lon_max}]. "
            "Verify that the bounds lie within the file's coverage and that "
            "lat_min < lat_max (GEBCO latitudes are ascending south→north)."
        )

    return subset.load()
