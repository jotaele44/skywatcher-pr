import logging
import os

import geopandas as gpd

logger = logging.getLogger(__name__)


def fetch_for_aoi(
    aoi_gdf: gpd.GeoDataFrame,
    aoi_id: str,
    output_dir: str,
    days_back: int = 90,
) -> list:
    """
    Fetch satellite data for a given AOI via openEO and return GeoTIFF paths.

    If GeoTIFFs already exist in output_dir for this aoi_id, they are returned
    immediately without re-fetching.

    Parameters
    ----------
    aoi_gdf    : single-row GeoDataFrame of the AOI polygon (EPSG:4326)
    aoi_id     : 8-char hex identifier (used for filenames and job title)
    output_dir : directory where GeoTIFFs are saved (created if absent)
    days_back  : temporal window in days for satellite data search

    Returns
    -------
    list of absolute paths to downloaded GeoTIFF files (may be empty on failure)
    """
    from core.ingest.loaders.openeo_loader import (
        build_bbox,
        build_temporal_extent,
        connect,
        fetch_sentinel2,
    )

    os.makedirs(output_dir, exist_ok=True)

    # Skip re-fetch if data already downloaded
    import glob
    existing = glob.glob(os.path.join(output_dir, "*.tif"))
    if existing:
        logger.info(
            "Satellite data already present for AOI %s (%d file(s)); skipping fetch.",
            aoi_id, len(existing),
        )
        return existing

    try:
        connection = connect()
        bbox = build_bbox(aoi_gdf)
        temporal_extent = build_temporal_extent(days_back)
        tif_paths = fetch_sentinel2(connection, bbox, temporal_extent, output_dir, aoi_id)

        if not tif_paths:
            logger.warning(
                "openEO returned no data for AOI %s "
                "(possible causes: cloud cover, no imagery in temporal window).",
                aoi_id,
            )
        return tif_paths

    except (ConnectionError, ImportError) as exc:
        logger.error("Satellite fetch failed (auth/connectivity): %s", exc)
        raise
    except Exception as exc:
        logger.error("Unexpected error during satellite fetch for AOI %s: %s", aoi_id, exc)
        return []
