import csv
from pathlib import Path

from satim_tile_seam_classifier import (
    TILE_SEAM_CANDIDATE,
    TILE_SEAM_INSUFFICIENT,
    TILE_SEAM_PROBABLE,
    TileSeamEvidence,
    classify_tile_seam,
    evidence_from_mapping,
)


LEDGER = Path("data/calibration/satim_tile_seam_cases.csv")


def test_samaritans_purse_case_classifies_as_tile_seam_probable():
    with LEDGER.open(newline="", encoding="utf-8") as handle:
        row = next(csv.DictReader(handle))

    evidence = evidence_from_mapping(row)
    decision = classify_tile_seam(evidence)

    assert row["case_id"] == "SATIM_TILE_SEAM_SAMARITANS_PURSE_001"
    assert decision["label"] == TILE_SEAM_PROBABLE
    assert decision["artifact_confidence"] == "MEDIUM_HIGH"
    assert decision["ground_feature_confidence"] == "LOW"
    assert decision["privacy_status"] == "DERIVED_FIXTURE_ONLY"


def test_two_positive_flags_remain_candidate_not_locked_probable():
    decision = classify_tile_seam(
        TileSeamEvidence(
            crosses_landcover_classes=True,
            persists_across_zoomed_frames=True,
        )
    )

    assert decision["label"] == TILE_SEAM_CANDIDATE
    assert decision["artifact_confidence"] == "MEDIUM"


def test_physical_geometry_contradiction_prevents_probable_lock():
    decision = classify_tile_seam(
        TileSeamEvidence(
            crosses_landcover_classes=True,
            persists_across_zoomed_frames=True,
            roof_or_object_texture_split=True,
            object_anchors_consistent=True,
            follows_physical_geometry=True,
        )
    )

    assert decision["label"] == TILE_SEAM_CANDIDATE
    assert decision["contradiction_score"] == 1


def test_raw_coordinate_release_blocks_public_fixture():
    decision = classify_tile_seam(
        TileSeamEvidence(
            crosses_landcover_classes=True,
            persists_across_zoomed_frames=True,
            roof_or_object_texture_split=True,
            object_anchors_consistent=True,
            raw_coordinate_released=True,
        )
    )

    assert decision["label"] == TILE_SEAM_INSUFFICIENT
    assert decision["privacy_status"] == "BLOCK_RAW_COORDINATE_RELEASE"
