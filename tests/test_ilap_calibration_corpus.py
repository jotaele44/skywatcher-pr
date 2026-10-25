from scripts.validate_ilap_calibration_corpus import validate


def _row(record_id: str, lineage: str, split: str, sha: str = "a" * 64):
    return {
        "record_id": record_id,
        "source_lineage_id": lineage,
        "manifestation": record_id,
        "class_family": "test",
        "class_label": "TEST_CLASS",
        "label_state": "ANALYST_LABEL",
        "independent_binding_state": "UNRESOLVED",
        "split_state": split,
        "sha256": sha,
        "status": "ACQUIRED_SEED",
        "notes": "",
    }


def test_same_source_lineage_cannot_cross_train_validation_test():
    result = validate([
        _row("A", "LINEAGE-1", "TRAIN", "a" * 64),
        _row("B", "LINEAGE-1", "TEST", "b" * 64),
    ])
    assert result["status"] == "FAIL"
    assert any("source-lineage leakage" in e for e in result["errors"])


def test_duplicate_bytes_are_reported_not_silently_treated_independent():
    result = validate([
        _row("A", "LINEAGE-1", "UNASSIGNED", "a" * 64),
        _row("B", "LINEAGE-1", "UNASSIGNED", "a" * 64),
    ])
    assert result["status"] == "PASS"
    assert "a" * 64 in result["duplicate_byte_groups"]


def test_excluded_rights_rows_do_not_create_split_leakage():
    result = validate([
        _row("A", "LINEAGE-1", "EXCLUDED_PENDING_RIGHTS", "a" * 64),
        _row("B", "LINEAGE-1", "EXCLUDED_PENDING_RIGHTS", "b" * 64),
    ])
    assert result["status"] == "PASS"


def test_unknown_split_fails_closed():
    result = validate([_row("A", "LINEAGE-1", "MAYBE")])
    assert result["status"] == "FAIL"
