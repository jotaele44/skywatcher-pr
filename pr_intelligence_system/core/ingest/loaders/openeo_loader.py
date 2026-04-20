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

DEM_COLLECTION = "COPERNICUS_30"     # Copernicus GLO-30 DEM (30m resolution)
DEM_BAND = "DEM"
DEM_TEMPORAL_EXTENT = ["2010-01-01", "2023-12-31"]  # static dataset; wide range


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

    Downloaded files are renamed with an 'ndvi_' prefix so aoi_pipeline
    can distinguish them from DEM files in the same directory.

    Returns list of downloaded .tif file paths.
    """
    logger.info(
        "Building Sentinel-2 NDVI process graph (bbox=%s, time=%s).", bbox, temporal_extent
    )

    cube = connection.load_collection(
        "SENTINEL2_L2A",
        spatial_extent=bbox,
        temporal_extent=temporal_extent,
        bands=SENTINEL2_BANDS,
        max_cloud_cover=MAX_CLOUD_COVER,
    )

    cube_mean = cube.mean_time()
    ndvi = cube_mean.normalized_difference(band1="B08", band2="B04")

    job_title = f"pr_int_{aoi_id}_ndvi"
    logger.info("Submitting batch job: %s", job_title)

    job = ndvi.create_job(out_format="GTiff", title=job_title)
    job.start_and_wait()
    logger.info("Batch job complete: %s", job.job_id)

    job.get_results().download_files(output_dir)
    return _prefix_new_tifs(output_dir, "ndvi_")


def fetch_dem(
    connection,
    bbox: dict,
    output_dir: str,
    aoi_id: str,
) -> list:
    """
    Fetch Copernicus GLO-30 DEM for the AOI and download as GeoTIFF.

    The DEM is a static dataset (no meaningful temporal dimension).
    Downloaded files are renamed with a 'dem_' prefix.

    Returns list of downloaded .tif file paths.
    """
    logger.info("Building Copernicus DEM process graph (bbox=%s).", bbox)

    cube = connection.load_collection(
        DEM_COLLECTION,
        spatial_extent=bbox,
        temporal_extent=DEM_TEMPORAL_EXTENT,
        bands=[DEM_BAND],
    )

    # DEM is static; mean_time collapses any duplicate timestamps safely
    result = cube.mean_time()

    job_title = f"pr_int_{aoi_id}_dem"
    logger.info("Submitting DEM batch job: %s", job_title)

    job = result.create_job(out_format="GTiff", title=job_title)
    job.start_and_wait()
    logger.info("DEM batch job complete: %s", job.job_id)

    job.get_results().download_files(output_dir)
    return _prefix_new_tifs(output_dir, "dem_")


def _prefix_new_tifs(output_dir: str, prefix: str) -> list:
    """
    Rename any untagged *.tif files in output_dir with the given prefix.
    Files already starting with a known prefix ('ndvi_', 'dem_') are skipped.
    Returns the final list of prefixed .tif paths.
    """
    known_prefixes = ("ndvi_", "dem_")
    renamed = []
    for path in glob.glob(os.path.join(output_dir, "*.tif")):
        basename = os.path.basename(path)
        if basename.startswith(known_prefixes):
            renamed.append(path)
            continue
        new_path = os.path.join(output_dir, prefix + basename)
        os.rename(path, new_path)
        renamed.append(new_path)
    logger.info("Tagged %d file(s) with prefix '%s'.", len(renamed), prefix)
    return renamed
