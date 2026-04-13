import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)


def normalize_coordinates(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce lat/lon to float, clip to valid ranges, drop invalid rows.

    Clipping ranges:
        lat ∈ [-90, 90]
        lon ∈ [-180, 180]
    Rows where lat or lon cannot be parsed as a number are dropped.
    """
    df = df.copy()

    if 'lat' not in df.columns or 'lon' not in df.columns:
        logger.error("DataFrame is missing 'lat' and/or 'lon' columns")
        return df

    df['lat'] = pd.to_numeric(df['lat'], errors='coerce')
    df['lon'] = pd.to_numeric(df['lon'], errors='coerce')

    df['lat'] = df['lat'].clip(-90.0, 90.0)
    df['lon'] = df['lon'].clip(-180.0, 180.0)

    before = len(df)
    df = df.dropna(subset=['lat', 'lon']).reset_index(drop=True)
    after = len(df)

    if before != after:
        logger.info(f"normalize_coordinates: dropped {before - after} rows with unparseable coordinates")

    logger.info(f"normalize_coordinates: {after} valid rows retained")
    return df


def add_coordinate_metadata(df: pd.DataFrame) -> pd.DataFrame:
    """Append derived coordinate metadata columns.

    Adds: lat_abs, lon_abs, hemisphere (N/S), meridian (E/W).
    """
    df = df.copy()

    if 'lat' not in df.columns or 'lon' not in df.columns:
        logger.warning("Cannot add coordinate metadata: missing lat/lon columns")
        return df

    df['lat_abs']    = df['lat'].abs()
    df['lon_abs']    = df['lon'].abs()
    df['hemisphere'] = df['lat'].apply(lambda x: 'N' if x >= 0.0 else 'S')
    df['meridian']   = df['lon'].apply(lambda x: 'E' if x >= 0.0 else 'W')
    return df
