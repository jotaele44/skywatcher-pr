"""Gate: mission classification is speculative-until-evidence-gated."""

from __future__ import annotations

from skywatcher.fr24 import mission_classification as mc


def test_below_threshold_is_speculative():
    r = mc.classify("patrol", 0.5)
    assert r.status == "highly_speculative"


def test_above_threshold_is_evidence_gated():
    r = mc.classify("patrol", 0.95)
    assert r.status == "evidence_gated"


def test_at_threshold_stays_speculative():
    r = mc.classify("patrol", mc.HIGH_THRESHOLD)
    assert r.status == "highly_speculative"  # strictly-greater gate


def test_score_is_clamped():
    assert mc.classify("x", 5.0).evidence_score == 1.0
    assert mc.classify("x", -1.0).evidence_score == 0.0


def test_gate_never_emits_confirmed():
    for score in (0.0, 0.5, 0.86, 1.0):
        assert mc.classify("x", score).status in ("highly_speculative", "evidence_gated")
        assert mc.classify("x", score).status != "confirmed"
