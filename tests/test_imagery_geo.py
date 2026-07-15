"""Tests for imagery.geo — bbox construction, tile math, PR envelope."""

from pytest import approx

from imagery import config, geo


def test_bbox_from_point_centered():
    bbox = geo.bbox_from_point(18.2, -66.4, buffer_deg=0.05)
    west, south, east, north = bbox
    assert west == approx(-66.45) and east == approx(-66.35)
    assert south == approx(18.15) and north == approx(18.25)
    lat, lon = geo.bbox_center(bbox)
    assert lat == approx(18.2)
    assert lon == approx(-66.4)


def test_bbox_from_point_default_buffer():
    bbox = geo.bbox_from_point(18.2, -66.4)
    assert bbox[2] - bbox[0] == approx(2 * config.DEFAULT_BUFFER_DEG)


def test_lat_lon_to_tile_matches_slippy_math():
    # Zoom 0 → single tile (0,0); zoom 1 → NW quadrant for PR (northern, western).
    assert geo.lat_lon_to_tile(0.0, 0.0, 0) == (0, 0)
    x, y = geo.lat_lon_to_tile(18.2, -66.4, 1)
    assert (x, y) == (0, 0)


def test_overlaps_pr_true_for_pr_bbox():
    assert geo.overlaps_pr([-66.45, 18.15, -66.35, 18.25]) is True


def test_overlaps_pr_false_far_away():
    assert geo.overlaps_pr([10.0, 40.0, 11.0, 41.0]) is False


def test_clamp_bbox_to_pr():
    clamped = geo.clamp_bbox_to_pr([-70.0, 10.0, -60.0, 30.0])
    assert clamped[0] >= config.PR_LON_MIN
    assert clamped[1] >= config.PR_LAT_MIN
    assert clamped[2] <= config.PR_LON_MAX
    assert clamped[3] <= config.PR_LAT_MAX
