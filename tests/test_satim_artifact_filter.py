from satim_artifact_filter import (
    ArtifactClass,
    ArtifactLink,
    ArtifactObservation,
    ArtifactSignal,
    NON_DESTRUCTIVE_CONFIDENCE_PATCH_STATUS,
    artifact_filter_schema,
    build_artifact_filter_ledger,
    build_detector_confidence_patch,
    score_artifact_observation,
)


def artifact_fixture() -> ArtifactObservation:
    return ArtifactObservation(
        artifact_id="SATIM-ARTIFACT-PR771-001",
        grid_id="PR-BARRANQUITAS-PR771-RIO_GRANDE_DE_MANATI",
        source_id="SATIM_CUT_FILL_LEDGER:SATIM-CUT-FILL-PR771-001",
        timestamp_local="2026-06-29T15:00:00-04:00",
        signals={
            ArtifactSignal.TILE_SEAM: 1.0,
            ArtifactSignal.ORTHO_MOSAIC_BOUNDARY: 1.0,
            ArtifactSignal.BLUR_EDGE: 0.6,
            ArtifactSignal.EPOCH_MISMATCH: 0.5,
            ArtifactSignal.COLOR_BALANCE_SHIFT: 1.0,
            ArtifactSignal.PARALLAX_OFFSET: 0.0,
            ArtifactSignal.CROSSES_UNRELATED_TERRAIN: 1.0,
            ArtifactSignal.CANDIDATE_BOUNDARY_COINCIDENCE: 1.0,
        },
        classes=(ArtifactClass.IMAGERY_ARTIFACT,),
        links={
            ArtifactLink.PATCHWORK_POI: True,
            ArtifactLink.ROAD_END_NODE: True,
            ArtifactLink.CUT_FILL_FEATURE: True,
        },
        patchwork_poi_id="SATIM-PR771-BARRANQUITAS-001",
        road_end_node_id="SATIM-ROAD-END-PR771-001",
        cut_fill_feature_id="SATIM-CUT-FILL-PR771-001",
        original_detector_score=0.82,
        notes="Regression fixture linked to patchwork, road-end, and cut/fill outputs.",
    )


def test_schema_contains_required_signals_and_guardrail():
    schema = artifact_filter_schema()

    assert schema["filter"] == "SATIM_TILE_SEAM_AND_MOSAIC_ARTIFACT_FILTER_v1"
    assert schema["guardrail"] == NON_DESTRUCTIVE_CONFIDENCE_PATCH_STATUS
    assert "TILE_SEAM" in schema["signals"]
    assert "ORTHO_MOSAIC_BOUNDARY" in schema["signals"]
    assert "BLUR_EDGE" in schema["signals"]
    assert "EPOCH_MISMATCH" in schema["signals"]
    assert "COLOR_BALANCE_SHIFT" in schema["signals"]
    assert "PARALLAX_OFFSET" in schema["signals"]
    assert "REVIEW_REQUIRED" in schema["classes"]


def test_fixture_scores_artifact_and_preserves_detector_score():
    score = score_artifact_observation(artifact_fixture())

    assert score.artifact_score == 0.99
    assert score.linkage_score == 0.15
    assert score.combined_artifact_score == 1.0
    assert score.confidence_band == "HIGH"
    assert score.patch_status == NON_DESTRUCTIVE_CONFIDENCE_PATCH_STATUS
    assert score.non_destructive_patch is True
    assert score.original_detector_score == 0.82
    assert score.adjusted_detector_score == 0.41
    assert score.linked_evidence == ("CUT_FILL_FEATURE", "PATCHWORK_POI", "ROAD_END_NODE")


def test_artifact_filter_ledger_retains_candidate_and_provenance():
    rows = build_artifact_filter_ledger([artifact_fixture()])

    assert len(rows) == 1
    row = rows[0]
    assert row["artifact_id"] == "SATIM-ARTIFACT-PR771-001"
    assert row["non_destructive_patch"] is True
    assert row["original_detector_score"] == 0.82
    assert row["adjusted_detector_score"] == 0.41
    assert row["signal_contributions"]["TILE_SEAM"] == 0.25
    assert row["cut_fill_feature_id"] == "SATIM-CUT-FILL-PR771-001"
    assert "IMAGERY_ARTIFACT" in row["classes"]


def test_detector_confidence_patch_is_non_destructive():
    rows = build_detector_confidence_patch([artifact_fixture()])

    assert len(rows) == 1
    row = rows[0]
    assert row["original_detector_score"] == 0.82
    assert row["adjusted_detector_score"] == 0.41
    assert row["provenance_rule"] == "artifact_score and original_detector_score remain separable"
    assert row["mutation_rule"] == "candidate retained; emit confidence patch only"
    assert row["patch_status"] == NON_DESTRUCTIVE_CONFIDENCE_PATCH_STATUS
