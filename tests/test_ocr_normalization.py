"""Gate: OCR observation normalization using synthetic OCR strings."""

from __future__ import annotations

from skywatcher.fr24 import ocr_normalization as ocn


def test_clean_returns_string():
    out = ocn.clean("N123AB\n\n  altitude 3500 ft ")
    assert isinstance(out, str)
    assert out  # non-empty


def test_confidence_score_in_unit_range():
    score = ocn.confidence_score({"callsign_or_label": "N123", "ocr_text": "N123"})
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0


def test_normalize_observation_attaches_confidence():
    rec = {"ocr_text": "N123AB (N123) H125", "region_type": "callsign", "ocr_status": "ok"}
    out = ocn.normalize_observation(rec)
    assert isinstance(out, dict)
    assert "confidence" in out
    assert 0.0 <= float(out["confidence"]) <= 1.0


def test_prohibited_label_vocabulary_present():
    # candidate-only policy: 'confirmed' must be a disallowed review status.
    assert "confirmed" in ocn.DISALLOWED_REVIEW_STATUSES
