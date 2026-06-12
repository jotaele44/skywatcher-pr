from __future__ import annotations

from skywatcher.correlation.footprint_proximity import correlate_point_to_footprints, haversine_m
from skywatcher.registry.airspace_footprints import AirspaceFootprint


def test_haversine_zero_distance() -> None:
    assert haversine_m(18.0, -66.0, 18.0, -66.0) == 0


def test_correlate_point_to_footprints_returns_nearby_match() -> None:
    footprint = AirspaceFootprint(
        footprint_id="pr-test-helipad",
        airfield_code="TEST",
        facility_name="Test Helipad",
        facility_type="helipad",
        operator_class="medical",
        latitude=18.3902778,
        longitude=-66.0719444,
        radius_m=100,
        confidence="high",
        source_tier="T2",
        description="test",
    )

    matches = correlate_point_to_footprints(18.3902778, -66.0719444, [footprint])

    assert len(matches) == 1
    assert matches[0].footprint_id == "pr-test-helipad"
    assert matches[0].match_type == "near_ground_aviation_node"
    assert matches[0].score == 1.0


def test_correlate_point_to_footprints_skips_missing_geometry() -> None:
    footprint = AirspaceFootprint(
        footprint_id="pr-test-g0",
        airfield_code="TEST",
        facility_name="G0 Node",
        facility_type="fbo",
        operator_class="commercial_fbo",
        latitude=None,
        longitude=None,
        radius_m=250,
        confidence="medium",
        source_tier="T2",
        description="test",
    )

    matches = correlate_point_to_footprints(18.3902778, -66.0719444, [footprint])

    assert matches == []
