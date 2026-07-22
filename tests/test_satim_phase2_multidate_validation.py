from fr24.calibration.satim_multidate_validation import validate_candidate_across_dates


BASE_CANDIDATE = {
    "visual_id": "SATIM-VIS-PHASE2_001",
    "classification": "probable_tile_seam",
    "imagery_epoch": "2024-01",
    "contradiction_flags": [],
}


def test_multidate_validation_blocks_single_still_promotion():
    result = validate_candidate_across_dates(BASE_CANDIDATE, [])

    assert result["decision"] == "cross_source_required"
    assert result["review_state"] == "needs_review"
    assert "single_still_seam_claim" in result["contradiction_flags"]


def test_multidate_validation_keeps_near_epoch_review_only():
    result = validate_candidate_across_dates(
        BASE_CANDIDATE,
        [
            {
                "imagery_epoch": "2024-02",
                "capture_datetime_utc": "2024-02-01T00:00:00Z",
                "geometry_match_score": 0.95,
                "radiometric_match_score": 0.95,
            }
        ],
    )

    assert result["epoch_class"] == "near_epoch"
    assert result["classification_hint"] == "probable_tile_seam"
    assert result["decision"] == "review"
    assert result["review_state"] == "needs_review"


def test_multidate_validation_single_cross_epoch_is_insufficient():
    # Hardened default (min_cross_epoch_comparisons=2): a single cross-epoch
    # comparison can no longer drive a persistence verdict.
    result = validate_candidate_across_dates(
        BASE_CANDIDATE,
        [
            {
                "imagery_epoch": "2022-01",
                "capture_datetime_utc": "2022-01-01T00:00:00Z",
                "geometry_match_score": 0.9,
                "radiometric_match_score": 0.8,
            }
        ],
    )

    assert result["epoch_class"] == "insufficient_cross_epoch"
    assert "single_still_seam_claim" in result["contradiction_flags"]


def test_multidate_validation_marks_disappearing_cross_epoch_boundary():
    result = validate_candidate_across_dates(
        BASE_CANDIDATE,
        [
            {
                "imagery_epoch": "2022-01",
                "capture_datetime_utc": "2022-01-01T00:00:00Z",
                "geometry_match_score": 0.1,
                "radiometric_match_score": 0.1,
            },
            {
                "imagery_epoch": "2021-06",
                "capture_datetime_utc": "2021-06-01T00:00:00Z",
                "geometry_match_score": 0.1,
                "radiometric_match_score": 0.1,
            },
        ],
    )

    assert result["epoch_class"] == "cross_epoch"
    assert result["classification_hint"] == "mixed_epoch_artifact"
    assert result["decision"] == "review"


def test_multidate_validation_marks_persistent_ground_feature_candidate():
    result = validate_candidate_across_dates(
        BASE_CANDIDATE,
        [
            {
                "imagery_epoch": "2022-01",
                "capture_datetime_utc": "2022-01-01T00:00:00Z",
                "geometry_match_score": 0.9,
                "radiometric_match_score": 0.8,
            },
            {
                "imagery_epoch": "2021-06",
                "capture_datetime_utc": "2021-06-01T00:00:00Z",
                "geometry_match_score": 0.9,
                "radiometric_match_score": 0.8,
            },
        ],
    )

    assert result["classification_hint"] == "probable_ground_feature"
    assert result["decision"] == "cross_source_required"
    assert result["multi_date_persistence"] >= 0.65
