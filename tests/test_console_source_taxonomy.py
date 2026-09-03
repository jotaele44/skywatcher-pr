from server.backend.console.source_taxonomy import (
    SOURCE_TAXONOMY_VERSION,
    build_provenance,
    normalize_observation,
)


def test_legacy_screenshot_maps_without_dropping_source_type():
    row = {
        "observation_id": "obs-1",
        "source_id": "screen-1",
        "source_type": "screenshot",
        "lineage_id": "lineage-1",
        "synthetic": False,
    }
    normalized = normalize_observation(row)
    assert normalized["source_type"] == "screenshot"
    assert normalized["source_family"] == "screenshot_evidence"
    assert normalized["source_method"] == "screenshot_ocr"
    assert normalized["data_rights"] == "user_supplied"
    assert normalized["source_taxonomy_version"] == SOURCE_TAXONOMY_VERSION


def test_synthetic_is_separated_from_evidence_family():
    provenance, flags = build_provenance(
        {
            "observation_id": "syn-1",
            "source_id": "fixture",
            "source_type": "screenshot",
            "lineage_id": "lin-1",
            "synthetic": True,
        }
    )
    assert provenance["source_family"] == "synthetic_test"
    assert provenance["data_rights"] == "synthetic"
    assert provenance["operational_mode"] == "batch"
    assert flags == []


def test_unknown_source_remains_explicit_and_flagged():
    provenance, flags = build_provenance(
        {
            "observation_id": "obs-unknown",
            "source_type": "mystery_feed",
            "lineage_id": "lin-unknown",
        }
    )
    assert provenance["source_family"] == "unknown"
    assert provenance["source_method"] == "unknown"
    assert provenance["data_rights"] == "unknown"
    assert provenance["operational_mode"] == "unknown"
    assert "unknown_source_type" in flags
