import geopandas as gpd
import pandas as pd
import numpy as np
import os
import logging

logger = logging.getLogger(__name__)


def load_vector(filepath: str) -> pd.DataFrame:
    """Load a vector file (shp, gpkg, geojson, kml) and return a DataFrame.

    Reprojects to EPSG:4326 if needed, extracts lat/lon from geometry.
    """
    try:
        gdf = gpd.read_file(filepath)

        # Reproject to EPSG:4326 if CRS differs
        if gdf.crs is not None:
            if gdf.crs.to_epsg() != 4326:
                logger.info(f"Reprojecting {filepath} from {gdf.crs} to EPSG:4326")
                gdf = gdf.to_crs(epsg=4326)
        else:
            logger.warning(f"No CRS found for {filepath}, assuming EPSG:4326")
            gdf = gdf.set_crs(epsg=4326)

        # Extract lat/lon
        if len(gdf) > 0:
            non_null_geom = gdf.geometry.dropna()
            is_all_points = (
                len(non_null_geom) > 0
                and (non_null_geom.geom_type == 'Point').all()
            )
            if is_all_points:
                gdf['lon'] = gdf.geometry.x
                gdf['lat'] = gdf.geometry.y
            else:
                centroids = gdf.geometry.centroid
                gdf['lon'] = centroids.x
                gdf['lat'] = centroids.y
        else:
            gdf['lon'] = pd.Series(dtype=float)
            gdf['lat'] = pd.Series(dtype=float)

        df = pd.DataFrame(gdf.drop(columns='geometry'))
        df['source_file'] = os.path.basename(filepath)
        df['source_format'] = 'vector'
        logger.info(f"Loaded vector: {filepath} -> {len(df)} rows")
        return df

    except Exception as e:
        logger.error(f"Failed to load vector {filepath}: {e}")
        raise
