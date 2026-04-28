import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock, patch
import numpy as np
import pandas as pd
import geopandas as gpd
import pytest
from shapely.geometry import Point

from core.location import apply_aspects, list_aspects, resolve_location, ASPECT_FILTERS


def _make_gdf(n=6, **kwargs):
    defaults = {
        "lat": [18.0, 18.1, 18.2, 18.3, 18.4, 18.5],
        "lon": [-66.9, -66.8, -66.7, -66.6, -66.5, -66.4],
        "elevation_proxy": [10.0, 200.0, 500.0, 30.0, 600.0, 5.0],
        "hydro_align": [0.6, 0.3, 0.7, 0.2, 0.8, 0.1],
        "confidence": [0.9, 0.5, 0.8, 0.4, 0.9, 0.3],
        "cluster": [1, -1, 2, -1, 3, -1],
        "slope_class": ["flat", "gentle", "steep", "flat", "moderate", "flat"],
        "in_infrastructure_zone": [True, False, False, True, False, False],
        "classification": ["anomaly"] * 6,
    }
    defaults.update(kwargs)
    rows = pd.DataFrame({k: v[:n] for k, v in defaults.items()})
    geoms = [Point(row.lon, row.lat) for row in rows.itertuples(index=False)]
    return gpd.GeoDataFrame(rows, geometry=geoms, crs="EPSG:4326")


# ---------- apply_aspects ----------

def test_apply_aspects_coastal():
    """Coastal: elevation_proxy < 50 → keeps rows 0, 3, 5."""
    gdf = _make_gdf()
    result = apply_aspects(gdf, ["coastal"])
    assert (result["elevation_proxy"] < 50).all()
    assert len(result) == 3


def test_apply_aspects_mountainous():
    """Mountainous: elevation_proxy > 400 → keeps rows 2, 4."""
    gdf = _make_gdf()
    result = apply_aspects(gdf, ["mountainous"])
    assert (result["elevation_proxy"] > 400).all()
    assert len(result) == 2


def test_apply_aspects_multiple_and_logic():
    """AND logic: coastal AND riverine → elevation < 50 AND hydro_align > 0.5."""
    gdf = _make_gdf()
    result = apply_aspects(gdf, ["coastal", "riverine"])
    assert (result["elevation_proxy"] < 50).all()
    assert (result["hydro_align"] > 0.50).all()


def test_apply_aspects_empty_list():
    """Empty aspects list → returns gdf unchanged."""
    gdf = _make_gdf()
    result = apply_aspects(gdf, [])
    assert len(result) == len(gdf)


def test_apply_aspects_none():
    """None aspects → returns gdf unchanged."""
    gdf = _make_gdf()
    result = apply_aspects(gdf, None)
    assert len(result) == len(gdf)


def test_apply_aspects_unknown_name(caplog):
    """Unknown aspect name logs a warning and returns full set."""
    import logging
    gdf = _make_gdf()
    with caplog.at_level(logging.WARNING, logger="core.location"):
        result = apply_aspects(gdf, ["nonexistent_aspect"])
    assert len(result) == len(gdf)
    assert "nonexistent_aspect" in caplog.text


def test_list_aspects_returns_known_names():
    aspects = list_aspects()
    for name in ["coastal", "mountainous", "riverine", "karst", "urban",
                 "high-confidence", "corridor", "flat", "sloped"]:
        assert name in aspects


# ---------- resolve_location ----------

def _make_mock_location(lat=18.47, lon=-66.11, address="San Juan, Puerto Rico", osm_type="city"):
    loc = MagicMock()
    loc.latitude = lat
    loc.longitude = lon
    loc.address = address
    loc.raw = {"type": osm_type, "class": osm_type}
    return loc


def test_resolve_location_cache():
    """Second call with same name hits cache — geocoder called only once."""
    import core.location as loc_mod
    loc_mod._geocode_cache.clear()

    mock_loc = _make_mock_location()
    with patch("geopy.geocoders.Nominatim") as MockNominatim:
        instance = MockNominatim.return_value
        instance.geocode.return_value = mock_loc

        r1 = resolve_location("San Juan")
        r2 = resolve_location("San Juan")

    assert r1["lat"] == r2["lat"]
    # geocode called only once (second call uses cache)
    assert instance.geocode.call_count == 1


def test_resolve_location_radius_from_type():
    """City type → default radius 10 km."""
    import core.location as loc_mod
    loc_mod._geocode_cache.clear()

    mock_loc = _make_mock_location(osm_type="city")
    with patch("geopy.geocoders.Nominatim") as MockNominatim:
        instance = MockNominatim.return_value
        instance.geocode.return_value = mock_loc
        result = resolve_location("San Juan")

    assert result["radius_km"] == 10


def test_resolve_location_radius_override():
    """Explicit radius_km overrides the type-based default."""
    import core.location as loc_mod
    loc_mod._geocode_cache.clear()

    mock_loc = _make_mock_location(osm_type="city")
    with patch("geopy.geocoders.Nominatim") as MockNominatim:
        instance = MockNominatim.return_value
        instance.geocode.return_value = mock_loc
        result = resolve_location("San Juan", radius_km=25.0)

    assert result["radius_km"] == 25.0


def test_resolve_location_not_found_raises():
    """Unresolvable name raises ValueError."""
    import core.location as loc_mod
    loc_mod._geocode_cache.clear()

    with patch("geopy.geocoders.Nominatim") as MockNominatim:
        instance = MockNominatim.return_value
        instance.geocode.return_value = None
        with pytest.raises(ValueError, match="Could not resolve"):
            resolve_location("Narnia")
