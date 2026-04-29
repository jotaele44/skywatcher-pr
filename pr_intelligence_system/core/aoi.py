import logging

import geopandas as gpd
import pyproj
from shapely.geometry import Point

logger = logging.getLogger(__name__)

CRS_WGS84 = "EPSG:4326"
CRS_PR_STATE = "EPSG:32161"  # Puerto Rico State Plane (NAD83)


def _get_buffer_distance(radius_km: float) -> float:
    """Return buffer distance in the native units of EPSG:32161."""
    try:
        crs = pyproj.CRS(CRS_PR_STATE)
        unit = crs.axis_info[0].unit_name.lower()
        if "foot" in unit or "feet" in unit:
            return radius_km * 3280.84  # km → US survey feet
        return radius_km * 1000.0  # km → metres
    except Exception as exc:
        logger.warning("Could not detect CRS unit (%s); defaulting to metres.", exc)
        return radius_km * 1000.0


def create_aoi(lat: float, lon: float, radius_km: float) -> gpd.GeoDataFrame:
    """
    Build a circular AOI polygon around (lat, lon) with radius radius_km km.

    Projects to EPSG:32161 for accurate buffering, then returns result in
    EPSG:4326.
    """
    if not -90.0 <= lat <= 90.0:
        raise ValueError(f"lat must be in [-90, 90], got {lat}")
    if not -180.0 <= lon <= 180.0:
        raise ValueError(f"lon must be in [-180, 180], got {lon}")
    if radius_km <= 0:
        raise ValueError(f"radius_km must be positive, got {radius_km}")

    point_gdf = gpd.GeoDataFrame(
        {"lat": [lat], "lon": [lon], "radius_km": [radius_km]},
        geometry=[Point(lon, lat)],
        crs=CRS_WGS84,
    )

    projected = point_gdf.to_crs(CRS_PR_STATE)
    buffer_dist = _get_buffer_distance(radius_km)
    projected["geometry"] = projected.geometry.buffer(buffer_dist)

    aoi_gdf = projected.to_crs(CRS_WGS84)
    logger.info(
        "AOI created: lat=%.4f lon=%.4f radius=%.2f km (buffer=%.1f units in %s)",
        lat, lon, radius_km, buffer_dist, CRS_PR_STATE,
    )
    return aoi_gdf
