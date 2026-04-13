import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)

DEFAULT_RESOLUTION = 0.01  # degrees (~1 km at mid-latitudes)


def assign_cell_id(df: pd.DataFrame, resolution: float = DEFAULT_RESOLUTION) -> pd.DataFrame:
    """Assign a grid cell identifier to every row based on lat/lon.

    The cell_id encodes the integer floor-divided lat and lon cells as
    '<lat_cell>_<lon_cell>'.  Also adds grid_lat / grid_lon centroids.
    """
    df = df.copy()

    if 'lat' not in df.columns or 'lon' not in df.columns:
        logger.error("'lat' or 'lon' column missing – cannot assign cell_id")
        df['cell_id']  = 'UNKNOWN'
        df['grid_lat'] = np.nan
        df['grid_lon'] = np.nan
        return df

    lat_cell = np.floor(df['lat'].values / resolution).astype(int)
    lon_cell = np.floor(df['lon'].values / resolution).astype(int)

    df['cell_id']  = [f"{la}_{lo}" for la, lo in zip(lat_cell, lon_cell)]
    df['grid_lat'] = lat_cell * resolution + resolution / 2.0
    df['grid_lon'] = lon_cell * resolution + resolution / 2.0

    n_unique = df['cell_id'].nunique()
    logger.info(
        f"Grid alignment: resolution={resolution}° → {n_unique} unique cells "
        f"for {len(df)} points"
    )
    return df


def snap_to_grid(df: pd.DataFrame, resolution: float = DEFAULT_RESOLUTION) -> pd.DataFrame:
    """Snap lat/lon coordinates to the nearest grid-cell centroid.

    Adds lat_snapped and lon_snapped columns.
    """
    df = df.copy()

    if 'lat' not in df.columns or 'lon' not in df.columns:
        logger.error("'lat' or 'lon' column missing – cannot snap to grid")
        return df

    df['lat_snapped'] = (
        np.floor(df['lat'].values / resolution) * resolution + resolution / 2.0
    )
    df['lon_snapped'] = (
        np.floor(df['lon'].values / resolution) * resolution + resolution / 2.0
    )
    return df
