from fr24.calibration.l4_registry_audit import audit_rows, registry_tokens


def test_registry_tokens_from_mapping():
    tokens = registry_tokens({"REG1": {"registration": "REG1", "operator": "Agency"}})
    assert "REG1" in tokens
    assert "AGENCY" in tokens


def test_l4_audit_rows_finds_candidate_after_three_sightings():
    rows = [
        {"registration": "REG9", "callsign": "A", "operator": "Sample"},
        {"registration": "REG9", "callsign": "A", "operator": "Sample"},
        {"registration": "REG9", "callsign": "A", "operator": "Sample"},
    ]
    metrics = audit_rows(rows, registry={"REG1": {"registration": "REG1"}})
    assert metrics["record_count"] == 3
    assert metrics["onboarding_candidates"][0]["key"] == "REG9"
