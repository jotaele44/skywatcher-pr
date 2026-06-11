"""Tests for GIS intelligence: haversine and corridor membership."""

import pytest

from pipeline.gis_intelligence import (
    CorridorAnalyzer,
    PuertoRicoInfrastructure,
    haversine_nm,
)


def test_haversine_same_point():
    dist = haversine_nm(18.44, -66.0, 18.44, -66.0)
    assert dist == pytest.approx(0.0, abs=1e-6)


def test_haversine_known_distance():
    # SJU → BQN: ~60 nm
    dist = haversine_nm(18.4373, -66.0018, 18.4948, -67.1294)
    assert 55 < dist < 70, f"Expected ~60 nm, got {dist:.1f}"


def test_infrastructure_loads():
    infra = PuertoRicoInfrastructure()
    assert infra is not None


def test_corridor_analyzer_find_corridors(populated_db):
    import sqlite3
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    track_pts = [dict(r) for r in conn.execute(
        "SELECT * FROM track_points WHERE flight_id = 'FLT_N5854Z_001'"
    )]
    conn.close()

    infra = PuertoRicoInfrastructure()
    analyzer = CorridorAnalyzer(infra)
    result = analyzer.find_corridors_for_flight(track_pts)
    assert isinstance(result, list)


def test_haversine_triangle_inequality():
    a = haversine_nm(18.0, -66.0, 18.5, -66.0)
    b = haversine_nm(18.5, -66.0, 18.5, -67.0)
    c = haversine_nm(18.0, -66.0, 18.5, -67.0)
    assert c <= a + b + 0.1  # triangle inequality with small tolerance
