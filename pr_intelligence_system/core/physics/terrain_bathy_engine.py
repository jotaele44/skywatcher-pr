import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)


def compute_elevation_proxy(df: pd.DataFrame) -> pd.DataFrame:
    """Compute a synthetic elevation proxy from lat/lon coordinates.

    In production this module would read actual DEM/bathymetry rasters.
    The proxy uses a sinusoidal latitude-based model to produce realistic
    elevation variation across the globe.

    Adds: elevation_proxy (metres above sea level, approximate).
    """
    df = df.copy()

    lat = df['lat'].values.astype(float)
    lon = df['lon'].values.astype(float)

    rng = np.random.RandomState(42)
    noise = rng.normal(0.0, 50.0, len(lat))

    elevation_proxy = (
        np.abs(np.sin(np.radians(lat * 2.0))) * 500.0
        + np.cos(np.radians(lon)) * 100.0
        + noise
    )

    df['elevation_proxy'] = elevation_proxy
    logger.info(
        f"Elevation proxy: mean={elevation_proxy.mean():.2f} m, "
        f"std={elevation_proxy.std():.2f} m"
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
