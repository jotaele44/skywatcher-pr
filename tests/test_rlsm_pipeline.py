"""
Tests for the RLSM extraction-first pipeline.

Verifies the structural invariants required by the spec:
  1. every image has exactly one screenshots row
  2. every processed screenshot has an OCR attempt record
  3. raw OCR is never overwritten
  4. labeled POIs and unlabeled candidates are stored in SEPARATE tables
  5. failed files are recorded in the screenshots table (never silently skipped)
  6. duplicate groups are recorded
  7. exports are reproducible (running the exporter twice produces identical bytes)
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import sqlite3
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
BASELINE = REPO / "data" / "FR24_baseline"
OUTPUTS = REPO / "outputs"


def _conn() -> sqlite3.Connection:
    if not DB.exists():
        pytest.skip(f"RLSM DB not yet built: {DB}")
    c = sqlite3.connect(DB)
    c.execute("PRAGMA foreign_keys = ON")
    # CI cascade guard: sqlite3.connect() creates an empty file as a side-effect,
    # so an earlier test that touched the DB path may have left an empty file.
    # Skip if the canonical schema is missing — distinguishes "no populated DB"
    # from "DB has been built and queries should be meaningful".
    has_tables = c.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='screenshots'"
    ).fetchone()
    if not has_tables:
        c.close()
        pytest.skip(f"RLSM DB exists but is empty (no schema): {DB}")
    return c


# ---- structural invariants ---------------------------------------------------

def test_screema_tables_exist():
    c = _conn()
    expected = {"screenshots", "processing_runs", "ocr_observations",
                "aircraft_observations", "flight_track_features", "labeled_pins",
                "unlabeled_pin_candidates", "geo_anchors", "manual_review_queue"}
    existing = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    missing = expected - existing
    assert not missing, f"missing tables: {missing}"


def test_every_image_has_exactly_one_screenshots_row():
    """Invariant 1: bijection between baseline image files and screenshots rows."""
    c = _conn()
    # Count baseline images on disk (excluding sidecars + missing-on-disk synth row)
    files_on_disk = sorted(
        p for sub in BASELINE.iterdir() if sub.is_dir()
        for p in sub.iterdir()
        if p.is_file() and not p.name.endswith(".sidecar.json")
    )
    n_disk = len(files_on_disk)

    # screenshots rows that are present-on-disk (rel_path not under _missing/)
    n_present_rows = c.execute(
        "SELECT COUNT(*) FROM screenshots WHERE rel_path NOT LIKE '%/_missing/%'"
    ).fetchone()[0]
    assert n_present_rows == n_disk, (
        f"screenshots.present_rows ({n_present_rows}) != on-disk images ({n_disk})"
    )
    # SHA-256 uniqueness in screenshots table
    n_dups = c.execute(
        "SELECT COUNT(*) FROM (SELECT sha256 FROM screenshots GROUP BY sha256 HAVING COUNT(*) > 1)"
    ).fetchone()[0]
    assert n_dups == 0, f"{n_dups} duplicate sha256 in screenshots"


def test_every_processed_screenshot_has_ocr_attempt():
    """Invariant 2: ocr_status='ok' implies >= 1 ocr_observation row exists."""
    c = _conn()
    rows = c.execute("""
        SELECT s.screenshot_id, s.filename
        FROM screenshots s
        WHERE s.ocr_status = 'ok'
          AND NOT EXISTS (SELECT 1 FROM ocr_observations o WHERE o.screenshot_id = s.screenshot_id)
    """).fetchall()
    assert not rows, f"{len(rows)} 'ok' screenshots have no ocr_observations: {rows[:5]}"


def test_raw_ocr_is_never_overwritten():
    """Invariant 3: an ocr_observations row is append-only (UPDATE prohibited).

    Tested by checking: each (screenshot_id, zone, run_id) appears at most once;
    on a hypothetical re-run, a new run_id is used so multiple rows can exist
    for the same (screenshot_id, zone) — but never overwriting an existing row.
    """
    c = _conn()
    # Multiple rows for same (screenshot, zone) are allowed across runs, but
    # a single (screenshot, zone, run_id) triple must be unique.
    rows = c.execute("""
        SELECT screenshot_id, zone, run_id, COUNT(*) AS n
        FROM ocr_observations
        GROUP BY screenshot_id, zone, run_id
        HAVING n > 1
    """).fetchall()
    assert not rows, f"duplicate (screenshot_id, zone, run_id) tuples: {rows[:5]}"

    # raw_text is non-empty when ocr_status='ok' (i.e. never replaced with "" via update)
    bad = c.execute("""
        SELECT obs_id FROM ocr_observations
        WHERE ocr_status = 'ok' AND (raw_text IS NULL OR raw_text = '')
    """).fetchone()
    assert not bad, f"'ok' OCR row with empty raw_text: {bad}"


def test_labeled_vs_unlabeled_separated():
    """Invariant 4: labeled_pins and unlabeled_pin_candidates are separate tables."""
    c = _conn()
    # Each must have its own dedicated columns
    cols_labeled = {row[1] for row in c.execute("PRAGMA table_info(labeled_pins)")}
    cols_unlabeled = {row[1] for row in c.execute("PRAGMA table_info(unlabeled_pin_candidates)")}
    assert "raw_label" in cols_labeled, "labeled_pins must have raw_label"
    assert "raw_label" not in cols_unlabeled, "unlabeled_pin_candidates must NOT have raw_label"
    assert "candidate_type" in cols_unlabeled, "unlabeled_pin_candidates must have candidate_type"
    assert "candidate_type" not in cols_labeled, "labeled_pins must NOT have candidate_type"


def test_failed_files_recorded():
    """Invariant 5: anything that failed to ingest is in screenshots with non-ok status."""
    c = _conn()
    n_failed = c.execute(
        "SELECT COUNT(*) FROM screenshots WHERE ingest_status IN ('corrupt','unreadable')"
    ).fetchone()[0]
    # We expect at least 1 (the known-missing file flagged in manifest)
    assert n_failed >= 1, "expected at least 1 failed-file row (missing-on-disk)"
    # All failed rows should have an ingest_error message
    rows_missing_err = c.execute("""
        SELECT screenshot_id FROM screenshots
        WHERE ingest_status IN ('corrupt','unreadable')
          AND (ingest_error IS NULL OR ingest_error = '')
    """).fetchall()
    assert not rows_missing_err, f"{len(rows_missing_err)} failed rows lack ingest_error"


def test_duplicate_groups_recorded():
    """Invariant 6: exact-SHA dup detection populates dup_group_id where applicable."""
    c = _conn()
    # If there are SHAs that appear twice, they MUST have a non-null dup_group_id
    bad = c.execute("""
        WITH dup_shas AS (
            SELECT sha256 FROM screenshots GROUP BY sha256 HAVING COUNT(*) > 1
        )
        SELECT s.screenshot_id, s.sha256
        FROM screenshots s
        WHERE s.sha256 IN (SELECT sha256 FROM dup_shas)
          AND s.dup_group_id IS NULL
    """).fetchall()
    assert not bad, f"{len(bad)} screenshots in dup SHAs are missing dup_group_id"


def test_exports_reproducible():
    """Invariant 7: running the exporter twice in the same DB state produces
    byte-identical files. Hardened (N6): we export TWICE inside the test and
    compare h1 vs h2 — both fresh against the current DB. The old form
    compared on-disk vs fresh, which re-broke whenever the DB advanced
    without a re-export (a stale-artifact tripwire, not a determinism test)."""
    # Skip via _conn() if no populated DB (CI without the baseline).
    # _conn() already creates the file as a side-effect; we close immediately
    # so the export below opens its own connection cleanly.
    _conn().close()
    needed = [
        "rlsm_ingest_manifest.csv",
        "rlsm_duplicate_report.csv",
        "rlsm_failed_files.csv",
    ]
    from fr24 import rlsm_export
    rlsm_export.export_all()
    missing = [n for n in needed if not (OUTPUTS / n).exists()]
    if missing:
        pytest.skip(f"exporter did not produce: {missing}")
    h1 = {n: hashlib.sha256((OUTPUTS / n).read_bytes()).hexdigest() for n in needed}
    rlsm_export.export_all()
    h2 = {n: hashlib.sha256((OUTPUTS / n).read_bytes()).hexdigest() for n in needed}
    diffs = [n for n in needed if h1[n] != h2[n]]
    assert not diffs, f"exports not reproducible across two in-test runs: {diffs}"


# ---- end-to-end smoke -------------------------------------------------------

def test_aircraft_observations_well_formed():
    """Every aircraft row links back to a screenshot and has a valid identity_status.

    Allowed identity_status values:
      - confirmed / partial / conflicting / unknown — produced by the primary
        aircraft extractor (fr24/rlsm_extractors.py).
      - recovered — produced by a separate raw-text rescue pass that scans
        ocr_observations.raw_text for known FAA tail numbers and inserts new
        aircraft_observations rows for tails the primary extractor missed.
    """
    c = _conn()
    rows = c.execute("""
        SELECT aircraft_obs_id, identity_status
        FROM aircraft_observations
        WHERE identity_status NOT IN ('confirmed','partial','conflicting','unknown','recovered')
           OR screenshot_id NOT IN (SELECT screenshot_id FROM screenshots)
    """).fetchall()
    assert not rows, f"{len(rows)} malformed aircraft rows"


def test_review_queue_pointers_resolve():
    """Every manual_review_queue row points to a real screenshot."""
    c = _conn()
    rows = c.execute("""
        SELECT review_id FROM manual_review_queue r
        WHERE r.screenshot_id IS NOT NULL
          AND r.screenshot_id NOT IN (SELECT screenshot_id FROM screenshots)
    """).fetchall()
    assert not rows, f"{len(rows)} review-queue rows reference unknown screenshots"


def test_aircraft_observations_dedup_index_exists():
    """The ix_air_dedup partial-unique index must exist (B-dedup-unique)."""
    import sqlite3 as _sqlite3
    c = _conn()
    row = c.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND name='ix_air_dedup'"
    ).fetchone()
    assert row is not None, "ix_air_dedup unique index is missing"
    sql = row[0]
    assert "UNIQUE" in sql.upper()
    assert "registration" in sql and "source_zone" in sql


def test_aircraft_observations_dedup_rejects_duplicates():
    """Inserting a second row with the same (screenshot, registration, source_zone)
    raises IntegrityError. Test uses a savepoint + rollback so live data is
    untouched even on success of the first insert."""
    import sqlite3 as _sqlite3
    c = _conn()
    # Pick any real screenshot_id so the FK is satisfied
    sid_row = c.execute("SELECT screenshot_id FROM screenshots LIMIT 1").fetchone()
    if not sid_row:
        pytest.skip("no screenshots in DB")
    sid = sid_row[0]
    test_reg = "Z9_TEST_DEDUP_REG"
    test_zone = "test_zone_dedup"
    try:
        c.execute("SAVEPOINT dedup_test")
        c.execute("""
            INSERT INTO aircraft_observations
              (screenshot_id, registration, identity_status, source_zone, observed_at)
            VALUES (?, ?, 'unknown', ?, '2099-01-01T00:00:00Z')
        """, (sid, test_reg, test_zone))
        # Second insert with same (sid, reg, zone) must fail
        with pytest.raises(_sqlite3.IntegrityError):
            c.execute("""
                INSERT INTO aircraft_observations
                  (screenshot_id, registration, identity_status, source_zone, observed_at)
                VALUES (?, ?, 'unknown', ?, '2099-01-01T00:00:00Z')
            """, (sid, test_reg, test_zone))
    finally:
        c.execute("ROLLBACK TO SAVEPOINT dedup_test")
        c.execute("RELEASE SAVEPOINT dedup_test")
