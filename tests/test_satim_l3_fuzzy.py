"""L3 fuzzy scoring is opt-in: the default path is exact-match (unchanged);
fuzzy mode awards OCR-confusable + single-edit credit."""

from __future__ import annotations

from fr24.calibration import l3_ocr_scoring as l3


def _truth(callsign):
    return {"image_path": "img1.png", "callsign": callsign}


def test_default_is_exact_match():
    # 'N1O5' (letter O) vs 'N105' (zero) — a confusable near-miss.
    assert l3.compare_field("callsign", _truth("N1O5"), {"callsign": "N105"}) is False


def test_fuzzy_credits_confusable():
    assert l3.compare_field("callsign", _truth("N1O5"), {"callsign": "N105"}, fuzzy=True) is True


def test_fuzzy_credits_single_edit():
    assert l3.compare_field("callsign", _truth("N12345"), {"callsign": "N12346"}, fuzzy=True) is True


def test_fuzzy_still_rejects_far_values():
    assert l3.compare_field("callsign", _truth("N12345"), {"callsign": "XYZ99"}, fuzzy=True) is False


def test_altitude_never_fuzzy():
    # integers: a wrong digit is a wrong number even in fuzzy mode
    assert l3.compare_field("altitude_ft", {"altitude_ft": "3500"}, {"altitude_ft": "3600"}, fuzzy=True) is False


def test_score_records_mode_flag():
    rows = [{"image_path": "img1.png", "callsign": "N1O5"}]
    preds = {"img1.png": {"callsign": "N105"}}
    exact = l3.score_records(rows, preds, fuzzy=False)
    fuzzy = l3.score_records(rows, preds, fuzzy=True)
    assert exact["field_scores"]["callsign"] == 0.0
    assert fuzzy["field_scores"]["callsign"] == 1.0
