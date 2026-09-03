from fr24.calibration.l5_synthetic_boundary_classifier import (
    classify_candidate,
    classify_synthetic_boundary,
)


def test_strong_synthetic_boundary_classifies_as_probable_tile_seam_observation() -> None:
    result = classify_synthetic_boundary(
        {
            "straightness": 0.98,
            "radiometric_delta": 0.95,
            "terrain_crossing": 0.90,
            "landcover_persistence": 0.90,
            "coastal_crossing_score": 0.60,
            "orthogonality": 0.0,
            "road_alignment": 0.0,
            "building_alignment": 0.0,
            "airport_alignment": 0.0,
            "parcel_alignment": 0.0,
            "infrastructure_rejection": 0.0,
        }
    )

    assert result["classification"] == "probable_tile_seam"
    assert result["confidence"] >= 0.55
    assert result["resolved_origin"] == "UNRESOLVED"
    assert "SOURCE_MOSAIC_CUTLINE" in result["origin_candidates"]
    assert "DISPLAY_TILE_EDGE" in result["origin_candidates"]


def test_infrastructure_alignment_pushes_candidate_to_ground_feature_candidate() -> None:
    result = classify_synthetic_boundary(
        {
            "straightness": 0.98,
            "radiometric_delta": 0.20,
            "terrain_crossing": 0.10,
            "landcover_persistence": 0.10,
            "orthogonality": 1.0,
            "road_alignment": 1.0,
            "building_alignment": 0.9,
            "airport_alignment": 0.8,
            "parcel_alignment": 0.8,
            "infrastructure_rejection": 0.88,
        }
    )

    assert result["classification"] == "persistent_ground_feature_candidate"
    assert result["resolved_origin"] == "UNRESOLVED"


def test_orthogonality_alone_is_not_enough_for_tile_seam() -> None:
    result = classify_synthetic_boundary(
        {
            "straightness": 0.90,
            "radiometric_delta": 0.10,
            "terrain_crossing": 0.05,
            "landcover_persistence": 0.05,
            "orthogonality": 1.0,
            "infrastructure_rejection": 0.0,
        }
    )

    assert result["classification"] == "indeterminate"


def test_legacy_candidate_columns_are_supported_without_origin_promotion() -> None:
    result = classify_candidate(
        {
            "straight_boundary_score": "0.99",
            "radiometric_discontinuity_score": "0.95",
            "terrain_crossing": "0.80",
            "landcover_persistence": "0.80",
            "infrastructure_alignment": "0.0",
        }
    )

    assert result["classification"] == "probable_tile_seam"
    assert result["resolved_origin"] == "UNRESOLVED"
