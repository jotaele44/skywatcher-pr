import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import geopandas as gpd
from shapely.geometry import Point, Polygon
from core.memory import generate_aoi_id, load_memory, check_coverage, save_to_memory
from core.aoi import create_aoi


def test_generate_aoi_id_deterministic():
    a = generate_aoi_id(18.265, -66.700, 5.0)
    b = generate_aoi_id(18.265, -66.700, 5.0)
    assert a == b


def test_generate_aoi_id_length():
    aoi_id = generate_aoi_id(18.265, -66.700, 5.0)
    assert len(aoi_id) == 8


def test_generate_aoi_id_differs_for_different_inputs():
    a = generate_aoi_id(18.265, -66.700, 5.0)
    b = generate_aoi_id(18.265, -66.700, 10.0)
    c = generate_aoi_id(18.300, -66.700, 5.0)
    assert a != b
    assert a != c


def test_load_memory_missing_file_returns_empty():
    gdf = load_memory("/nonexistent/path/memory.gpkg")
    assert isinstance(gdf, gpd.GeoDataFrame)
    assert gdf.empty


def test_check_coverage_empty_memory_returns_new():
    aoi_gdf = create_aoi(18.265, -66.700, 5.0)
    empty_memory = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    status, matching = check_coverage(aoi_gdf, empty_memory)
    assert status == "new"
    assert matching.empty


def test_check_coverage_no_intersection_returns_new():
    aoi_gdf = create_aoi(18.265, -66.700, 5.0)
    # Store a polygon far away from the query AOI
    far_poly = Polygon([(-10, 40), (-9, 40), (-9, 41), (-10, 41)])
    memory_gdf = gpd.GeoDataFrame(
        {"aoi_id": ["abc"], "result_path": ["x"], "status": ["complete"],
         "ilap_count": [0], "mean_confidence": [0.0], "corridor_count": [0],
         "timestamp": ["2024-01-01"]},
        geometry=[far_poly], crs="EPSG:4326"
    )
    status, matching = check_coverage(aoi_gdf, memory_gdf)
    assert status == "new"


def test_check_coverage_full_containment():
    aoi_small = create_aoi(18.265, -66.700, 1.0)
    aoi_large = create_aoi(18.265, -66.700, 20.0)  # large enough to contain small
    memory_gdf = gpd.GeoDataFrame(
        {"aoi_id": ["abc"], "result_path": ["x"], "status": ["complete"],
         "ilap_count": [0], "mean_confidence": [0.0], "corridor_count": [0],
         "timestamp": ["2024-01-01"]},
        geometry=aoi_large.geometry.values, crs="EPSG:4326"
    )
    status, _ = check_coverage(aoi_small, memory_gdf)
    assert status == "full"


def test_save_and_reload_memory():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "memory.gpkg")
        aoi_gdf = create_aoi(18.265, -66.700, 5.0)
        aoi_id = generate_aoi_id(18.265, -66.700, 5.0)
        summary = {"total_ilaps": 3, "mean_confidence": 0.8, "corridor_count": 1}
        save_to_memory(path, aoi_id, aoi_gdf, summary, "/tmp/results.csv")
        reloaded = load_memory(path)
        assert len(reloaded) == 1
        assert reloaded.iloc[0]["aoi_id"] == aoi_id
        assert reloaded.iloc[0]["ilap_count"] == 3
