"""Gate: telemetry field parsing using synthetic values."""

from __future__ import annotations

from skywatcher.fr24 import telemetry_parser as tp


def test_parser_version_is_versioned():
    assert isinstance(tp.PARSER_VERSION, str)
    assert tp.PARSER_VERSION.count(".") >= 1


def test_parse_callsign_region():
    rec = {
        "ocr_text": "N123AB (N123)",
        "region_type": "callsign",
        "ocr_char_count": 20,
        "ocr_status": "ok",
    }
    row = tp.parse_telemetry(rec)
    assert row["parser_version"] == tp.PARSER_VERSION
    assert row["callsign_or_label"]  # extracted a non-empty label


def test_parse_altitude_region():
    rec = {
        "ocr_text": "3,500 ft",
        "region_type": "altitude",
        "ocr_char_count": 20,
        "ocr_status": "ok",
    }
    row = tp.parse_telemetry(rec)
    assert row["barometric_altitude_ft"]  # extracted an altitude value


def test_failed_ocr_marks_review_status():
    rec = {"ocr_text": "", "region_type": "callsign", "ocr_status": "failed"}
    row = tp.parse_telemetry(rec)
    assert row["review_status"] == "region_ocr_failed"


def test_values_disagree_helper():
    assert tp.values_disagree("N1", "N2")
    assert not tp.values_disagree("N1", "N1")
