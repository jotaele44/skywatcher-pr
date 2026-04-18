import os
import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)

# Guard import of the DEM cache — the fetcher package may not be importable
# in isolated unit-test contexts or if dependencies are not installed.
try:
    from core.ingest.fetchers.copernicus_dem import get_cached_dem
    _DEM_IMPORT_OK = True
except Exception:
    _DEM_IMPORT_OK = False


def compute_elevation_proxy(df: pd.DataFrame) -> pd.DataFrame:
    """Compute elevation proxy from lat/lon.

    Priority:
      1. Real Copernicus GLO-30 DEM data (if the fetcher populated the cache
         during Step 1 ingestion) — vectorised nearest-neighbour lookup.
      2. Synthetic sinusoidal proxy (original behaviour) — used as fallback
         when no DEM cache is available, ensuring full backward compatibility.

    Adds: elevation_proxy (metres above sea level).
    """
    df = df.copy()

    lat = df['lat'].values.astype(float)
    lon = df['lon'].values.astype(float)

    # ── Attempt real DEM lookup ───────────────────────────────────────────────
    # Priority 1: module-level in-memory cache (populated within the same process)
    dem_df = None
    if _DEM_IMPORT_OK:
        try:
            dem_df = get_cached_dem()
        except Exception as exc:
            logger.debug(f"DEM cache lookup failed: {exc}")

    # Priority 2: load merged DEM from disk (populated by a previous subprocess)
    if (dem_df is None or len(dem_df) == 0):
        dem_disk_path = os.path.join(
            'data', 'raw', 'fetcher_cache', 'copernicus_dem', 'dem_merged.tif'
        )
        if os.path.exists(dem_disk_path):
            try:
                from core.ingest.loaders.raster_loader import load_raster
                dem_df = load_raster(dem_disk_path)
                if len(dem_df) > 0:
                    logger.info(f"elevation_proxy: loaded DEM from disk cache ({len(dem_df)} pts)")
                    # Re-populate module-level cache for subsequent calls in this process
                    if _DEM_IMPORT_OK:
                        try:
                            import core.ingest.fetchers.copernicus_dem as _dem_mod
                            _dem_mod._DEM_CACHE = dem_df.copy()
                        except Exception:
                            pass
            except Exception as exc:
                logger.debug(f"Could not load DEM from disk: {exc}")
                dem_df = None

    if dem_df is not None and len(dem_df) > 0:
        dem_lats = dem_df['lat'].values.astype(float)
        dem_lons = dem_df['lon'].values.astype(float)
        dem_vals = dem_df['raster_value'].values.astype(float)

        elevations = np.empty(len(lat), dtype=float)
        for i in range(len(lat)):
            dists2 = (dem_lats - lat[i]) ** 2 + (dem_lons - lon[i]) ** 2
            elevations[i] = dem_vals[int(np.argmin(dists2))]

        logger.info("elevation_proxy: using real Copernicus GLO-30 DEM data")

    else:
        # ── Synthetic fallback (original logic, unchanged) ────────────────────
        rng  = np.random.RandomState(42)
        noise = rng.normal(0.0, 50.0, len(lat))
        elevations = (
            np.abs(np.sin(np.radians(lat * 2.0))) * 500.0
            + np.cos(np.radians(lon)) * 100.0
            + noise
        )
        logger.info("elevation_proxy: using synthetic proxy (no DEM cache available)")

    df['elevation_proxy'] = elevations
    logger.info(
        f"Elevation proxy: mean={elevations.mean():.2f} m, "
        f"std={elevations.std():.2f} m"
    )
    return df


def compute_bathymetry_proxy(df: pd.DataFrame) -> pd.DataFrame:
    """Compute a synthetic bathymetry proxy (negative depth values).

    Adds: bathymetry_proxy (metres, negative = below sea level).
    """
    df = df.copy()

    lat = df['lat'].values.astype(float)
    lon = df['lon'].values.astype(float)

    bathy_proxy = -(
        np.abs(np.cos(np.radians(lat))) * 3000.0
        + np.sin(np.radians(lon * 1.5)) * 500.0
    )

    df['bathymetry_proxy'] = bathy_proxy
    logger.info(
        f"Bathymetry proxy: mean={bathy_proxy.mean():.2f} m, "
        f"min={bathy_proxy.min():.2f} m"
    )
    return df


def apply_terrain_constraints(df: pd.DataFrame) -> pd.DataFrame:
    """Apply terrain and bathymetry constraint columns to the DataFrame.

    Calls compute_elevation_proxy and compute_bathymetry_proxy, then stamps
    a boolean terrain_valid flag (elevation within plausible Earth range).
    """
    df = compute_elevation_proxy(df)
    df = compute_bathymetry_proxy(df)
    df['terrain_valid'] = (
        (df['elevation_proxy'] >= -500.0)
        & (df['elevation_proxy'] <= 8849.0)
    )
    logger.info(
        f"Terrain constraints: {df['terrain_valid'].sum()}/{len(df)} rows terrain_valid"
    )
    return df
