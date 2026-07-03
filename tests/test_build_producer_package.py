"""Tests for scripts/build_producer_package.py (FR24 DB -> producer package)."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BUILDER = REPO_ROOT / "scripts" / "build_producer_package.py"
VALIDATOR = REPO_ROOT / "scripts" / "validate_airspace_export.py"


def _make_fixture_db(path: Path, rows: list[dict]) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute(
        """
        CREATE TABLE screenshots (
            screenshot_id TEXT PRIMARY KEY,
            image_path TEXT,
            flight_id TEXT,
            processed_at TEXT,
            callsign TEXT,
            altitude_ft INTEGER,
            ground_speed_mph INTEGER,
            latitude REAL,
            longitude REAL,
            timestamp TEXT,
            raw_text TEXT,
            ocr_confidence REAL,
            sha256 TEXT,
            coordinate_method TEXT,
            coordinate_confidence REAL,
            estimated_error_m REAL,
            review_status TEXT DEFAULT 'pending'
        )
        """
    )
    for row in rows:
        keys = sorted(row)
        conn.execute(
            f"INSERT INTO screenshots ({','.join(keys)}) VALUES ({','.join('?' * len(keys))})",
            [row[k] for k in keys],
        )
    conn.commit()
    conn.close()


FIXTURE_ROWS = [
    {
        "screenshot_id": "fix-0001",
        "image_path": "fixtures/fix-0001.png",
        "flight_id": "FL123",
        "processed_at": "2026-06-01T12:00:00Z",
        "callsign": "N123AB",
        "altitude_ft": 4500,
        "latitude": 18.44,
        "longitude": -66.01,
        "timestamp": "2026-06-01T11:58:00Z",
        "ocr_confidence": 0.9,
        "sha256": "a" * 64,
        "coordinate_method": "geo_calibration",
        "coordinate_confidence": 0.85,
        "review_status": "approved",
    },
    {
        # no coordinates -> must be skipped, not exported
        "screenshot_id": "fix-0002",
        "image_path": "fixtures/fix-0002.png",
        "timestamp": "2026-06-01T12:10:00Z",
        "latitude": None,
        "longitude": None,
        "ocr_confidence": 0.4,
    },
    {
        # rejected -> excluded by the query
        "screenshot_id": "fix-0003",
        "image_path": "fixtures/fix-0003.png",
        "timestamp": "2026-06-01T12:20:00Z",
        "latitude": 18.20,
        "longitude": -66.50,
        "review_status": "rejected",
    },
]


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))


def _build(tmp_path: Path, extra: list[str] | None = None) -> tuple[Path, subprocess.CompletedProcess]:
    db = tmp_path / "fr24_fixture.db"
    _make_fixture_db(db, FIXTURE_ROWS)
    out = tmp_path / "pkg"
    cmd = [
        sys.executable, str(BUILDER),
        "--db", str(db), "--out", str(out),
        "--mode", "test", "--mark-synthetic",
    ] + (extra or [])
    return out, _run(cmd)


def test_builder_emits_validator_passing_test_package(tmp_path):
    out, proc = _build(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    validated = _run([sys.executable, str(VALIDATOR), str(out), "--mode", "test"])
    assert validated.returncode == 0, validated.stdout + validated.stderr
    assert "VALIDATION PASSED" in validated.stdout


def test_fixture_package_can_never_pass_production(tmp_path):
    out, proc = _build(tmp_path)
    assert proc.returncode == 0
    validated = _run([sys.executable, str(VALIDATOR), str(out), "--mode", "production"])
    assert validated.returncode != 0  # synthetic rows are rejected in production


def test_rows_without_coords_are_skipped_and_rejected_rows_excluded(tmp_path):
    out, proc = _build(tmp_path)
    assert "skipped fix-0002" in proc.stdout
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["record_counts"]["observations"] == 1
    obs = json.loads((out / "observations.geojson").read_text())["features"]
    assert [f["properties"]["observation_id"] for f in obs] == ["fr24-fix-0001"]


def test_real_capture_rows_default_to_non_synthetic(tmp_path):
    db = tmp_path / "fr24_fixture.db"
    _make_fixture_db(db, FIXTURE_ROWS[:1])
    out = tmp_path / "pkg_real_flag"
    proc = _run([sys.executable, str(BUILDER), "--db", str(db), "--out", str(out)])
    assert proc.returncode == 0
    rows = json.loads((out / "observations.geojson").read_text())["features"]
    assert all(f["properties"]["synthetic"] is False for f in rows)
    sources = json.loads((out / "sources.json").read_text())
    assert all(s["provenance_status"] == "operator_capture" for s in sources)


def test_empty_db_fails_closed(tmp_path):
    db = tmp_path / "empty.db"
    _make_fixture_db(db, [])
    proc = _run(
        [sys.executable, str(BUILDER), "--db", str(db), "--out", str(tmp_path / "pkg")]
    )
    assert proc.returncode == 1
    assert "no exportable screenshot rows" in proc.stdout
