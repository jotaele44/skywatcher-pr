from fr24.calibration.l5_tile_seam_shadow_calibration import classify_candidate, summarize


def test_l5_classifies_linear_artifact():
    result = classify_candidate({
        "straight_boundary_score": 1,
        "radiometric_discontinuity_score": 1,
        "cloud_mask_intersection": 0,
        "shadow_mask_intersection": 0,
        "dem_hillshade_alignment": 0,
        "multi_date_persistence": 0,
        "infrastructure_alignment": 0,
    })
    assert result["decision"] == "probable_tile_seam"
    assert result["tile_seam_likelihood"] >= 0.75


def test_l5_summarize_counts_decisions():
    summary = summarize([
        {"decision": "probable_tile_seam"},
        {"decision": "indeterminate"},
    ])
    assert summary["candidate_count"] == 2
    assert summary["decision_counts"]["probable_tile_seam"] == 1


def test_l5_does_not_promote_right_angle_alone():
    result = classify_candidate({
        "right_angle_score": 1,
        "straight_boundary_score": 0,
        "radiometric_discontinuity_score": 0,
        "texture_discontinuity_score": 0,
        "rectangular_patch_score": 0,
        "dem_hillshade_alignment": 0.5,
        "multi_date_persistence": 0.5,
    })
    assert result["decision"] == "indeterminate"
    assert result["tile_seam_likelihood"] < 0.55
    assert result["orthogonal_artifact_score"] == 1


def test_l5_promotes_orthogonal_tile_seam_with_multiple_signals():
    result = classify_candidate({
        "right_angle_score": 1,
        "straight_boundary_score": 1,
        "rectangular_patch_score": 1,
        "radiometric_discontinuity_score": 1,
        "texture_discontinuity_score": 0.8,
        "dem_hillshade_alignment": 0,
        "multi_date_persistence": 0,
        "cloud_mask_intersection": 0,
        "shadow_mask_intersection": 0,
    })
    assert result["decision"] == "probable_tile_seam"
    assert result["tile_seam_likelihood"] >= 0.55
    assert result["tile_corroborating_signal_count"] >= 2


def test_l5_context_marks_explainable_infrastructure():
    result = classify_candidate({
        "right_angle_score": 1,
        "straight_boundary_score": 1,
        "rectangular_patch_score": 1,
        "radiometric_discontinuity_score": 0.8,
        "utility_plant_alignment": 1,
        "multi_date_persistence": 0.7,
        "dem_hillshade_alignment": 0,
    })
    assert result["decision"] == "explainable_infrastructure"
    assert result["context_suppression_score"] == 1
