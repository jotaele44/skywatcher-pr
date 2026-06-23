from fr24.calibration.features.airport_alignment import (
    AirportFootprint,
    compute_airport_alignment,
    enrich_candidate_with_airport_alignment,
)


def test_airport_alignment_scores_candidate_inside_footprint_radius() -> None:
    footprints = [
        AirportFootprint(
            footprint_id="pr-sju-test-fbo",
            facility_name="Test FBO",
            facility_type="fbo",
            latitude=18.0,
            longitude=-66.0,
            radius_m=500,
        )
    ]

    result = compute_airport_alignment({"candidate_latitude": "18.0", "candidate_longitude": "-66.0"}, footprints)

    assert result.airport_alignment == 1.0
    assert result.nearest_footprint_id == "pr-sju-test-fbo"
    assert result.match_count == 1


def test_airport_alignment_returns_zero_without_candidate_coordinates() -> None:
    result = compute_airport_alignment({}, [])

    assert result.airport_alignment == 0.0
    assert result.match_count == 0


def test_airport_alignment_enrichment_adds_classifier_column() -> None:
    footprints = [
        AirportFootprint(
            footprint_id="pr-helipad-test",
            facility_name="Test Helipad",
            facility_type="helipad",
            latitude=18.0,
            longitude=-66.0,
            radius_m=100,
        )
    ]

    enriched = enrich_candidate_with_airport_alignment({"candidate_latitude": "18.0", "candidate_longitude": "-66.0"}, footprints)

    assert enriched["airport_alignment"] == "1.0"
    assert enriched["nearest_airport_footprint_id"] == "pr-helipad-test"
