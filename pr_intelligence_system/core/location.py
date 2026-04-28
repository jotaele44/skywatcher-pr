import logging
import warnings

import geopandas as gpd
import pandas as pd

logger = logging.getLogger(__name__)

# Puerto Rico bounding box: (lat_max, lon_min), (lat_min, lon_max)
_PR_VIEWBOX = [(18.6, -67.3), (17.8, -65.2)]
_USER_AGENT = "pr_int_query/1.0"

# OSM type → default query radius in km
_RADIUS_BY_TYPE = {
    "city": 10,
    "town": 10,
    "suburb": 5,
    "village": 5,
    "hamlet": 5,
    "island": 50,
    "park": 15,
    "nature_reserve": 15,
    "water": 15,
    "river": 10,
    "bay": 10,
}
_DEFAULT_RADIUS_KM = 10.0

# In-memory geocoding cache (keyed on normalised name)
_geocode_cache: dict = {}

# ---------------------------------------------------------------------------
# Aspect filter definitions
# ---------------------------------------------------------------------------
# Each value is a callable (pd.DataFrame) -> pd.Series[bool]

def _safe_get(df, col, default):
    return df[col] if col in df.columns else pd.Series(default, index=df.index)

ASPECT_FILTERS = {
    "coastal":         lambda df: _safe_get(df, "elevation_proxy", 9999) < 50,
    "mountainous":     lambda df: _safe_get(df, "elevation_proxy", 0) > 400,
    "riverine":        lambda df: _safe_get(df, "hydro_align", 0.0) > 0.50,
    "karst":           lambda df: (
        _safe_get(df, "lon", 0.0).between(-67.3, -66.5) &
        _safe_get(df, "lat", 0.0).between(18.2, 18.5)
    ),
    "urban":           lambda df: _safe_get(df, "in_infrastructure_zone", False).astype(bool),
    "high-confidence": lambda df: _safe_get(df, "confidence", 0.0) > 0.75,
    "corridor":        lambda df: _safe_get(df, "cluster", -1) != -1,
    "flat":            lambda df: _safe_get(df, "slope_class", "") == "flat",
    "sloped":          lambda df: _safe_get(df, "slope_class", "").isin(["moderate", "steep", "gentle"]),
}


def list_aspects() -> list:
    """Return sorted list of valid aspect names."""
    return sorted(ASPECT_FILTERS.keys())


def apply_aspects(gdf: gpd.GeoDataFrame, aspects: list) -> gpd.GeoDataFrame:
    """
    Filter GeoDataFrame rows to those satisfying ALL requested aspects.

    Unknown aspect names are warned and skipped. Returns gdf unchanged
    if aspects is empty or None.
    """
    if not aspects:
        return gdf

    mask = pd.Series(True, index=gdf.index)
    for name in aspects:
        fn = ASPECT_FILTERS.get(name.lower())
        if fn is None:
            logger.warning(
                "Unknown aspect '%s' — ignored. Valid: %s", name, list_aspects()
            )
            continue
        try:
            mask = mask & fn(gdf)
        except Exception as exc:
            logger.warning("Aspect '%s' filter failed (%s); skipped.", name, exc)

    result = gdf[mask].copy()
    logger.info(
        "Aspect filter [%s]: %d → %d rows.",
        ", ".join(aspects), len(gdf), len(result),
    )
    return result


# ---------------------------------------------------------------------------
# Geocoding
# ---------------------------------------------------------------------------

def resolve_location(name: str, radius_km: float = None) -> dict:
    """
    Resolve a place name to coordinates and a default query radius.

    Strategy:
      1. Search Nominatim bounded to Puerto Rico viewbox
      2. If no result, retry with ", Puerto Rico" appended
      3. Select default radius from OSM result type (overridden by radius_km)

    Returns
    -------
    dict with keys: lat, lon, radius_km, display_name, osm_type

    Raises
    ------
    ValueError  if the place cannot be resolved
    ImportError if geopy is not installed
    """
    try:
        from geopy.geocoders import Nominatim
        from geopy.exc import GeocoderTimedOut, GeocoderServiceError
    except ImportError:
        raise ImportError("geopy is required for location queries: pip install geopy")

    cache_key = name.lower().strip()
    if cache_key in _geocode_cache:
        result = _geocode_cache[cache_key].copy()
        if radius_km is not None:
            result["radius_km"] = radius_km
        logger.info("Geocode cache hit: '%s' → %s", name, result["display_name"])
        return result

    geocoder = Nominatim(user_agent=_USER_AGENT, timeout=10)

    location = None
    try:
        location = geocoder.geocode(
            name,
            viewbox=_PR_VIEWBOX,
            bounded=True,
            exactly_one=True,
        )
    except (GeocoderTimedOut, GeocoderServiceError) as exc:
        logger.warning("Nominatim (bounded) failed for '%s': %s", name, exc)

    if location is None:
        # Retry without bounding, appending Puerto Rico for disambiguation
        retry_name = name if "puerto rico" in name.lower() else f"{name}, Puerto Rico"
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                location = geocoder.geocode(retry_name, exactly_one=True)
        except (GeocoderTimedOut, GeocoderServiceError) as exc:
            logger.warning("Nominatim (unbounded) failed for '%s': %s", retry_name, exc)

    if location is None:
        raise ValueError(
            f"Could not resolve location: '{name}'\n"
            f"Try a more specific name, e.g. 'San Juan, Puerto Rico', "
            f"or use explicit coordinates instead."
        )

    raw = location.raw
    osm_type = raw.get("type", raw.get("class", ""))
    default_radius = _RADIUS_BY_TYPE.get(osm_type, _DEFAULT_RADIUS_KM)

    result = {
        "lat": float(location.latitude),
        "lon": float(location.longitude),
        "radius_km": radius_km if radius_km is not None else default_radius,
        "display_name": location.address,
        "osm_type": osm_type,
    }

    _geocode_cache[cache_key] = result.copy()
    logger.info(
        "Resolved '%s' → %s (%.4f, %.4f), radius %.1f km",
        name, result["display_name"], result["lat"], result["lon"], result["radius_km"],
    )
    return result
