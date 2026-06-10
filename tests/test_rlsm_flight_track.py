"""Tests for fr24/rlsm_flight_track.py — the heuristic flight-track classifier.

Tests are structural — they verify the classifier produces valid `path_shape`
enum values + the correct schema-mapped row shape. They do NOT assert
classification accuracy (no ground-truth labels exist).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


# ──────────────────────────────────────────────────────────────────────────
# Unit tests — the pure heuristic function (no SQLite, no FS)
# ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "observations,expected_shape,expected_hover",
    [
        # absent: no observations → absent, no hover
        ([], "absent", 0),
        # hover: a speed_kt = 0 → hover, has_hover = 1
        ([(0, 90)], "hover", 1),
        ([(0, None), (200, 180)], "hover", 1),
        # linear: positive speed + heading present → linear, no hover
        ([(120, 180)], "linear", 0),
        ([(80, 90), (140, 95)], "linear", 0),
        # multi: two observations with >= 30° heading delta → multi
        ([(100, 0), (100, 30)], "multi", 0),
        ([(120, 10), (140, 200)], "multi", 0),
        # multi: across the 0/360 wrap (350° vs 10° is a 20° delta → NOT multi)
        ([(120, 350), (140, 10)], "linear", 0),
        # multi: 340° vs 10° is a 30° wrap-around delta → multi
        ([(120, 340), (140, 10)], "multi", 0),
        # no useful signal (speed=None, heading=None) → absent
        ([(None, None)], "absent", 0),
        # has speed but no heading → still "absent" because linear needs both
        ([(120, None)], "absent", 0),
    ],
)
def test_classify_screenshot(observations, expected_shape, expected_hover):
    from fr24.rlsm_flight_track import _classify_screenshot
    shape, hover = _classify_screenshot(observations)
    assert shape == expected_shape, f"expected {expected_shape}, got {shape} for {observations}"
    assert hover == expected_hover, f"expected has_hover={expected_hover}, got {hover}"


# ──────────────────────────────────────────────────────────────────────────
# Integration test — the full run() against a hermetic in-memory DB
# ──────────────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_rlsm_db(tmp_path: Path, monkeypatch):
    """Build a tiny RLSM DB with 4 screenshots covering the 4 classifications."""
    db = tmp_path / "rlsm.sqlite"
    schema_path = Path(__file__).resolve().parents[1] / "data" / "rlsm" / "schema.sql"
    if not schema_path.exists():
        pytest.skip("data/rlsm/schema.sql not tracked")
    conn = sqlite3.connect(str(db))
    conn.executescript(schema_path.read_text())
    # 4 screenshots, all 'ok' for ingest
    for sid in (1, 2, 3, 4):
        conn.execute(
            "INSERT INTO screenshots (screenshot_id, sha256, filename, rel_path, ext, "
            "size_bytes, width, height, ingest_status, ingested_at) "
            "VALUES (?, ?, ?, ?, 'png', ?, ?, ?, 'ok', '2026-06-01T00:00:00Z')",
            (sid, f"sha{sid}", f"f{sid}.png", f"f{sid}.png", 1000, 800, 600),
        )
    # screenshot 1: hover (speed_kt=0)
    # screenshot 2: linear (positive speed + heading)
    # screenshot 3: multi (two observations, headings 0/180)
    # screenshot 4: absent (no aircraft_observations row at all)
    conn.execute(
        "INSERT INTO processing_runs (run_kind, started_at, status, n_inputs, n_processed, n_failed) "
        "VALUES ('test', '2026-06-01T00:00:00Z', 'completed', 0, 0, 0)"
    )
    test_run_id = conn.execute("SELECT MAX(run_id) FROM processing_runs").fetchone()[0]
    insert_aircraft = (
        "INSERT INTO aircraft_observations (screenshot_id, run_id, registration, identity_status, "
        "speed_kt, heading_deg, observed_at) VALUES (?, ?, ?, 'confirmed', ?, ?, '2026-06-01T00:00:00Z')"
    )
    conn.execute(insert_aircraft, (1, test_run_id, "N1AB", 0, 90))
    conn.execute(insert_aircraft, (2, test_run_id, "N2CD", 120, 180))
    conn.execute(insert_aircraft, (3, test_run_id, "N3EF", 100, 0))
    conn.execute(insert_aircraft, (3, test_run_id, "N3GH", 100, 180))
    # screenshot 4 deliberately has NO aircraft_observations rows
    conn.commit()
    conn.close()

    # Monkey-patch fr24.rlsm_flight_track.DB to the test path BEFORE importing run()
    import fr24.rlsm_flight_track as ft
    monkeypatch.setattr(ft, "DB", db)
    return db


def test_run_classifies_all_four_shapes(tmp_rlsm_db):
    from fr24.rlsm_flight_track import run
    snapshot = run(budget_sec=10.0)
    assert snapshot["processed"] == 4
    assert snapshot["targets"] == 4
    assert snapshot["failed"] == 0
    classifications = snapshot["classifications"]
    assert classifications.get("hover") == 1
    assert classifications.get("linear") == 1
    assert classifications.get("multi") == 1
    assert classifications.get("absent") == 1


def test_run_is_idempotent(tmp_rlsm_db):
    """A second run() must classify zero new screenshots — the NOT EXISTS guard works."""
    from fr24.rlsm_flight_track import run
    first = run(budget_sec=10.0)
    second = run(budget_sec=10.0)
    assert first["processed"] == 4
    assert second["processed"] == 0
    assert second["targets"] == 0


def test_run_writes_schema_compliant_rows(tmp_rlsm_db):
    """Verify the inserted rows obey the schema's path_shape enum + confidence range."""
    from fr24.rlsm_flight_track import run, HEURISTIC_CONFIDENCE
    run(budget_sec=10.0)
    conn = sqlite3.connect(str(tmp_rlsm_db))
    rows = conn.execute(
        "SELECT path_shape, has_hover, confidence FROM flight_track_features ORDER BY screenshot_id"
    ).fetchall()
    conn.close()
    # 4 screenshots → 4 rows
    assert len(rows) == 4
    valid_shapes = {"linear", "curve", "loop", "orbit", "hover", "gap", "multi", "absent"}
    for shape, has_hover, confidence in rows:
        assert shape in valid_shapes, f"invalid path_shape: {shape}"
        assert has_hover in (0, 1)
        assert 0.0 <= confidence <= 1.0, f"confidence out of [0,1]: {confidence}"
        # All classifications come from the heuristic, so confidence should be the constant
        assert confidence == HEURISTIC_CONFIDENCE


def test_processing_runs_row_recorded(tmp_rlsm_db):
    """Verify the runner emits a processing_runs row with run_kind='flight_track'."""
    from fr24.rlsm_flight_track import run
    run(budget_sec=10.0)
    conn = sqlite3.connect(str(tmp_rlsm_db))
    rows = conn.execute(
        "SELECT run_kind, status, n_processed FROM processing_runs WHERE run_kind='flight_track'"
    ).fetchall()
    conn.close()
    assert len(rows) == 1
    kind, status, n_processed = rows[0]
    assert kind == "flight_track"
    assert status == "completed"
    assert n_processed == 4
