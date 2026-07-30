from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from fr24 import rlsm_icons_certified
from fr24 import rlsm_intelligence_audit_v2
from fr24 import rlsm_ocr_certified
from fr24 import rlsm_source_reconcile
from fr24 import rlsm_standalone_icons_certified


def _ledger_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE screenshots (
            screenshot_id INTEGER PRIMARY KEY,
            rel_path TEXT NOT NULL,
            ingest_status TEXT NOT NULL,
            ingest_error TEXT,
            ocr_status TEXT NOT NULL DEFAULT 'pending'
        );
        CREATE TABLE processing_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_kind TEXT NOT NULL,
            started_at TEXT,
            ended_at TEXT,
            status TEXT NOT NULL,
            n_inputs INTEGER DEFAULT 0,
            n_processed INTEGER DEFAULT 0,
            n_failed INTEGER DEFAULT 0,
            notes TEXT
        );
        """
    )
    conn.commit()


def test_source_reconcile_preserves_and_marks_missing_rows(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    corpus = repo / "data" / "FR24_baseline"
    corpus.mkdir(parents=True)
    (corpus / "present.png").write_bytes(b"not-decoded-by-reconciliation")
    db = repo / "data" / "rlsm" / "ledger.sqlite"
    db.parent.mkdir(parents=True)

    conn = sqlite3.connect(db)
    _ledger_schema(conn)
    conn.executemany(
        """INSERT INTO screenshots
           (screenshot_id, rel_path, ingest_status, ingest_error, ocr_status)
           VALUES (?, ?, 'ok', NULL, 'pending')""",
        [
            (1, "data/FR24_baseline/present.png"),
            (2, "data/FR24_baseline/absent.png"),
        ],
    )
    conn.execute(
        """INSERT INTO processing_runs
           (run_kind, started_at, status, n_inputs, n_processed, n_failed)
           VALUES ('ocr_parallel', '2026-07-30T00:00:00Z', 'in_progress', 2, 0, 0)"""
    )
    conn.commit()
    conn.close()

    result = rlsm_source_reconcile.reconcile(
        db_path=db,
        repo_root=repo,
        corpus_root=corpus,
        output_path=repo / "outputs" / "reconciliation.json",
    )

    assert result["database_rows"] == 2
    assert result["disk_images"] == 1
    assert result["active_rows"] == 1
    assert result["newly_missing_rows"] == 1
    assert result["stale_runs_closed"] == 1

    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT screenshot_id, ingest_status FROM screenshots ORDER BY screenshot_id"
    ).fetchall()
    stale_status = conn.execute(
        "SELECT status FROM processing_runs WHERE run_kind='ocr_parallel'"
    ).fetchone()[0]
    conn.close()
    assert rows == [(1, "ok"), (2, "missing_source")]
    assert stale_status == "failed"


def test_failed_ocr_frames_fail_the_processing_run() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE processing_runs (
               run_id INTEGER PRIMARY KEY,
               ended_at TEXT,
               status TEXT,
               n_inputs INTEGER,
               n_processed INTEGER,
               n_failed INTEGER,
               notes TEXT
           )"""
    )
    conn.execute(
        "INSERT INTO processing_runs (run_id, status) VALUES (1, 'in_progress')"
    )
    result = rlsm_ocr_certified._finish_run(
        conn,
        run_id=1,
        targets=200,
        processed=200,
        counts={"ok": 0, "partial": 0, "failed": 200},
        stopped_for_budget=False,
        unexpected_error=None,
    )
    persisted = conn.execute(
        "SELECT status, n_failed FROM processing_runs WHERE run_id=1"
    ).fetchone()
    conn.close()
    assert result["status"] == "failed"
    assert persisted == ("failed", 200)


def test_standalone_icon_filter_rejects_saturated_texture() -> None:
    saturated = {
        "w": 52,
        "h": 52,
        "area": 1800,
        "aspect": 1.0,
        "fill_ratio": 0.85,
        "saturation": 0.4,
        "value": 0.5,
    }
    plausible = {
        "w": 18,
        "h": 20,
        "area": 160,
        "aspect": 1.2,
        "fill_ratio": 0.44,
        "saturation": 0.5,
        "value": 0.8,
    }
    window = (0, 0, 64, 64)
    assert not rlsm_standalone_icons_certified._plausible(saturated, window)
    assert rlsm_standalone_icons_certified._plausible(plausible, window)


def test_empty_icon_channel_clusters_without_stage_failure(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE icon_observations (
               icon_id INTEGER PRIMARY KEY,
               screenshot_id INTEGER,
               pin_id INTEGER,
               ahash TEXT,
               hue_deg REAL,
               saturation REAL,
               value REAL,
               area_px INTEGER,
               aspect REAL,
               fill_ratio REAL,
               cluster_id INTEGER,
               icon_class TEXT
           )"""
    )
    naming_file = tmp_path / "icon_classes.generated.json"
    result = rlsm_icons_certified._cluster(conn, naming_file)
    conn.close()
    assert result == {"distinct_hashes": 0, "clusters": 0, "icons_total": 0}
    assert naming_file.exists()


def test_symlinked_corpus_uses_canonical_repository_paths(tmp_path: Path) -> None:
    repo = tmp_path / "worktree"
    external = tmp_path / "private-corpus"
    external.mkdir()
    (external / "frame.png").write_bytes(b"frame")
    link = repo / "data" / "FR24_baseline"
    link.parent.mkdir(parents=True)
    os.symlink(external, link, target_is_directory=True)

    prior_repo = rlsm_intelligence_audit_v2.REPO
    rlsm_intelligence_audit_v2.REPO = repo
    try:
        manifest = rlsm_intelligence_audit_v2._disk_manifest(link)
    finally:
        rlsm_intelligence_audit_v2.REPO = prior_repo

    assert set(manifest) == {"data/FR24_baseline/frame.png"}
