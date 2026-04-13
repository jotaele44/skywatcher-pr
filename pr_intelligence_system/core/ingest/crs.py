import geopandas as gpd
import pandas as pd
import logging

logger = logging.getLogger(__name__)

TARGET_CRS = 'EPSG:4326'
TARGET_EPSG = 4326


def normalize_crs(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Reproject a GeoDataFrame to EPSG:4326, assigning it if absent."""
    if gdf.crs is None:
        logger.warning("GeoDataFrame has no CRS – assuming EPSG:4326")
        gdf = gdf.set_crs(epsg=TARGET_EPSG)
    elif gdf.crs.to_epsg() != TARGET_EPSG:
        logger.info(f"Reprojecting GeoDataFrame from {gdf.crs} to {TARGET_CRS}")
        gdf = gdf.to_crs(TARGET_CRS)
    return gdf


def validate_latlon_range(df: pd.DataFrame) -> pd.DataFrame:
    """Clip lat/lon values to the valid EPSG:4326 range in-place."""
    df = df.copy()

    if 'lat' in df.columns:
        invalid_lat = (df['lat'] < -90) | (df['lat'] > 90)
        n_invalid = int(invalid_lat.sum())
        if n_invalid > 0:
            logger.warning(f"Clipping {n_invalid} out-of-range latitude values to [-90, 90]")
            df.loc[invalid_lat, 'lat'] = df.loc[invalid_lat, 'lat'].clip(-90.0, 90.0)

    if 'lon' in df.columns:
        invalid_lon = (df['lon'] < -180) | (df['lon'] > 180)
        n_invalid = int(invalid_lon.sum())
        if n_invalid > 0:
            logger.warning(f"Clipping {n_invalid} out-of-range longitude values to [-180, 180]")
            df.loc[invalid_lon, 'lon'] = df.loc[invalid_lon, 'lon'].clip(-180.0, 180.0)

    return df


def ensure_crs_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Validate lat/lon ranges and stamp the CRS label onto the DataFrame."""
    df = validate_latlon_range(df)
    df['crs'] = TARGET_CRS
    return df
