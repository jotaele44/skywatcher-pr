"""Tests for OCR confidence thresholds in screenshots."""

import sqlite3


def test_ocr_confidence_range(populated_db):
    conn = sqlite3.connect(populated_db)
    rows = conn.execute(
        "SELECT screenshot_id, ocr_confidence FROM screenshots WHERE ocr_confidence IS NOT NULL"
    ).fetchall()
    conn.close()
    assert len(rows) > 0
    for ss_id, conf in rows:
        assert 0.0 <= conf <= 1.0, f"{ss_id}: ocr_confidence {conf} out of range"


def test_ocr_confidence_not_all_zero(populated_db):
    conn = sqlite3.connect(populated_db)
    nonzero = conn.execute(
        "SELECT COUNT(*) FROM screenshots WHERE ocr_confidence > 0"
    ).fetchone()[0]
    conn.close()
    assert nonzero > 0, "All OCR confidences are zero"


def test_coordinate_confidence_range(populated_db):
    conn = sqlite3.connect(populated_db)
    rows = conn.execute(
        "SELECT screenshot_id, coordinate_confidence FROM screenshots "
        "WHERE coordinate_confidence IS NOT NULL"
    ).fetchall()
    conn.close()
    for ss_id, conf in rows:
        assert 0.0 <= conf <= 1.0, f"{ss_id}: coordinate_confidence {conf} out of range"


def test_estimated_error_m_positive(populated_db):
    conn = sqlite3.connect(populated_db)
    rows = conn.execute(
        "SELECT screenshot_id, estimated_error_m FROM screenshots "
        "WHERE estimated_error_m IS NOT NULL"
    ).fetchall()
    conn.close()
    for ss_id, err in rows:
        assert err >= 0, f"{ss_id}: estimated_error_m {err} is negative"
