"""Coverage-gate caps for the shared confidence helper (skill coverage-gates.md)."""

from skywatcher.core.confidence import (
    GRADES,
    float_to_grade,
    grade,
    grade_to_float,
)


def _ord(g):
    return GRADES.index(g)


def test_ground_truth_reaches_verified():
    g = grade(observation_count=10, is_ground_truth=True)
    assert g.confidence_grade == "VERIFIED"
    assert g.evidence_tier == "T1"


def test_no_denominator_capped_below_high():
    g = grade(observation_count=50, denominator=None)
    assert _ord(g.confidence_grade) <= _ord("MODERATE")


def test_strong_recurrence_with_denominator_can_reach_high():
    g = grade(observation_count=8, denominator=10)
    assert g.confidence_grade == "HIGH"


def test_spatial_without_georef_capped():
    g = grade(observation_count=8, denominator=10, is_spatial=True, has_georef=False)
    assert _ord(g.confidence_grade) <= _ord("MODERATE")
    assert "no_georef_spatial_capped" in g.caps_applied


def test_no_source_context_capped_low():
    g = grade(observation_count=8, denominator=10, has_source_context=False)
    assert _ord(g.confidence_grade) <= _ord("LOW")
    assert "no_source_context_capped" in g.caps_applied


def test_weak_evidence_is_low():
    assert grade(observation_count=1, denominator=40).confidence_grade == "LOW"
    assert grade(observation_count=0, denominator=40).confidence_grade == "INSUFFICIENT"


def test_float_grade_reconciliation_roundtrips_ordering():
    prev = -1.0
    for g in GRADES:
        f = grade_to_float(g)
        assert f > prev, "grade floats must increase with grade strength"
        prev = f
    assert float_to_grade(0.95) == "VERIFIED"
    assert float_to_grade(0.10) == "INSUFFICIENT"
