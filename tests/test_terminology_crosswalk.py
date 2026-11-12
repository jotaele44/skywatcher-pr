"""Regression tests for non-destructive terminology compatibility."""
from skywatcher.core.terminology_crosswalk import (
    CERTIFICATION_STATES,
    EVIDENCE_STATES,
    resolve_term,
)


def test_all_governing_evidence_states_remain_canonical():
    for value in EVIDENCE_STATES:
        resolved = resolve_term(value, "evidence")
        assert (resolved.status, resolved.normalized) == ("CANONICAL", value)


def test_all_governing_certification_states_remain_canonical():
    for value in CERTIFICATION_STATES:
        resolved = resolve_term(value, "certification")
        assert (resolved.status, resolved.normalized) == ("CANONICAL", value)


def test_display_alias_does_not_automatically_certify():
    resolved = resolve_term("DERIVED", "evidence")
    assert resolved.normalized == "COMPUTED"
    assert resolved.status == "ALIAS_REQUIRES_REVIEW"
    assert resolved.original == "DERIVED"


def test_verified_is_not_automatically_pass():
    resolved = resolve_term("VERIFIED", "certification")
    assert resolved.normalized is None
    assert resolved.status == "UNRESOLVED"


def test_rejected_is_not_automatically_fail():
    resolved = resolve_term("REJECTED", "certification")
    assert resolved.normalized is None
    assert resolved.status == "UNRESOLVED"


def test_unknown_input_preserved():
    resolved = resolve_term(" covert ", "certification")
    assert resolved.original == " covert "
    assert resolved.normalized is None
    assert resolved.status == "UNRESOLVED"
