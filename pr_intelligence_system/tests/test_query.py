import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
from core.query import compute_summary, filter_ilaps, ILAP_CLASSIFICATION


def _make_ilap_gdf(n_anomaly=5, n_noise=3, high_conf=2, hydro_linked=3, cluster_ids=None):
    """Build a minimal GeoDataFrame that looks like pipeline output."""
    rows = []
    for i in range(n_anomaly):
        rows.append({
            "lat": 18.0 + i * 0.01,
            "lon": -66.0 + i * 0.01,
            "classification": ILAP_CLASSIFICATION,
            "confidence": 0.90 if i < high_conf else 0.50,
            "hydro_align": 0.70 if i < hydro_linked else 0.30,
            "physics_score": 0.80,
            "cluster": (cluster_ids[i] if cluster_ids else -1),
        })
    for i in range(n_noise):
        rows.append({
            "lat": 18.5 + i * 0.01,
            "lon": -66.5 + i * 0.01,
            "classification": "noise",
            "confidence": 0.20,
            "hydro_align": 0.10,
            "physics_score": 0.20,
            "cluster": -1,
        })
    df = pd.DataFrame(rows)
    geoms = [Point(r.lon, r.lat) for r in df.itertuples(index=False)]
    return gpd.GeoDataFrame(df, geometry=geoms, crs="EPSG:4326")


def test_filter_ilaps_keeps_only_anomaly():
    gdf = _make_ilap_gdf(n_anomaly=5, n_noise=3)
    result = filter_ilaps(gdf)
    assert len(result) == 5
    assert (result["classification"] == ILAP_CLASSIFICATION).all()


def test_filter_ilaps_empty_input():
    empty = gpd.GeoDataFrame(columns=["classification", "geometry"], crs="EPSG:4326")
    result = filter_ilaps(empty)
    assert result.empty


def test_compute_summary_counts():
    gdf = _make_ilap_gdf(n_anomaly=5, high_conf=2, hydro_linked=3, cluster_ids=[1, 1, 2, -1, -1])
    ilaps = filter_ilaps(gdf)
    s = compute_summary(ilaps)
    assert s["total_ilaps"] == 5
    assert s["high_confidence_count"] == 2
    assert s["hydro_linked_count"] == 3
    assert s["corridor_count"] == 2
    assert set(s["corridor_ids"]) == {1, 2}


def test_compute_summary_empty():
    empty = gpd.GeoDataFrame(columns=["classification", "geometry", "confidence",
                                       "hydro_align", "physics_score", "cluster"],
                              crs="EPSG:4326")
    s = compute_summary(empty)
    assert s["total_ilaps"] == 0
    assert s["high_confidence_count"] == 0
    assert s["hydro_linked_count"] == 0
    assert s["corridor_count"] == 0
    assert s["corridor_ids"] == []
    assert s["mean_confidence"] == 0.0


def test_compute_summary_mean_values():
    gdf = _make_ilap_gdf(n_anomaly=4, n_noise=0, high_conf=0, hydro_linked=0)
    ilaps = filter_ilaps(gdf)
    s = compute_summary(ilaps)
    assert 0.0 <= s["mean_confidence"] <= 1.0
    assert 0.0 <= s["mean_physics_score"] <= 1.0
