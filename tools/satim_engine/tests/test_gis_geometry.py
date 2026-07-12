"""Unit tests for the offline GIS join geometry.

The pure-geometry tests import only stdlib + the ``gis_geometry`` module, so they
run without pandas. The pandas-facing ``bbox_context_join`` tests are guarded
with ``importorskip`` so the file still collects in a pandas-free environment.
"""
import pytest

from satim_engine.plugins.gis_geometry import (
    bbox_distance_deg,
    layer_bbox,
    point_in_bbox,
    resolve_geometry_layers,
)

# A small AOI: roughly a 0.1x0.1 degree box over western Puerto Rico.
AOI = {"bbox": [-67.20, 18.20, -67.00, 18.40]}


def test_layer_bbox_from_explicit_bbox():
    assert layer_bbox(AOI) == (-67.20, 18.20, -67.00, 18.40)


def test_layer_bbox_from_points_extent():
    layer = {"points": [(-67.2, 18.2), (-67.0, 18.4), (-67.1, 18.3)]}
    assert layer_bbox(layer) == (-67.2, 18.2, -67.0, 18.4)


def test_layer_bbox_normalizes_inverted_corners():
    # Caller passes max/min swapped; helper normalizes to min<=max.
    assert layer_bbox([-67.0, 18.4, -67.2, 18.2]) == (-67.2, 18.2, -67.0, 18.4)


def test_layer_bbox_returns_none_for_opaque_layer():
    assert layer_bbox(object()) is None
    assert layer_bbox({"kind": "roads"}) is None


def test_point_in_bbox_membership():
    bbox = layer_bbox(AOI)
    assert point_in_bbox(18.30, -67.10, bbox) is True   # inside
    assert point_in_bbox(18.20, -67.20, bbox) is True   # on the corner
    assert point_in_bbox(18.50, -67.10, bbox) is False  # north of the box


def test_bbox_distance_zero_inside_positive_outside():
    bbox = layer_bbox(AOI)
    assert bbox_distance_deg(18.30, -67.10, bbox) == 0.0
    # 0.1 deg north of the top edge.
    assert bbox_distance_deg(18.50, -67.10, bbox) == pytest.approx(0.10, abs=1e-9)


def test_resolve_geometry_layers_skips_non_geometric():
    layers = {"aoi": AOI, "opaque": object(), "roads": {"kind": "roads"}}
    resolved = resolve_geometry_layers(layers)
    assert [name for name, _ in resolved] == ["aoi"]


def test_bbox_context_join_offline_match_and_columns():
    pd = pytest.importorskip("pandas")
    from satim_engine.plugins.gis_join import bbox_context_join

    df = pd.DataFrame([
        {"source": "t.csv", "latitude": 18.30, "longitude": -67.10},  # inside AOI
        {"source": "t.csv", "latitude": 18.50, "longitude": -67.10},  # outside AOI
    ])
    out = bbox_context_join(df, layers={"aoi": AOI})

    # Required schema columns are preserved.
    for col in ("source", "latitude", "longitude", "gis_join_status", "gis_layer_count"):
        assert col in out.columns
    assert list(out["gis_join_status"]) == ["GIS_JOIN_OFFLINE", "GIS_JOIN_OFFLINE"]
    assert out.loc[0, "gis_matched_layers"] == "aoi"
    assert out.loc[0, "gis_nearest_layer_deg"] == 0.0
    assert out.loc[1, "gis_matched_layers"] == ""
    assert out.loc[1, "gis_nearest_layer_deg"] == pytest.approx(0.10, abs=1e-6)


def test_bbox_context_join_offline_never_mutates_input():
    pd = pytest.importorskip("pandas")
    from satim_engine.plugins.gis_join import bbox_context_join

    df = pd.DataFrame([{"source": "t.csv", "latitude": 18.30, "longitude": -67.10}])
    original = df.copy()
    bbox_context_join(df, layers={"aoi": AOI})
    pd.testing.assert_frame_equal(df, original)


def test_bbox_context_join_opaque_layers_stay_context_only():
    pd = pytest.importorskip("pandas")
    from satim_engine.plugins.gis_join import bbox_context_join

    df = pd.DataFrame([{"source": "t.csv", "latitude": 18.30, "longitude": -67.10}])
    out = bbox_context_join(df, layers={"parcels": object(), "roads": object()})
    # Opaque handles: still counted, but no geometry => context-only, no crash.
    assert out.loc[0, "gis_join_status"] == "BBOX_CONTEXT_ONLY"
    assert out.loc[0, "gis_layer_count"] == 2
    assert "gis_matched_layers" not in out.columns
