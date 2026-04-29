"""
lidar_stream.py — On-demand COPC LiDAR streaming for PR.INT.

Streams Cloud Optimized Point Cloud tiles directly from NOAA S3 storage,
clips to AOI bbox, and generates DEM GeoTIFFs — no full-dataset download.

PDAL must be available on PATH. Install via: conda install -c conda-forge pdal
"""

import json
import logging
import os
import subprocess
import shutil
import tempfile

logger = logging.getLogger(__name__)

# Canonical paths relative to pr_intelligence_system/
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_HERE))
URL_FILE = os.path.join(_PROJECT_ROOT, "data", "raw", "Lidar", "urllist9390_final.txt")
GPKG_INDEX = os.path.join(_PROJECT_ROOT, "data", "raw", "Lidar", "2019_ngs_topobathy_PR_index.gpkg")

MAX_TILES = 3          # conservative initial cap — increase after stable baseline
DEM_RESOLUTION = 5.0  # metres; 5m balances accuracy with file size


def load_urls() -> list:
    """Load and validate COPC URLs from the canonical URL list."""
    if not os.path.exists(URL_FILE):
        raise FileNotFoundError(
            f"LiDAR URL list not found: {URL_FILE}\n"
            "Place urllist9390_final.txt in data/raw/Lidar/"
        )
    clean = []
    with open(URL_FILE) as fh:
        for line in fh:
            url = line.strip().replace("%5C", "").rstrip("\\")
            if url.endswith(".copc.laz"):
                clean.append(url)
    if not clean:
        raise ValueError(f"No valid .copc.laz URLs found in {URL_FILE}")
    logger.info("Loaded %d COPC URLs.", len(clean))
    return clean


def filter_urls_by_bbox(urls: list, bbox: dict, max_tiles: int = MAX_TILES) -> list:
    """
    Select tiles that cover the AOI bbox.

    Uses GPKG tile index when available for spatial filtering; otherwise
    returns the first max_tiles URLs as a conservative fallback.
    """
    if os.path.exists(GPKG_INDEX):
        try:
            return _filter_by_gpkg(urls, bbox, max_tiles)
        except Exception as exc:
            logger.warning("GPKG spatial filter failed (%s); using first %d URLs.", exc, max_tiles)
    else:
        logger.info("No GPKG tile index found; streaming first %d URLs.", max_tiles)
    return urls[:max_tiles]


def _filter_by_gpkg(urls: list, bbox: dict, max_tiles: int) -> list:
    """Intersect bbox with tile index GeoPackage and match tile names to URLs."""
    import geopandas as gpd
    from shapely.geometry import box

    aoi_box = box(bbox["west"], bbox["south"], bbox["east"], bbox["north"])
    index_gdf = gpd.read_file(GPKG_INDEX)
    intersecting = index_gdf[index_gdf.geometry.intersects(aoi_box)]

    if intersecting.empty:
        logger.info("GPKG: no tiles intersect AOI; falling back to first %d URLs.", max_tiles)
        return urls[:max_tiles]

    logger.info("GPKG: %d tile(s) intersect AOI.", len(intersecting))

    url_by_basename = {os.path.basename(u).lower(): u for u in urls}
    matched = []

    for _, row in intersecting.iterrows():
        for attr in ("url", "filename", "name", "FileName", "Name", "title"):
            val = str(row.get(attr) or "")
            if not val:
                continue
            key = os.path.basename(val).lower()
            if key in url_by_basename:
                matched.append(url_by_basename[key])
                break
        if len(matched) >= max_tiles:
            break

    if not matched:
        logger.warning("GPKG matched 0 URL basenames; falling back to first %d.", max_tiles)
        return urls[:max_tiles]

    return matched[:max_tiles]


def stream_tile(url: str, bbox: dict, out_las: str) -> None:
    """Stream a COPC tile bounded to AOI bbox via PDAL translate."""
    bounds = (
        f"([{bbox['west']},{bbox['east']}],"
        f"[{bbox['south']},{bbox['north']}])"
    )
    cmd = [
        "pdal", "translate",
        url, out_las,
        f"--readers.copc.bounds={bounds}",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(
            f"PDAL stream failed for {os.path.basename(url)}: {result.stderr[:400]}"
        )


def las_to_dem(las_path: str, tif_path: str, resolution: float = DEM_RESOLUTION) -> None:
    """Convert LAS to DEM GeoTIFF via PDAL (ground points only, SMRF filter)."""
    pipeline = {
        "pipeline": [
            las_path,
            {"type": "filters.smrf"},
            {"type": "filters.range", "limits": "Classification[2:2]"},
            {
                "type": "writers.gdal",
                "filename": tif_path,
                "resolution": resolution,
                "output_type": "mean",
            },
        ]
    }
    result = subprocess.run(
        ["pdal", "pipeline", "--stdin"],
        input=json.dumps(pipeline).encode(),
        capture_output=True,
        timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError(f"PDAL DEM generation failed: {result.stderr[:400]}")


def stream_lidar(bbox: dict, output_dir: str, cleanup_las: bool = True) -> dict:
    """
    Stream COPC tiles for the AOI bbox and generate DEM GeoTIFFs.

    Parameters
    ----------
    bbox       : {"west": float, "south": float, "east": float, "north": float}
    output_dir : directory where DEM GeoTIFFs are written (created if absent)
    cleanup_las: remove intermediate LAS files after DEM generation

    Returns
    -------
    {"las": [paths], "dem": [paths], "tmp_dir": str}
    Las list is empty when cleanup_las=True (files already removed).
    """
    os.makedirs(output_dir, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="lidar_las_")

    try:
        urls = load_urls()
    except (FileNotFoundError, ValueError) as exc:
        logger.info("LiDAR streaming skipped: %s", exc)
        return {"las": [], "dem": [], "tmp_dir": tmp_dir}

    selected = filter_urls_by_bbox(urls, bbox)
    las_files, dem_files = [], []

    for i, url in enumerate(selected):
        las_path = os.path.join(tmp_dir, f"tile_{i}.las")
        dem_path = os.path.join(output_dir, f"lidar_dem_{i}.tif")

        if os.path.exists(dem_path):
            logger.info("LiDAR DEM cached: %s", os.path.basename(dem_path))
            dem_files.append(dem_path)
            continue

        try:
            logger.info(
                "Streaming LiDAR tile %d/%d: %s",
                i + 1, len(selected), os.path.basename(url),
            )
            stream_tile(url, bbox, las_path)
            las_to_dem(las_path, dem_path)
            dem_files.append(dem_path)
            logger.info("LiDAR DEM ready: %s", os.path.basename(dem_path))
        except Exception as exc:
            logger.warning("Tile %d failed (%s); skipping.", i, exc)
            continue

        if not cleanup_las and os.path.exists(las_path):
            las_files.append(las_path)

    if cleanup_las:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return {"las": las_files, "dem": dem_files, "tmp_dir": tmp_dir}
