from fr24.calibration.l5_tile_seam_shadow_calibration import classify_candidate_strict


BASE = {
    "straightness": 0.95,
    "radiometric_delta": 0.90,
    "dem_hillshade_alignment": 0.0,
    "shadow_mask_intersection": 0.0,
    "multi_date_persistence": 0.0,
    "infrastructure_alignment": 0.0,
    "track_line_overlap": 0.0,
    "ui_overlay_overlap": 0.0,
}


def test_screen_lock_promotes_viewport_artifact_not_display_tile_edge():
    out = classify_candidate_strict(
        {**BASE, "screen_locked_score": 0.95, "ground_fixed_score": 0.0}
    )

    assert out["decision"] == "probable_viewport_artifact"
    assert out["resolved_origin"] == "VIEWPORT_COMPOSITING_ARTIFACT"


def test_provider_tile_grid_binding_is_required_for_display_tile_edge():
    out = classify_candidate_strict(
        {
            **BASE,
            "screen_locked_score": 0.0,
            "ground_fixed_score": 0.8,
            "provider_tile_grid_binding_score": 0.9,
        }
    )

    assert out["decision"] == "probable_display_tile_edge"
    assert out["resolved_origin"] == "DISPLAY_TILE_EDGE"


def test_ground_fixed_non_grid_zoom_persistence_is_only_provisional_mosaic_without_metadata():
    out = classify_candidate_strict(
        {
            **BASE,
            "ground_fixed_score": 0.9,
            "provider_tile_grid_binding_score": 0.0,
            "adjacent_zoom_ground_persistence_score": 0.9,
        }
    )

    assert out["decision"] == "probable_source_mosaic_cutline"
    assert out["origin_state"] == "PROVISIONAL"
    assert out["resolved_origin"] == "UNRESOLVED"


def test_source_mosaic_metadata_can_close_mosaic_origin():
    out = classify_candidate_strict(
        {
            **BASE,
            "ground_fixed_score": 0.9,
            "provider_tile_grid_binding_score": 0.0,
            "adjacent_zoom_ground_persistence_score": 0.9,
            "source_mosaic_metadata_binding_score": 0.95,
        }
    )

    assert out["decision"] == "probable_source_mosaic_cutline"
    assert out["origin_state"] == "PASS"
    assert out["resolved_origin"] == "SOURCE_MOSAIC_CUTLINE"


def test_physical_ground_identity_requires_independent_binding():
    out = classify_candidate_strict(
        {**BASE, "independent_ground_feature_binding_score": 0.95}
    )

    assert out["resolved_origin"] == "PHYSICAL_GROUND_FEATURE"
