"""Tests for the per_screenshot_affine calibration mode + RLSM anchor plumbing.

Covers:
  - fit_affine / apply_affine (lifted from scripts/rlsm_geocode_unlabeled.py)
  - GeoCalibration(mode="per_screenshot_affine") residual-driven confidence
    and its fixed_pr_bounds fallback
  - fr24.rlsm_anchors anchor collection from a schema.sql fixture DB
  - scripts/sync_rlsm_calibration.py bridging RLSM anchors into the
    operational DB so build_producer_package.py can reach the `located` floor
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from integration.geo_calibration import (
    GeoCalibration,
    affine_median_residual_deg,
    apply_affine,
    fit_affine,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_SQL = REPO_ROOT / "data" / "rlsm" / "schema.sql"

# A ground-truth transform for synthetic anchors: lon = -67.3 + 0.001*px,
# lat = 18.6 - 0.0005*py (pixel y grows downward).
TRUE_AFFINE = (-67.3, 0.001, 18.6, -0.0005)


def _anchor(px: float, py: float, lat_offset: float = 0.0, lon_offset: float = 0.0):
    lat, lon = apply_affine(TRUE_AFFINE, px, py)
    return (px, py, lat + lat_offset, lon + lon_offset)


# ──────────────────────────────────────────────────────────────────────────
# fit_affine / apply_affine
# ──────────────────────────────────────────────────────────────────────────

def test_fit_affine_recovers_known_transform():
    anchors = [_anchor(100, 200), _anchor(800, 1500), _anchor(400, 900)]
    affine = fit_affine([(a[0], a[1]) for a in anchors], [(a[2], a[3]) for a in anchors])
    assert affine is not None
    for got, want in zip(affine, TRUE_AFFINE):
        assert got == pytest.approx(want, abs=1e-9)
    assert affine_median_residual_deg(
        affine, [(a[0], a[1]) for a in anchors], [(a[2], a[3]) for a in anchors]
    ) == pytest.approx(0.0, abs=1e-9)


def test_fit_affine_requires_two_anchors():
    assert fit_affine([(100, 200)], [(18.4, -66.1)]) is None
    assert fit_affine([], []) is None


def test_fit_affine_rejects_degenerate_pixel_spread():
    # Same pixel x for every anchor -> lon scale unrecoverable.
    assert fit_affine([(100, 200), (100, 900)], [(18.4, -66.1), (18.1, -66.5)]) is None


# ──────────────────────────────────────────────────────────────────────────
# GeoCalibration per_screenshot_affine mode
# ──────────────────────────────────────────────────────────────────────────

def test_affine_mode_exact_anchors_cross_located_floor():
    cal = GeoCalibration(mode="per_screenshot_affine",
                         anchors=[_anchor(100, 200), _anchor(900, 1800)])
    result = cal.pixel_to_coord(500, 1000, 1170, 2532)
    want_lat, want_lon = apply_affine(TRUE_AFFINE, 500, 1000)
    assert result.coordinate_method == "per_screenshot_affine"
    assert result.coordinate_confidence == 0.90
    assert result.estimated_error_m == 50.0  # floored, never claims 0 m
    assert result.lat == pytest.approx(want_lat, abs=1e-4)
    assert result.lon == pytest.approx(want_lon, abs=1e-4)
    # This is the point of the mode: >= build_producer_package's located floor.
    assert result.coordinate_confidence >= 0.8


def _banded_anchors(t: float):
    """Four anchors whose lat offsets (+t, +t, -t, -t) are mean-zero and
    orthogonal to the centered pixel-y regressor (-900, 900, -500, 500), so
    the OLS fit recovers TRUE_AFFINE exactly and every residual equals t."""
    return [
        _anchor(100, 200, lat_offset=t),
        _anchor(900, 2000, lat_offset=t),
        _anchor(500, 600, lat_offset=-t),
        _anchor(300, 1600, lat_offset=-t),
    ]


def test_affine_mode_mid_residual_gets_mid_confidence():
    # 0.003 deg residual -> ~333 m: inside the (150, 500] band.
    cal = GeoCalibration(mode="per_screenshot_affine", anchors=_banded_anchors(0.003))
    result = cal.pixel_to_coord(500, 1000, 1170, 2532)
    assert result.coordinate_method == "per_screenshot_affine"
    assert result.coordinate_confidence == 0.82
    assert 150.0 < result.estimated_error_m <= 500.0


def test_affine_mode_loose_residual_gets_floor_confidence():
    # 0.008 deg residual -> ~888 m: past the 500 m band.
    cal = GeoCalibration(mode="per_screenshot_affine", anchors=_banded_anchors(0.008))
    result = cal.pixel_to_coord(500, 1000, 1170, 2532)
    assert result.coordinate_confidence == 0.70
    assert result.estimated_error_m > 500.0


@pytest.mark.parametrize(
    "anchors",
    [
        None,
        [],
        [(100, 200, 18.4, -66.1)],                      # one anchor
        [(100, 200, 18.4, -66.1), (100, 900, 18.1, -66.5)],       # zero pixel-x spread
        [(100, 200, 18.4, -66.1), (100.02, 200.03, 18.1, -66.5)],  # dedup -> one anchor
    ],
)
def test_affine_mode_falls_back_to_fixed_bounds(anchors):
    cal = GeoCalibration(mode="per_screenshot_affine", anchors=anchors)
    assert cal.affine is None
    result = cal.pixel_to_coord(500, 300, 1024, 768)
    baseline = GeoCalibration(mode="fixed_pr_bounds").pixel_to_coord(500, 300, 1024, 768)
    assert result.coordinate_method == "fixed_pr_bounds"
    assert result.coordinate_confidence == baseline.coordinate_confidence == 0.65
    assert result.lat == baseline.lat and result.lon == baseline.lon


def test_existing_modes_unchanged():
    result = GeoCalibration(mode="fixed_pr_bounds").pixel_to_coord(500, 300, 1024, 768)
    assert result.coordinate_method == "fixed_pr_bounds"
    assert result.coordinate_confidence == 0.65
    assert result.estimated_error_m == 1500.0


def test_geocoder_script_reexports_shared_affine():
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        import rlsm_geocode_unlabeled as geocoder
    finally:
        sys.path.pop(0)
    assert geocoder.fit_affine is fit_affine
    assert geocoder.apply_affine is apply_affine


# ──────────────────────────────────────────────────────────────────────────
# fr24.rlsm_anchors against a schema.sql fixture DB
# ──────────────────────────────────────────────────────────────────────────

@pytest.fixture
def rlsm_db(tmp_path: Path) -> Path:
    if not SCHEMA_SQL.exists():
        pytest.skip("data/rlsm/schema.sql not tracked")
    db = tmp_path / "rlsm.sqlite"
    conn = sqlite3.connect(str(db))
    conn.executescript(SCHEMA_SQL.read_text())
    for sid, sha in ((1, "a" * 64), (2, "b" * 64)):
        conn.execute(
            "INSERT INTO screenshots (screenshot_id, sha256, filename, rel_path, ext,"
            " size_bytes, width, height, ingest_status, ingested_at)"
            " VALUES (?, ?, ?, ?, 'png', 1000, 1170, 2532, 'ok', '2026-06-01T00:00:00Z')",
            (sid, sha, f"f{sid}.png", f"f{sid}.png"),
        )
    # Screenshot 1: two pixel geo_anchors on the TRUE_AFFINE transform plus one
    # vocab-matched labeled pin with a backfilled centroid.
    for name, px, py in (("SAN JUAN", 100, 200), ("PONCE", 900, 1800)):
        lat, lon = apply_affine(TRUE_AFFINE, px, py)
        conn.execute(
            "INSERT INTO geo_anchors (screenshot_id, anchor_kind, name, pixel_x, pixel_y,"
            " lat, lon, confidence, observed_at)"
            " VALUES (1, 'derived', ?, ?, ?, ?, ?, 0.9, '2026-06-01T00:00:00Z')",
            (name, px, py, lat, lon),
        )
    pin_lat, pin_lon = apply_affine(TRUE_AFFINE, 500, 1000)
    conn.execute(
        "INSERT INTO geo_anchors (screenshot_id, anchor_kind, name, lat, lon, observed_at)"
        " VALUES (NULL, 'static', 'CAGUAS', ?, ?, '2026-06-01T00:00:00Z')",
        (pin_lat, pin_lon),
    )
    conn.execute(
        "INSERT INTO labeled_pins (screenshot_id, raw_label, normalized_label,"
        " centroid_x, centroid_y, pin_type_guess, observed_at)"
        " VALUES (1, 'Caguas', 'Caguas', 500, 1000, 'city', '2026-06-01T00:00:00Z')",
    )
    # Duplicate pixel position of an existing anchor -> deduplicated.
    conn.execute(
        "INSERT INTO labeled_pins (screenshot_id, raw_label, normalized_label,"
        " centroid_x, centroid_y, pin_type_guess, observed_at)"
        " VALUES (1, 'San Juan', 'San Juan', 100, 200, 'city', '2026-06-01T00:00:00Z')",
    )
    # NULL centroid (extractor default before the re-OCR backfill) -> excluded.
    conn.execute(
        "INSERT INTO labeled_pins (screenshot_id, raw_label, normalized_label,"
        " pin_type_guess, observed_at)"
        " VALUES (1, 'Mayaguez', 'Mayaguez', 'city', '2026-06-01T00:00:00Z')",
    )
    # Screenshot 2 has no anchors at all.
    conn.commit()
    conn.close()
    return db


def test_anchors_for_screenshot_unions_and_dedups(rlsm_db):
    from fr24.rlsm_anchors import anchors_for_screenshot, build_geo_lookup

    conn = sqlite3.connect(str(rlsm_db))
    lookup = build_geo_lookup(conn, places_geojson=Path("/nonexistent/places.geojson"))
    assert "CAGUAS" in lookup  # named geo_anchors feed the vocabulary
    anchors = anchors_for_screenshot(conn, 1, lookup)
    assert len(anchors) == 3  # 2 pixel geo_anchors + 1 vocab pin; duplicate dropped
    assert anchors_for_screenshot(conn, 2, lookup) == []
    conn.close()

    cal = GeoCalibration(mode="per_screenshot_affine", anchors=anchors)
    assert cal.affine is not None
    assert cal.pixel_to_coord(700, 1400, 1170, 2532).coordinate_confidence == 0.90


# ──────────────────────────────────────────────────────────────────────────
# scripts/sync_rlsm_calibration.py end-to-end
# ──────────────────────────────────────────────────────────────────────────

def _make_operational_db(path: Path, rows: list[dict]) -> None:
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


def test_sync_promotes_fixed_bounds_rows_to_affine(rlsm_db, tmp_path):
    # The operational row was stamped by fixed_pr_bounds at pixel (500, 1000)
    # in a 1170x2532 frame; recompute that stamp exactly as the inventory did.
    fixed = GeoCalibration(mode="fixed_pr_bounds").pixel_to_coord(500, 1000, 1170, 2532)
    op_db = tmp_path / "fr24.db"
    _make_operational_db(op_db, [
        {
            "screenshot_id": "op-0001",
            "sha256": "a" * 64,  # matches RLSM screenshot 1 (has anchors)
            "latitude": fixed.lat,
            "longitude": fixed.lon,
            "timestamp": "2026-06-01T11:58:00Z",
            "ocr_confidence": 0.9,
            "coordinate_method": "fixed_pr_bounds",
            "coordinate_confidence": 0.65,
            "estimated_error_m": 1500.0,
        },
        {
            "screenshot_id": "op-0002",
            "sha256": "b" * 64,  # matches RLSM screenshot 2 (no anchors)
            "latitude": 18.2,
            "longitude": -66.5,
            "coordinate_method": "fixed_pr_bounds",
            "coordinate_confidence": 0.65,
        },
        {
            "screenshot_id": "op-0003",
            "sha256": "c" * 64,  # no RLSM match
            "latitude": 18.2,
            "longitude": -66.5,
            "coordinate_method": "fixed_pr_bounds",
        },
        {
            "screenshot_id": "op-0004",
            "sha256": "a" * 64,
            "latitude": 18.3,
            "longitude": -66.2,
            "coordinate_method": "manual_anchor_csv",  # protected: never clobbered
            "coordinate_confidence": 0.9,
        },
    ])

    proc = subprocess.run(
        [
            sys.executable, str(REPO_ROOT / "scripts" / "sync_rlsm_calibration.py"),
            "--rlsm-db", str(rlsm_db), "--operational-db", str(op_db),
            "--places-geojson", "/nonexistent/places.geojson",
        ],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    summary = json.loads(proc.stdout)
    assert summary["updated"] == 1
    assert summary["skipped_few_anchors"] == 1
    assert summary["skipped_no_sha_match"] == 1
    assert summary["skipped_method_protected"] == 1

    conn = sqlite3.connect(str(op_db))
    conn.row_factory = sqlite3.Row
    updated = conn.execute(
        "SELECT * FROM screenshots WHERE screenshot_id = 'op-0001'"
    ).fetchone()
    untouched = conn.execute(
        "SELECT * FROM screenshots WHERE screenshot_id = 'op-0004'"
    ).fetchone()
    conn.close()

    assert updated["coordinate_method"] == "per_screenshot_affine"
    assert updated["coordinate_confidence"] == 0.90
    assert updated["estimated_error_m"] == 50.0
    # The refit coordinate is the TRUE_AFFINE value at the recovered pixel.
    want_lat, want_lon = apply_affine(TRUE_AFFINE, 500, 1000)
    assert updated["latitude"] == pytest.approx(want_lat, abs=1e-3)
    assert updated["longitude"] == pytest.approx(want_lon, abs=1e-3)
    assert untouched["coordinate_method"] == "manual_anchor_csv"
    assert untouched["latitude"] == 18.3


def test_sync_dry_run_writes_nothing(rlsm_db, tmp_path):
    fixed = GeoCalibration(mode="fixed_pr_bounds").pixel_to_coord(500, 1000, 1170, 2532)
    op_db = tmp_path / "fr24.db"
    _make_operational_db(op_db, [{
        "screenshot_id": "op-0001",
        "sha256": "a" * 64,
        "latitude": fixed.lat,
        "longitude": fixed.lon,
        "coordinate_method": "fixed_pr_bounds",
        "coordinate_confidence": 0.65,
    }])
    proc = subprocess.run(
        [
            sys.executable, str(REPO_ROOT / "scripts" / "sync_rlsm_calibration.py"),
            "--rlsm-db", str(rlsm_db), "--operational-db", str(op_db),
            "--places-geojson", "/nonexistent/places.geojson", "--dry-run",
        ],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["updated"] == 1
    conn = sqlite3.connect(str(op_db))
    method = conn.execute("SELECT coordinate_method FROM screenshots").fetchone()[0]
    conn.close()
    assert method == "fixed_pr_bounds"


def test_synced_db_reaches_located_in_producer_package(rlsm_db, tmp_path):
    """The whole point of Task 1: after the sync, build_producer_package emits
    a `located` observation from what used to be an `approximate` row."""
    fixed = GeoCalibration(mode="fixed_pr_bounds").pixel_to_coord(500, 1000, 1170, 2532)
    op_db = tmp_path / "fr24.db"
    _make_operational_db(op_db, [{
        "screenshot_id": "op-0001",
        "image_path": "fixtures/op-0001.png",
        "sha256": "a" * 64,
        "latitude": fixed.lat,
        "longitude": fixed.lon,
        "timestamp": "2026-06-01T11:58:00Z",
        "processed_at": "2026-06-01T12:00:00Z",
        "ocr_confidence": 0.9,
        "coordinate_method": "fixed_pr_bounds",
        "coordinate_confidence": 0.65,
        "estimated_error_m": 1500.0,
        "review_status": "approved",
    }])
    sync = subprocess.run(
        [
            sys.executable, str(REPO_ROOT / "scripts" / "sync_rlsm_calibration.py"),
            "--rlsm-db", str(rlsm_db), "--operational-db", str(op_db),
            "--places-geojson", "/nonexistent/places.geojson",
        ],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert sync.returncode == 0, sync.stdout + sync.stderr

    out = tmp_path / "pkg"
    build = subprocess.run(
        [
            sys.executable, str(REPO_ROOT / "scripts" / "build_producer_package.py"),
            "--db", str(op_db), "--out", str(out), "--mode", "test", "--mark-synthetic",
        ],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert build.returncode == 0, build.stdout + build.stderr
    features = json.loads((out / "observations.geojson").read_text())["features"]
    assert len(features) == 1
    props = features[0]["properties"]
    assert props["geometry_status"] == "located"
    lineage = json.loads((out / "lineage.json").read_text())
    assert lineage[0]["coordinate_method"] == "per_screenshot_affine"
