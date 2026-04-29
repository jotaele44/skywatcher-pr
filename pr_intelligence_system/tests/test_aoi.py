import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from core.aoi import create_aoi, _get_buffer_distance


def test_create_aoi_returns_geodataframe():
    import geopandas as gpd
    gdf = create_aoi(18.265, -66.700, 5.0)
    assert isinstance(gdf, gpd.GeoDataFrame)
    assert len(gdf) == 1
    assert gdf.crs.to_epsg() == 4326


def test_create_aoi_polygon_contains_center():
    from shapely.geometry import Point
    gdf = create_aoi(18.265, -66.700, 5.0)
    center = Point(-66.700, 18.265)
    assert gdf.geometry.iloc[0].contains(center)


def test_create_aoi_columns():
    gdf = create_aoi(18.265, -66.700, 5.0)
    assert "lat" in gdf.columns
    assert "lon" in gdf.columns
    assert "radius_km" in gdf.columns
    assert gdf["lat"].iloc[0] == pytest.approx(18.265)
    assert gdf["lon"].iloc[0] == pytest.approx(-66.700)
    assert gdf["radius_km"].iloc[0] == pytest.approx(5.0)


def test_create_aoi_invalid_lat():
    with pytest.raises(ValueError, match="lat"):
        create_aoi(91.0, -66.700, 5.0)


def test_create_aoi_invalid_lon():
    with pytest.raises(ValueError, match="lon"):
        create_aoi(18.265, 200.0, 5.0)


def test_create_aoi_invalid_radius():
    with pytest.raises(ValueError, match="radius"):
        create_aoi(18.265, -66.700, -1.0)


def test_buffer_distance_positive():
    dist = _get_buffer_distance(5.0)
    assert dist > 0


def test_buffer_distance_scales_with_radius():
    d1 = _get_buffer_distance(5.0)
    d2 = _get_buffer_distance(10.0)
    assert d2 == pytest.approx(d1 * 2, rel=1e-3)
