"""Tests for screenshots table columns including new evidence-chain fields."""

import sqlite3


def test_screenshots_table_has_required_columns(populated_db):
    conn = sqlite3.connect(populated_db)
    cursor = conn.execute("PRAGMA table_info(screenshots)")
    cols = {row[1] for row in cursor.fetchall()}
    conn.close()

    required = {
        "screenshot_id", "image_path", "flight_id", "processed_at",
        "callsign", "altitude_ft", "ground_speed_mph",
        "latitude", "longitude", "timestamp", "raw_text", "ocr_confidence",
        "sha256", "coordinate_method", "coordinate_confidence",
        "estimated_error_m", "review_status",
    }
    missing = required - cols
    assert not missing, f"Missing columns: {missing}"


def test_screenshots_count_per_flight(populated_db):
    conn = sqlite3.connect(populated_db)
    rows = conn.execute(
        "SELECT flight_id, COUNT(*) as cnt FROM screenshots GROUP BY flight_id"
    ).fetchall()
    conn.close()
    for flight_id, cnt in rows:
        assert cnt == 3, f"{flight_id} has {cnt} screenshots, expected 3"


def test_screenshots_have_coordinate_method(populated_db):
    conn = sqlite3.connect(populated_db)
    rows = conn.execute(
        "SELECT coordinate_method FROM screenshots WHERE coordinate_method IS NOT NULL"
    ).fetchall()
    conn.close()
    assert len(rows) > 0


def test_screenshots_review_status_default(populated_db):
    conn = sqlite3.connect(populated_db)
    rows = conn.execute(
        "SELECT review_status FROM screenshots"
    ).fetchall()
    conn.close()
    for (status,) in rows:
        assert status in ("pending", None), f"Unexpected status: {status}"
