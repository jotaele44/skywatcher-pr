from __future__ import annotations

import csv
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from scripts.load_fr24_source_drop import load_source_drop

REPO_ROOT = Path(__file__).resolve().parents[1]
BUILDER = REPO_ROOT / "scripts" / "build_producer_package.py"
VALIDATOR = REPO_ROOT / "scripts" / "validate_airspace_export.py"


def _write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def test_source_drop_loader_fails_closed_without_coordinates(tmp_path: Path):
    media = tmp_path / "media.csv"
    observations = tmp_path / "observations.csv"
    review = tmp_path / "review.csv"
    _write_csv(
        media,
        [{"path": "active/screenshots/20260101/shot.png", "kind": "screenshots", "date_bucket": "20260101", "size": "123", "sha256": "a" * 64}],
        ["path", "kind", "date_bucket", "size", "sha256"],
    )
    _write_csv(
        observations,
        [{"aircraft_obs_id": "1", "filename": "shot.png", "filename_ts": "2026-01-01T00:00:00Z", "registration": "N123AB", "altitude_ft": "1200", "speed_kt": "100", "identity_status": "confirmed", "confidence": "95", "raw_excerpt": "REG. N123AB"}],
        ["aircraft_obs_id", "filename", "filename_ts", "registration", "altitude_ft", "speed_kt", "identity_status", "confidence", "raw_excerpt"],
    )
    _write_csv(review, [], ["review_id", "screenshot_id", "reason", "severity", "review_status"])

    summary = load_source_drop(
        db_path=tmp_path / "fr24.sqlite",
        media_index=media,
        observations=observations,
        review=review,
        source_ref="test",
    )

    assert summary["blocker_classification"] == "BLOCKED"
    assert summary["missing_geometry_rows"] == 1
    proc = subprocess.run(
        [sys.executable, str(BUILDER), "--db", str(tmp_path / "fr24.sqlite"), "--out", str(tmp_path / "pkg"), "--mode", "production"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 1
    assert "no exportable screenshot rows" in proc.stdout


def test_source_drop_loader_can_feed_non_synthetic_export_when_coordinates_exist(tmp_path: Path):
    media = tmp_path / "media.csv"
    observations = tmp_path / "observations.csv"
    review = tmp_path / "review.csv"
    _write_csv(
        media,
        [{"path": "active/screenshots/20260101/shot.png", "kind": "screenshots", "date_bucket": "20260101", "size": "123", "sha256": "b" * 64}],
        ["path", "kind", "date_bucket", "size", "sha256"],
    )
    _write_csv(
        observations,
        [{"aircraft_obs_id": "1", "filename": "shot.png", "filename_ts": "2026-01-01T00:00:00Z", "registration": "N123AB", "altitude_ft": "1200", "speed_kt": "100", "identity_status": "confirmed", "confidence": "95", "latitude": "18.4", "longitude": "-66.0", "raw_excerpt": "REG. N123AB"}],
        ["aircraft_obs_id", "filename", "filename_ts", "registration", "altitude_ft", "speed_kt", "identity_status", "confidence", "latitude", "longitude", "raw_excerpt"],
    )
    _write_csv(review, [], ["review_id", "screenshot_id", "reason", "severity", "review_status"])

    summary = load_source_drop(
        db_path=tmp_path / "fr24.sqlite",
        media_index=media,
        observations=observations,
        review=review,
        source_ref="test",
    )
    assert summary["blocker_classification"] == "FOUND"
    assert summary["exportable_rows"] == 1

    out = tmp_path / "pkg"
    built = subprocess.run(
        [sys.executable, str(BUILDER), "--db", str(tmp_path / "fr24.sqlite"), "--out", str(out), "--mode", "production"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    assert built.returncode == 0, built.stdout + built.stderr
    validated = subprocess.run(
        [sys.executable, str(VALIDATOR), str(out), "--mode", "production"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    assert validated.returncode == 0, validated.stdout + validated.stderr
    rows = json.loads((out / "observations.geojson").read_text())["features"]
    assert rows[0]["properties"]["synthetic"] is False

