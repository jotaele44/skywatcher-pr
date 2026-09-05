from satim_tile_seam_classifier import (
    ORIGIN_DISPLAY_TILE_EDGE,
    ORIGIN_PHYSICAL_GROUND_FEATURE,
    ORIGIN_SOURCE_MOSAIC_CUTLINE,
    ORIGIN_UNRESOLVED,
    ORIGIN_VIEWPORT_COMPOSITING_ARTIFACT,
    STATE_BLOCKED,
    STATE_FAIL,
    STATE_PASS,
    STATE_PROVISIONAL,
    TILE_SEAM_PROBABLE,
    TileSeamEvidence,
    classify_seam_origin,
    classify_tile_seam,
)


def test_single_still_cannot_resolve_causal_origin():
    out = classify_seam_origin(TileSeamEvidence(radiometric_discontinuity=True))

    assert out["resolved_origin"] == ORIGIN_UNRESOLVED
    assert out["origin_candidates"][ORIGIN_SOURCE_MOSAIC_CUTLINE]["state"] == STATE_BLOCKED
    assert out["origin_candidates"][ORIGIN_DISPLAY_TILE_EDGE]["state"] == STATE_BLOCKED


def test_ground_fixed_non_grid_zoom_persistent_is_only_provisional_source_mosaic():
    out = classify_seam_origin(
        TileSeamEvidence(
            radiometric_discontinuity=True,
            ground_fixed_under_pan=True,
            provider_tile_grid_binding=False,
            persists_across_adjacent_zoom_levels=True,
            independent_ground_feature_binding=False,
            screen_fixed_under_pan=False,
        )
    )

    assert out["resolved_origin"] == ORIGIN_UNRESOLVED
    assert out["origin_candidates"][ORIGIN_SOURCE_MOSAIC_CUTLINE]["state"] == STATE_PROVISIONAL
    assert out["origin_candidates"][ORIGIN_DISPLAY_TILE_EDGE]["state"] == STATE_FAIL


def test_provider_grid_binding_can_resolve_display_tile_edge():
    out = classify_seam_origin(
        TileSeamEvidence(
            radiometric_discontinuity=True,
            provider_tile_grid_binding=True,
            screen_fixed_under_pan=False,
            independent_ground_feature_binding=False,
        )
    )

    assert out["resolved_origin"] == ORIGIN_DISPLAY_TILE_EDGE
    assert out["origin_candidates"][ORIGIN_DISPLAY_TILE_EDGE]["state"] == STATE_PASS


def test_screen_fixed_is_viewport_not_tile_edge():
    out = classify_seam_origin(
        TileSeamEvidence(
            radiometric_discontinuity=True,
            screen_fixed_under_pan=True,
            ground_fixed_under_pan=False,
        )
    )

    assert out["resolved_origin"] == ORIGIN_VIEWPORT_COMPOSITING_ARTIFACT
    assert out["origin_candidates"][ORIGIN_DISPLAY_TILE_EDGE]["state"] == STATE_FAIL


def test_independent_ground_binding_overrides_heuristic_artifact_promotion():
    out = classify_seam_origin(
        TileSeamEvidence(
            radiometric_discontinuity=True,
            ground_fixed_under_pan=True,
            provider_tile_grid_binding=False,
            persists_across_adjacent_zoom_levels=True,
            independent_ground_feature_binding=True,
        )
    )

    assert out["resolved_origin"] == ORIGIN_PHYSICAL_GROUND_FEATURE
    assert out["origin_candidates"][ORIGIN_SOURCE_MOSAIC_CUTLINE]["state"] == STATE_FAIL


def test_conflicting_artifact_and_ground_bindings_are_preserved():
    out = classify_seam_origin(
        TileSeamEvidence(
            radiometric_discontinuity=True,
            source_mosaic_metadata_binding=True,
            independent_ground_feature_binding=True,
        )
    )

    assert out["resolved_origin"] == ORIGIN_PHYSICAL_GROUND_FEATURE
    assert "artifact_vs_physical_ground_binding" in out["contradictions"]


def test_legacy_visual_label_never_resolves_origin_by_itself():
    out = classify_tile_seam(
        TileSeamEvidence(
            crosses_landcover_classes=True,
            persists_across_zoomed_frames=True,
            roof_or_object_texture_split=True,
            object_anchors_consistent=True,
            radiometric_discontinuity=True,
        )
    )

    assert out["label"] == TILE_SEAM_PROBABLE
    assert out["resolved_origin"] == ORIGIN_UNRESOLVED
