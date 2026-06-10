"""Tests for RouteExtractor and FR24UISegmenter: synthetic route extraction."""

import pytest

from fr24.ui_segmenter import FR24UISegmenter, FR24Segments, BBox
from fr24.route_extractor import (
    RouteExtractor, RouteCandidate, COLOR_RANGES,
    _bbox_of_points, _polyline_length,
)


# ------------------------------------------------------------------ segmenter

def test_segmenter_geometric_init():
    seg = FR24UISegmenter(mode="geometric")
    assert seg is not None


def test_segmenter_invalid_mode():
    with pytest.raises(ValueError):
        FR24UISegmenter(mode="invalid")


def test_segment_from_size_returns_segments():
    seg = FR24UISegmenter()
    result = seg.segment_from_size(1024, 768)
    assert isinstance(result, FR24Segments)
    assert result.width == 1024
    assert result.height == 768
    assert result.method == "geometric"


def test_map_bbox_in_upper_portion():
    seg = FR24UISegmenter()
    result = seg.segment_from_size(1000, 800)
    bb = result.map_bbox
    assert bb.y < 800 * 0.20          # starts near top
    assert bb.y + bb.h < 800 * 0.85   # ends before bottom panel


def test_panel_bbox_in_lower_portion():
    seg = FR24UISegmenter()
    result = seg.segment_from_size(1000, 800)
    bb = result.panel_bbox
    assert bb.y > 800 * 0.60   # starts in lower portion of image


def test_map_and_panel_dont_heavily_overlap():
    seg = FR24UISegmenter()
    result = seg.segment_from_size(1000, 800)
    map_bottom = result.map_bbox.y + result.map_bbox.h
    panel_top = result.panel_bbox.y
    # At most 5% of height overlap allowed
    assert panel_top >= map_bottom - 40


def test_label_regions_returned():
    seg = FR24UISegmenter()
    result = seg.segment_from_size(1024, 768)
    assert len(result.labels) > 0
    types = {l.region_type for l in result.labels}
    assert "callsign" in types


def test_detect_label_regions_direct():
    seg = FR24UISegmenter()
    labels = seg.detect_label_regions(1024, 768)
    assert len(labels) >= 4
    for lbl in labels:
        assert lbl.confidence > 0


def test_bbox_as_tuple():
    bb = BBox(10, 20, 100, 50)
    assert bb.as_tuple() == (10, 20, 100, 50)
    assert bb.crop_coords() == (10, 20, 110, 70)


# ------------------------------------------------------------------ extractor

def test_extractor_init():
    ext = RouteExtractor()
    assert ext is not None


def test_extract_missing_file_returns_empty():
    ext = RouteExtractor()
    result = ext.extract("/nonexistent/path/image.jpg")
    assert result == []


def test_color_ranges_coverage():
    required = {"orange", "yellow", "green", "blue", "red"}
    assert required.issubset(set(COLOR_RANGES.keys()))


def test_route_candidate_centroid():
    rc = RouteCandidate(color="orange", points=[(0, 0), (4, 4)], confidence=0.5)
    cx, cy = rc.centroid()
    assert cx == 2.0
    assert cy == 2.0


def test_route_candidate_empty_centroid():
    rc = RouteCandidate(color="blue")
    assert rc.centroid() == (0.0, 0.0)


def test_bbox_of_points():
    pts = [(10, 20), (30, 40), (50, 60)]
    x, y, w, h = _bbox_of_points(pts)
    assert x == 10 and y == 20
    assert w == 40 and h == 40


def test_polyline_length_zero():
    assert _polyline_length([]) == 0.0
    assert _polyline_length([(5, 5)]) == 0.0


def test_polyline_length_known():
    import math
    pts = [(0, 0), (3, 4)]  # hypotenuse = 5
    assert abs(_polyline_length(pts) - 5.0) < 1e-6


def test_extract_array_black_image_no_routes():
    np = pytest.importorskip("numpy")
    ext = RouteExtractor()
    black = np.zeros((200, 300, 3), dtype="uint8")
    result = ext.extract_array(black)
    assert result == []


def test_extract_array_synthetic_orange_route():
    """Synthetic orange stripe should produce an orange RouteCandidate."""
    try:
        import numpy as np
    except ImportError:
        pytest.skip("numpy not available")

    ext = RouteExtractor()
    arr = np.zeros((100, 200, 3), dtype="uint8")
    # Paint a horizontal orange stripe
    arr[40:50, 20:180, 0] = 220  # R
    arr[40:50, 20:180, 1] = 120  # G
    arr[40:50, 20:180, 2] = 30   # B

    results = ext.extract_array(arr)
    colors = [r.color for r in results]
    assert "orange" in colors, f"Expected orange in {colors}"


def test_get_color_mask_orange():
    try:
        import numpy as np
    except ImportError:
        pytest.skip("numpy not available")

    ext = RouteExtractor()
    arr = np.zeros((10, 10, 3), dtype="uint8")
    arr[5, 5, 0] = 230
    arr[5, 5, 1] = 110
    arr[5, 5, 2] = 40
    mask = ext.get_color_mask(arr, "orange")
    assert mask is not None
    assert mask[5, 5]
    assert not mask[0, 0]


def test_extractor_with_segmenter():
    seg = FR24UISegmenter()
    ext = RouteExtractor(segmenter=seg)
    assert ext._segmenter is seg
    result = ext.extract("/nonexistent.jpg")
    assert isinstance(result, list)


def test_batch_segment(tmp_path):
    seg = FR24UISegmenter()
    results = seg.batch_segment(["/nonexistent1.jpg", "/nonexistent2.jpg"])
    assert len(results) == 2
    for r in results:
        assert isinstance(r, FR24Segments)


# ------------------------------------------------------------------ segment_array

def test_segment_array_returns_segments():
    np = pytest.importorskip("numpy")
    seg = FR24UISegmenter()
    arr = np.zeros((768, 1024, 3), dtype="uint8")
    result = seg.segment_array(arr)
    assert isinstance(result, FR24Segments)
    assert result.width == 1024
    assert result.height == 768


def test_segment_array_map_bbox_sensible():
    np = pytest.importorskip("numpy")
    seg = FR24UISegmenter()
    arr = np.zeros((800, 1000, 3), dtype="uint8")
    result = seg.segment_array(arr)
    assert result.map_bbox.w > 0
    assert result.map_bbox.h > 0
    assert result.map_bbox.y + result.map_bbox.h <= 800


def test_segment_array_edge_mode():
    np = pytest.importorskip("numpy")
    seg = FR24UISegmenter(mode="edge")
    arr = np.zeros((600, 800, 3), dtype="uint8")
    # Paint a horizontal bright band near the expected map/panel boundary
    boundary = int(600 * 0.72)
    arr[boundary - 2:boundary + 2, :] = 255
    result = seg.segment_array(arr)
    # Should return a valid FR24Segments regardless of mode
    assert isinstance(result, FR24Segments)
    assert result.map_bbox.h > 0


def test_segment_array_vs_segment_from_size_consistent():
    np = pytest.importorskip("numpy")
    seg = FR24UISegmenter(mode="geometric")
    w, h = 1024, 768
    arr = np.zeros((h, w, 3), dtype="uint8")
    from_array = seg.segment_array(arr)
    from_size = seg.segment_from_size(w, h)
    assert from_array.map_bbox.as_tuple() == from_size.map_bbox.as_tuple()
    assert from_array.panel_bbox.as_tuple() == from_size.panel_bbox.as_tuple()


def test_extract_array_with_extractor_and_segmenter():
    np = pytest.importorskip("numpy")
    seg = FR24UISegmenter()
    ext = RouteExtractor(segmenter=seg)
    arr = np.zeros((600, 800, 3), dtype="uint8")
    result = ext.extract_array(arr)
    assert isinstance(result, list)


def test_extract_array_single_pixel_region_returns_list():
    np = pytest.importorskip("numpy")
    from fr24.route_extractor import RouteExtractor
    ext = RouteExtractor()
    arr = np.zeros((100, 100, 3), dtype="uint8")
    arr[50, 50] = [0, 0, 255]  # single blue pixel — below min_points threshold
    result = ext.extract_array(arr)
    assert isinstance(result, list)
