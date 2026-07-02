from fr24.calibration.satim_gis_overlay import overlay_score_patch_from_metrics, patch_candidate_with_gis_scores


def test_overlay_score_patch_from_metrics_normalizes_gis_fields():
    patch = overlay_score_patch_from_metrics({
        "road_overlap_fraction": 1.2,
        "building_overlap_fraction": 0.4,
        "airport_overlap_fraction": 0.8,
        "parcel_edge_alignment": -1,
        "terrain_crossing": 0.5,
        "coastal_crossing_score": 0.7,
        "landcover_persistence": 0.9,
    })

    assert patch["road_alignment"] == 1.0
    assert patch["building_alignment"] == 0.4
    assert patch["airport_alignment"] == 0.8
    assert patch["parcel_alignment"] == 0.0
    assert patch["coastal_crossing_score"] == 0.7


def test_patch_candidate_with_gis_scores_flags_infrastructure_explanation():
    candidate = {
        "classification": "probable_tile_seam",
        "review_state": "unreviewed",
        "feature_scores": {},
        "contradiction_flags": [],
    }
    patched = patch_candidate_with_gis_scores(candidate, {
        "road_alignment": 1.0,
        "building_alignment": 1.0,
        "airport_alignment": 1.0,
        "parcel_alignment": 1.0,
    })

    assert patched["feature_scores"]["infrastructure_alignment"] == 1.0
    assert patched["review_state"] == "needs_review"
    assert "infrastructure_explains_boundary" in patched["contradiction_flags"]
