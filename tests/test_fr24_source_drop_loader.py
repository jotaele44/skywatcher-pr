from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from scripts.load_fr24_source_drop import load_source_drop
from scripts.build_fr24_capture_review_worklist import build_worklist
from scripts.build_fr24_bbox_icon_review_batch import build_batch
from scripts.reconcile_fr24_media_identity import reconcile

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


def test_source_drop_loader_derives_approx_point_from_visible_icon_review(tmp_path: Path):
    media = tmp_path / "media.csv"
    observations = tmp_path / "observations.csv"
    review = tmp_path / "review.csv"
    capture_review = tmp_path / "capture_review.csv"
    _write_csv(
        media,
        [{"path": "active/screenshots/20260101/shot.png", "kind": "screenshots", "date_bucket": "20260101", "size": "123", "sha256": "c" * 64}],
        ["path", "kind", "date_bucket", "size", "sha256"],
    )
    _write_csv(
        observations,
        [{"aircraft_obs_id": "1", "filename": "shot.png", "filename_ts": "2026-01-01T00:00:00Z", "registration": "N123AB", "identity_status": "confirmed", "confidence": "90", "raw_excerpt": "REG. N123AB"}],
        ["aircraft_obs_id", "filename", "filename_ts", "registration", "identity_status", "confidence", "raw_excerpt"],
    )
    _write_csv(review, [], ["review_id", "screenshot_id", "reason", "severity", "review_status"])
    _write_csv(
        capture_review,
        [{
            "filename": "shot.png",
            "sha256": "c" * 64,
            "aircraft_icon_visibility": "visible",
            "image_width": "1000",
            "image_height": "500",
            "capture_bbox_min_lon": "-67.0",
            "capture_bbox_min_lat": "18.0",
            "capture_bbox_max_lon": "-66.0",
            "capture_bbox_max_lat": "19.0",
            "capture_geometry_confidence": "0.7",
            "capture_geometry_uncertainty_m": "250",
            "aircraft_icon_pixel_x": "250",
            "aircraft_icon_pixel_y": "125",
            "aircraft_point_uncertainty_m": "250",
        }],
        [
            "filename", "sha256", "aircraft_icon_visibility", "image_width", "image_height",
            "capture_bbox_min_lon", "capture_bbox_min_lat", "capture_bbox_max_lon",
            "capture_bbox_max_lat", "capture_geometry_confidence",
            "capture_geometry_uncertainty_m", "aircraft_icon_pixel_x",
            "aircraft_icon_pixel_y", "aircraft_point_uncertainty_m",
        ],
    )

    summary = load_source_drop(
        db_path=tmp_path / "fr24.sqlite",
        media_index=media,
        observations=observations,
        review=review,
        source_ref="test",
        capture_review=capture_review,
    )
    assert summary["blocker_classification"] == "FOUND"
    assert summary["icon_derived_approx_rows"] == 1
    assert summary["missing_geometry_rows"] == 0

    out = tmp_path / "pkg_icon"
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
    feature = json.loads((out / "observations.geojson").read_text())["features"][0]
    props = feature["properties"]
    assert props["geometry_status"] == "approximate"
    assert props["position_precision"] == "APPROXIMATE"
    assert props["aircraft_point_status"] == "ICON_DERIVED_APPROX"
    assert props["aircraft_icon_visibility"] == "visible"
    assert props["lat"] == 18.75
    assert props["lon"] == -66.75


def test_source_drop_loader_keeps_non_visible_icon_review_bound(tmp_path: Path):
    media = tmp_path / "media.csv"
    observations = tmp_path / "observations.csv"
    review = tmp_path / "review.csv"
    capture_review = tmp_path / "capture_review.csv"
    _write_csv(
        media,
        [{"path": "active/screenshots/20260101/shot.png", "kind": "screenshots", "date_bucket": "20260101", "size": "123", "sha256": "d" * 64}],
        ["path", "kind", "date_bucket", "size", "sha256"],
    )
    _write_csv(
        observations,
        [{"aircraft_obs_id": "1", "filename": "shot.png", "filename_ts": "2026-01-01T00:00:00Z", "registration": "N123AB"}],
        ["aircraft_obs_id", "filename", "filename_ts", "registration"],
    )
    _write_csv(review, [], ["review_id", "screenshot_id", "reason", "severity", "review_status"])
    _write_csv(
        capture_review,
        [{"filename": "shot.png", "aircraft_icon_visibility": "not_visible"}],
        ["filename", "aircraft_icon_visibility"],
    )

    summary = load_source_drop(
        db_path=tmp_path / "fr24.sqlite",
        media_index=media,
        observations=observations,
        review=review,
        source_ref="test",
        capture_review=capture_review,
    )
    assert summary["blocker_classification"] == "BLOCKED"
    assert summary["icon_derived_approx_rows"] == 0
    assert summary["unresolved_capture_review_rows"] == 1


def test_bbox_icon_batch_builder_accepts_visible_icon_sha_bound_rows(tmp_path: Path):
    source = tmp_path / "shot.png"
    source.write_bytes(b"reviewed-fr24-screenshot")

    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    media = tmp_path / "media.csv"
    review = tmp_path / "review.csv"
    observations = tmp_path / "observations.csv"
    summary_out = tmp_path / "summary.json"
    _write_csv(
        media,
        [{
            "path": "FR24_DataBank/Media_Canonical/active/screenshots/20260101/shot.png",
            "kind": "screenshots",
            "date_bucket": "20260101",
            "size": str(source.stat().st_size),
            "sha256": sha,
        }],
        ["path", "kind", "date_bucket", "size", "sha256"],
    )
    _write_csv(
        review,
        [{
            "review_status": "COMPLETED",
            "filename": "shot.png",
            "absolute_source_path": str(source),
            "sha256": sha,
            "aircraft_icon_visibility": "visible",
            "observed_at": "2026-01-01T00:00:00Z",
            "callsign": "C6062",
            "confidence": "0.55",
        }],
        [
            "review_status", "filename", "absolute_source_path", "sha256",
            "aircraft_icon_visibility", "observed_at", "callsign", "confidence",
        ],
    )

    summary = build_batch(
        review_in=review,
        media_index=media,
        observations_out=observations,
        summary_out=summary_out,
        source_ref="test_batch",
    )

    assert summary["arithmetic"] == "1=1+0+0"
    assert summary["accepted_rows"] == 1
    rows = list(csv.DictReader(observations.open(encoding="utf-8", newline="")))
    assert rows[0]["filename"] == "shot.png"
    assert rows[0]["callsign"] == "C6062"


def test_bbox_icon_batch_builder_rejects_sha_mismatch(tmp_path: Path):
    source = tmp_path / "shot.png"
    source.write_bytes(b"reviewed-fr24-screenshot")
    media = tmp_path / "media.csv"
    review = tmp_path / "review.csv"
    observations = tmp_path / "observations.csv"
    summary_out = tmp_path / "summary.json"
    _write_csv(
        media,
        [{
            "path": "FR24_DataBank/Media_Canonical/active/screenshots/20260101/shot.png",
            "kind": "screenshots",
            "date_bucket": "20260101",
            "size": str(source.stat().st_size),
            "sha256": "e" * 64,
        }],
        ["path", "kind", "date_bucket", "size", "sha256"],
    )
    _write_csv(
        review,
        [{
            "review_status": "COMPLETED",
            "filename": "shot.png",
            "absolute_source_path": str(source),
            "sha256": "e" * 64,
            "aircraft_icon_visibility": "visible",
        }],
        ["review_status", "filename", "absolute_source_path", "sha256", "aircraft_icon_visibility"],
    )

    summary = build_batch(
        review_in=review,
        media_index=media,
        observations_out=observations,
        summary_out=summary_out,
        source_ref="test_batch",
    )

    assert summary["arithmetic"] == "1=0+1+0"
    assert summary["unresolved_rows"] == 1
    assert "source file SHA does not match review SHA" in summary["validation_rows"][0]["problems"]


def test_capture_review_worklist_preserves_media_identity(tmp_path: Path):
    media = tmp_path / "media.csv"
    out = tmp_path / "worklist.csv"
    _write_csv(
        media,
        [{"path": "active/screenshots/20260101/shot.png", "date_bucket": "20260101", "size": "123", "sha256": "e" * 64}],
        ["path", "date_bucket", "size", "sha256"],
    )

    summary = build_worklist(media, out)
    rows = list(csv.DictReader(out.open("r", encoding="utf-8", newline="")))
    assert summary["worklist_rows"] == 1
    assert rows[0]["filename"] == "shot.png"
    assert rows[0]["sha256"] == "e" * 64
    assert rows[0]["aircraft_icon_visibility"] == "unreviewed"
    assert rows[0]["aircraft_point_method"] == "screenshot_icon_georeference"


def test_media_identity_reconciler_separates_exact_from_candidate(tmp_path: Path):
    media = tmp_path / "media.csv"
    observations = tmp_path / "observations.csv"
    _write_csv(
        media,
        [
            {
                "path": "active/screenshots/20260101/exact.png",
                "kind": "screenshots",
                "date_bucket": "20260101",
                "sha256": "f" * 64,
                "aircraft_or_callsign": "N123AB",
            },
            {
                "path": "active/screenshots/20260102/candidate.png",
                "kind": "screenshots",
                "date_bucket": "20260102",
                "sha256": "a" * 64,
                "aircraft_or_callsign": "N456CD",
            },
        ],
        ["path", "kind", "date_bucket", "sha256", "aircraft_or_callsign"],
    )
    _write_csv(
        observations,
        [
            {
                "aircraft_obs_id": "1",
                "filename": "exact.png",
                "filename_ts": "2026-01-01T00:00:00Z",
                "registration": "N123AB",
            },
            {
                "aircraft_obs_id": "2",
                "filename": "renamed.png",
                "filename_ts": "2026-01-02T00:00:00Z",
                "registration": "N456CD",
            },
        ],
        ["aircraft_obs_id", "filename", "filename_ts", "registration"],
    )

    summary = reconcile(
        media_index=media,
        observations=observations,
        csv_out=tmp_path / "reconcile.csv",
        json_out=tmp_path / "reconcile.json",
    )
    rows = list(csv.DictReader((tmp_path / "reconcile.csv").open("r", encoding="utf-8", newline="")))
    assert summary["intersection_exact_filename"] == 1
    assert summary["candidate_not_identity_rows"] == 2
    assert rows[0]["match_status"] == "FOUND"
    assert any(row["match_status"] == "CANDIDATE_NOT_IDENTITY" for row in rows)
