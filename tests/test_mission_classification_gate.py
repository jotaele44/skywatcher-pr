"""Gate: mission/intent inference is quarantined from active PITIRRE use."""

from __future__ import annotations

import pytest

from skywatcher.fr24 import mission_classification as mc


def test_active_classification_fails_closed():
    with pytest.raises(mc.MissionInferenceProhibitedError):
        mc.classify("patrol", 0.95)


def test_legacy_replay_requires_explicit_opt_in():
    result = mc.classify("patrol", 0.95, legacy_compat=True)
    assert result.status == "evidence_gated"
    assert result.active_use_allowed is False
    assert result.canonical_state == "LEGACY_QUARANTINED"


def test_legacy_replay_preserves_historical_threshold_semantics():
    below = mc.classify("patrol", 0.5, legacy_compat=True)
    at_gate = mc.classify("patrol", mc.HIGH_THRESHOLD, legacy_compat=True)
    above = mc.classify("patrol", 0.95, legacy_compat=True)
    assert below.status == "highly_speculative"
    assert at_gate.status == "highly_speculative"
    assert above.status == "evidence_gated"


def test_legacy_score_is_clamped_without_becoming_canonical():
    hi = mc.classify("x", 5.0, legacy_compat=True)
    lo = mc.classify("x", -1.0, legacy_compat=True)
    assert hi.evidence_score == 1.0
    assert lo.evidence_score == 0.0
    assert hi.active_use_allowed is False
    assert lo.active_use_allowed is False


def test_legacy_gate_never_emits_confirmed_or_active():
    for score in (0.0, 0.5, 0.86, 1.0):
        result = mc.classify("x", score, legacy_compat=True)
        assert result.status in ("highly_speculative", "evidence_gated")
        assert result.status != "confirmed"
        assert result.active_use_allowed is False
        assert result.canonical_state == "LEGACY_QUARANTINED"
