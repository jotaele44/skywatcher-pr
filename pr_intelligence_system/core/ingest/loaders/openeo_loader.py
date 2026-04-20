import glob
import logging
import os
from datetime import date, timedelta

import geopandas as gpd

logger = logging.getLogger(__name__)

OPENEO_ENDPOINT = "https://openeo.dataspace.copernicus.eu"
DEFAULT_TEMPORAL_DAYS = 90
SENTINEL2_BANDS = ["B04", "B08", "B11"]  # Red, NIR, SWIR
MAX_CLOUD_COVER = 75  # percent


def connect(endpoint: str = OPENEO_ENDPOINT):
    """Connect and authenticate to the openEO endpoint."""
    try:
        import openeo
    except ImportError:
        raise ImportError("openeo package is required: pip install openeo")

    try:
        connection = openeo.connect(endpoint)
        connection.authenticate_oidc()
        logger.info("Connected to openEO endpoint: %s", endpoint)
        return connection
    except Exception as exc:
        raise ConnectionError(
            f"openEO authentication failed: {exc}\n"
            f"Run once interactively to cache your token:\n"
            f"  python -c \"import openeo; "
            f"openeo.connect('{endpoint}').authenticate_oidc()\""
        ) from exc


def build_bbox(aoi_gdf: gpd.GeoDataFrame) -> dict:
    """Extract bounding box dict from an AOI GeoDataFrame."""
    minx, miny, maxx, maxy = aoi_gdf.total_bounds
    return {"west": float(minx), "south": float(miny), "east": float(maxx), "north": float(maxy)}


def build_temporal_extent(days_back: int = DEFAULT_TEMPORAL_DAYS) -> list:
    """Return [start_date, end_date] strings for the last N days."""
    end = date.today()
    start = end - timedelta(days=days_back)
    return [str(start), str(end)]


def fetch_sentinel2(
    connection,
    bbox: dict,
    temporal_extent: list,
    output_dir: str,
    aoi_id: str,
) -> list:
    """
    Build openEO process graph for NDVI, submit batch job, wait, download.

    Process graph:
      SENTINEL2_L2A → filter cloud → mean over time → NDVI → GeoTIFF

    Returns list of downloaded .tif file paths.
    """
    logger.info(
        "Building Sentinel-2 process graph (bbox=%s, time=%s).", bbox, temporal_extent
    )

    cube = connection.load_collection(
        "SENTINEL2_L2A",
        spatial_extent=bbox,
        temporal_extent=temporal_extent,
        bands=SENTINEL2_BANDS,
        max_cloud_cover=MAX_CLOUD_COVER,
    )

    # Temporal mean to collapse the time dimension
    cube_mean = cube.mean_time()

    # NDVI = (B08 - B04) / (B08 + B04)
    ndvi = cube_mean.normalized_difference("B08", "B04")

    job_title = f"pr_int_{aoi_id}_ndvi"
    logger.info("Submitting batch job: %s", job_title)

    job = ndvi.create_job(
        out_format="GTiff",
        title=job_title,
    )
    job.start_and_wait()
    logger.info("Batch job complete: %s", job.job_id)

    results = job.get_results()
    results.download_files(output_dir)
    logger.info("Downloaded results to %s", output_dir)

    tif_paths = glob.glob(os.path.join(output_dir, "*.tif"))
    logger.info("GeoTIFF files available: %d", len(tif_paths))
    return tif_paths
