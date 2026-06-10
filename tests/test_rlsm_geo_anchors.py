"""Tests for fr24/rlsm_geo_anchors.py — the static geo-anchor populator.

Tests are structural: they verify the runner emits the right number of rows
per screenshot, the pixel projection is correct, the schema is honored, and
the runner is idempotent. They do NOT validate the lat/lon values themselves
(those come straight from configs/georef_anchors.csv and are the ground truth).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


# ──────────────────────────────────────────────────────────────────────────
# Unit tests — registry loading + projection (no SQLite)
# ──────────────────────────────────────────────────────────────────────────

def test_load_anchor_registry_returns_at_least_three_anchors():
    """We need ≥3 anchors to fit an affine transform downstream."""
    from fr24.rlsm_geo_anchors import _load_anchor_registry
    anchors = _load_anchor_registry()
    assert len(anchors) >= 3, "homography fitting requires ≥3 non-collinear anchors"


def test_load_anchor_registry_fields_well_formed():
    from fr24.rlsm_geo_anchors import _load_anchor_registry
    anchors = _load_anchor_registry()
    for a in anchors:
        # Each anchor has all required fields with correct types
        assert "anchor_id_text" in a and a["anchor_id_text"]
        assert "name" in a and a["name"]
        # Pixel fractions in [0,1] (the canonical resolution-independent range)
        assert 0.0 <= a["pixel_x_fraction"] <= 1.0
        assert 0.0 <= a["pixel_y_fraction"] <= 1.0
        # Puerto Rico bounding box (rough sanity check on lat/lon)
        assert 17.5 <= a["lat"] <= 19.0, f"lat {a['lat']} outside PR bbox"
        assert -68.0 <= a["lon"] <= -65.0, f"lon {a['lon']} outside PR bbox"


@pytest.mark.parametrize("width,height,fraction_x,fraction_y,expected_px,expected_py", [
    (1000, 800, 0.5, 0.5, 500, 400),  # centroid of a 1000x800 image
    (2880, 1800, 0.72, 0.42, 2074, 756),  # SJU-like anchor on retina res
    (100, 100, 0.0, 0.0, 0, 0),  # top-left corner
    (100, 100, 1.0, 1.0, 100, 100),  # bottom-right corner
])
def test_project_to_pixels(width, height, fraction_x, fraction_y, expected_px, expected_py):
    from fr24.rlsm_geo_anchors import _project_to_pixels
    anchor = {"pixel_x_fraction": fraction_x, "pixel_y_fraction": fraction_y}
    px, py = _project_to_pixels(anchor, width, height)
    assert px == expected_px
    assert py == expected_py


# ──────────────────────────────────────────────────────────────────────────
# Integration tests — run() against a hermetic in-memory DB
# ──────────────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_rlsm_db(tmp_path: Path, monkeypatch):
    """Build a tiny RLSM DB with 3 screenshots covering different scenarios."""
    db = tmp_path / "rlsm.sqlite"
    schema_path = Path(__file__).resolve().parents[1] / "data" / "rlsm" / "schema.sql"
    if not schema_path.exists():
        pytest.skip("data/rlsm/schema.sql not tracked")
    conn = sqlite3.connect(str(db))
    conn.executescript(schema_path.read_text())
    # screenshot 1: 'ok' + width/height present → SHOULD be processed
    conn.execute(
        "INSERT INTO screenshots (screenshot_id, sha256, filename, rel_path, ext, "
        "size_bytes, width, height, ingest_status, ingested_at) "
        "VALUES (1, 'sha1', 'f1.png', 'f1.png', 'png', 1000, 800, 600, 'ok', '2026-06-01T00:00:00Z')"
    )
    # screenshot 2: 'ok' BUT width=NULL → SHOULD be SKIPPED (cannot project)
    conn.execute(
        "INSERT INTO screenshots (screenshot_id, sha256, filename, rel_path, ext, "
        "size_bytes, width, height, ingest_status, ingested_at) "
        "VALUES (2, 'sha2', 'f2.png', 'f2.png', 'png', 500, NULL, NULL, 'ok', '2026-06-01T00:00:00Z')"
    )
    # screenshot 3: 'corrupt' → SHOULD be SKIPPED (ingest_status filter)
    conn.execute(
        "INSERT INTO screenshots (screenshot_id, sha256, filename, rel_path, ext, "
        "size_bytes, width, height, ingest_status, ingested_at) "
        "VALUES (3, 'sha3', 'f3.png', 'f3.png', 'png', 200, 800, 600, 'corrupt', '2026-06-01T00:00:00Z')"
    )
    conn.commit()
    conn.close()
    import fr24.rlsm_geo_anchors as ga
    monkeypatch.setattr(ga, "DB", db)
    return db


def test_run_processes_only_ok_screenshots_with_dimensions(tmp_rlsm_db):
    """Screenshot 1 (ok+dims) is processed; 2 (no dims) and 3 (corrupt) are skipped."""
    from fr24.rlsm_geo_anchors import run, _load_anchor_registry
    snapshot = run(budget_sec=10.0)
    n_anchors = len(_load_anchor_registry())
    assert snapshot["processed"] == 1
    assert snapshot["targets"] == 1  # only screenshot 1 qualifies for the run
    assert snapshot["failed"] == 0
    assert snapshot["anchors_inserted"] == n_anchors  # 1 screenshot × all anchors


def test_run_emits_static_kind_rows_with_pixel_coords(tmp_rlsm_db):
    """Verify the inserted rows have the expected shape + pixel projection."""
    from fr24.rlsm_geo_anchors import run, _load_anchor_registry, STATIC_ANCHOR_CONFIDENCE
    run(budget_sec=10.0)
    conn = sqlite3.connect(str(tmp_rlsm_db))
    rows = conn.execute(
        "SELECT anchor_kind, name, pixel_x, pixel_y, lat, lon, confidence, source "
        "FROM geo_anchors WHERE screenshot_id=1 ORDER BY anchor_id"
    ).fetchall()
    conn.close()
    anchors_registry = _load_anchor_registry()
    assert len(rows) == len(anchors_registry)
    for (kind, name, px, py, lat, lon, conf, source), expected in zip(rows, anchors_registry):
        assert kind == "static"
        assert name == expected["name"]
        # Pixel projection: round(fraction * dim)
        assert px == round(expected["pixel_x_fraction"] * 800)
        assert py == round(expected["pixel_y_fraction"] * 600)
        assert lat == expected["lat"]
        assert lon == expected["lon"]
        assert conf == STATIC_ANCHOR_CONFIDENCE
        assert "configs/georef_anchors.csv" in source


def test_run_is_idempotent(tmp_rlsm_db):
    """Second run() must insert zero new rows — NOT EXISTS guard works."""
    from fr24.rlsm_geo_anchors import run
    first = run(budget_sec=10.0)
    second = run(budget_sec=10.0)
    assert first["processed"] == 1
    assert second["processed"] == 0
    assert second["anchors_inserted"] == 0
    # geo_anchors still has only one screenshot's worth of rows
    conn = sqlite3.connect(str(tmp_rlsm_db))
    n_rows = conn.execute("SELECT COUNT(*) FROM geo_anchors").fetchone()[0]
    conn.close()
    assert n_rows == first["anchors_inserted"]


def test_run_records_processing_runs_row(tmp_rlsm_db):
    """Verify the runner emits a processing_runs row with run_kind='geo_anchors'."""
    from fr24.rlsm_geo_anchors import run
    run(budget_sec=10.0)
    conn = sqlite3.connect(str(tmp_rlsm_db))
    rows = conn.execute(
        "SELECT run_kind, status, n_processed FROM processing_runs WHERE run_kind='geo_anchors'"
    ).fetchall()
    conn.close()
    assert len(rows) == 1
    kind, status, n_processed = rows[0]
    assert kind == "geo_anchors"
    assert status == "completed"
    assert n_processed == 1


def test_anchor_kind_enum_compliance(tmp_rlsm_db):
    """All emitted anchor_kind values must be in the schema's documented enum."""
    from fr24.rlsm_geo_anchors import run
    run(budget_sec=10.0)
    conn = sqlite3.connect(str(tmp_rlsm_db))
    kinds = {row[0] for row in conn.execute("SELECT DISTINCT anchor_kind FROM geo_anchors").fetchall()}
    conn.close()
    assert kinds.issubset({"static", "derived", "failed"}), f"unknown kinds: {kinds}"


def test_confidence_in_canonical_range(tmp_rlsm_db):
    """confidence must obey the canonical [0,1] scale."""
    from fr24.rlsm_geo_anchors import run
    run(budget_sec=10.0)
    conn = sqlite3.connect(str(tmp_rlsm_db))
    rows = conn.execute("SELECT confidence FROM geo_anchors").fetchall()
    conn.close()
    for (conf,) in rows:
        assert 0.0 <= conf <= 1.0, f"confidence out of range: {conf}"
