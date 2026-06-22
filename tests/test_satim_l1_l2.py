from fr24.calibration.l1_segmenter_calibration import compute_fractional_boxes, score_annotations
from fr24.calibration.l2_route_calibration import pixel_in_range, sweep_min_route_pixels


def test_l1_fractional_boxes_are_ordered():
    boxes = compute_fractional_boxes(1000, 1000)
    assert boxes["map_bbox"] == (40, 80, 960, 720)
    assert boxes["panel_bbox"] == (40, 720, 960, 1000)


def test_l1_annotation_score():
    metrics = score_annotations([
        {"route_pixels_total": 100, "route_pixels_in_map": 95, "panel_text_pixels_in_map": 0}
    ])
    assert metrics["route_pixel_coverage"] == 0.95
    assert metrics["panel_text_overlap_pixels"] == 0


def test_l2_pixel_range_and_threshold_sweep():
    ranges = {"orange": {"r": (190, 255), "g": (80, 180), "b": (0, 80)}}
    assert pixel_in_range((220, 120, 20), ranges) is True
    assert pixel_in_range((10, 120, 20), ranges) is False
    assert sweep_min_route_pixels([3, 8, 21], [4, 8, 20]) == {4: 2, 8: 2, 20: 1}
