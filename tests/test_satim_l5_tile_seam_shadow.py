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
