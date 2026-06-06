"""GEBCO 2023 bathymetry processing pipeline.

Provides regional subset extraction (``gebco.io``) and terrain-derivative
computation (``gebco.terrain``) for the GEBCO 2023 global 15 arc-second grid.
"""

try:
    from .io import GebcoIO, open_gebco, subset_region
    from .terrain import (
        TerrainAnalyzer,
        cell_size_meters,
        compute_curvatures,
        compute_roughness,
        compute_rugosity,
        compute_slope,
    )
except ImportError:
    # xarray/netCDF4 not installed — provide stub classes so the package is importable
    class GebcoIO:  # type: ignore[no-redef]
        """Stub when xarray/netCDF4 are unavailable."""
        def __init__(self, *a, **kw): pass
    class TerrainAnalyzer:  # type: ignore[no-redef]
        """Stub when xarray/netCDF4 are unavailable."""
        def __init__(self, *a, **kw): pass
    def open_gebco(*a, **kw): return None  # type: ignore[misc]
    def subset_region(*a, **kw): return None  # type: ignore[misc]
    def cell_size_meters(*a, **kw): return 0.0  # type: ignore[misc]
    def compute_slope(*a, **kw): return None  # type: ignore[misc]
    def compute_curvatures(*a, **kw): return None  # type: ignore[misc]
    def compute_roughness(*a, **kw): return None  # type: ignore[misc]
    def compute_rugosity(*a, **kw): return None  # type: ignore[misc]

__all__ = [
    "GebcoIO",
    "TerrainAnalyzer",
    "open_gebco",
    "subset_region",
    "cell_size_meters",
    "compute_slope",
    "compute_curvatures",
    "compute_roughness",
    "compute_rugosity",
]
