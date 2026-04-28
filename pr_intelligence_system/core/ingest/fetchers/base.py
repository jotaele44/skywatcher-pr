import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)

# Canonical column schema every fetcher must return
FETCHER_COLUMNS = ['lat', 'lon', 'raster_value', 'source_file', 'source_format']

COLUMN_DTYPES = {
    'lat':          float,
    'lon':          float,
    'raster_value': float,
    'source_file':  str,
    'source_format': str,
}


def empty_fetcher_df(extra_cols: list = None) -> pd.DataFrame:
    """Return an empty DataFrame with the canonical fetcher schema.

    Optional extra_cols adds additional empty columns beyond the base schema.
    """
    cols = FETCHER_COLUMNS + (extra_cols or [])
    return pd.DataFrame(columns=cols)


def validate_fetcher_output(df: pd.DataFrame, fetcher_name: str) -> pd.DataFrame:
    """Coerce a fetcher DataFrame to the required schema.

    Fills any missing required columns with NaN / empty string and logs warnings
    for each missing column.  Does not drop extra columns.
    """
    df = df.copy()

    for col, dtype in COLUMN_DTYPES.items():
        if col not in df.columns:
            logger.warning(
                f"[{fetcher_name}] Missing required column '{col}' – filling with default"
            )
            df[col] = np.nan if dtype in (float, int) else ''

    # Coerce numeric columns
    for col in ('lat', 'lon', 'raster_value'):
        df[col] = pd.to_numeric(df[col], errors='coerce')

    return df


def bbox_to_wkt(aoi: tuple) -> str:
    """Convert (min_lon, min_lat, max_lon, max_lat) bounding box to WKT POLYGON."""
    min_lon, min_lat, max_lon, max_lat = aoi
    return (
        f"POLYGON(({min_lon} {min_lat}, {max_lon} {min_lat}, "
        f"{max_lon} {max_lat}, {min_lon} {max_lat}, {min_lon} {min_lat}))"
    )


def aoi_tile_list(aoi: tuple) -> list:
    """Return list of integer (lat, lon) pairs for 1-degree tiles covering the AOI.

    Used by DEM and Sentinel tile enumeration.
    Tile (lat, lon) = south-west corner of each 1-degree cell.
    """
    min_lon, min_lat, max_lon, max_lat = aoi
    tiles = []
    lat = int(np.floor(min_lat))
    while lat <= int(np.floor(max_lat)):
        lon = int(np.floor(min_lon))
        while lon <= int(np.floor(max_lon)):
            tiles.append((lat, lon))
            lon += 1
        lat += 1
    return tiles
