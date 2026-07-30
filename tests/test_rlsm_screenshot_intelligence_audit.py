from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from fr24 import (
    rlsm_flight_track_certified,
    rlsm_frame_artifacts,
    rlsm_intelligence_audit,
    rlsm_intelligence_audit_v2,
    rlsm_intelligence_pipeline,
    rlsm_standalone_icons,
)

REPO = Path(__file__).resolve().parents[1]
SCHEMA = REPO / "data" / "rlsm" / "schema.sql"


def make_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "rlsm.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.commit()
    conn.close()
    return db_path


def insert_screenshot(
    conn: sqlite3.Connection,
    *,
    rel_path: str,
    sha256: str,
    ocr_status: str = "pending",
) -> int:
    cursor = conn.execute(
        """INSERT INTO screenshots
           (sha256, filename, rel_path, month_bucket, filename_ts, ext,
            size_bytes, width, height, phash, ingest_status, ocr_status,
            ingested_at)
           VALUES (?, ?, ?, '2026-01', '2026-01-01T00:00:00-04:00',
                   '.png', 10, 100, 200, '0', 'ok', ?,
                   '2026-01-01T00:00:00Z')""",
        (sha256, Path(rel_path).name, rel_path, ocr_status),
    )
    return int(cursor.lastrowid)


def insert_ocr_receipt(
    conn: sqlite3.Connection,
    screenshot_id: int,
    *,
    status: str = "ok",
    error: str | None = None,
) -> None:
    conn.execute(
        """INSERT INTO ocr_observations
           (screenshot_id, zone, raw_text, raw_lines_json, confidence_mean,
            confidence_min, n_words, engine, engine_version, psm,
            ocr_status, ocr_error, observed_at)
           VALUES (?, 'label_layer', 'San Juan', '[]', 90, 80, 2,
                   'tesseract', '5', 6, ?, ?, '2026-01-01T00:00:00Z')""",
        (screenshot_id, status, error),
    )


def test_accounting_reports_complete_and_mismatched_corpora(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "frame.png").write_bytes(b"frame")

    conn = sqlite3.connect(db_path)
    insert_screenshot(conn, rel_path="frame.png", sha256="a" * 64)
    conn.commit()

    complete, errors = rlsm_intelligence_audit.audit_accounting(conn, corpus)
    assert complete["complete"] is True
    assert complete["coverage_percent"] == 100.0
    assert errors == []

    (corpus / "extra.png").write_bytes(b"extra")
    insert_screenshot(conn, rel_path="missing.png", sha256="b" * 64)
    conn.commit()
    mismatch, errors = rlsm_intelligence_audit.audit_accounting(conn, corpus)
    conn.close()

    assert mismatch["complete"] is False
    assert mismatch["disk_files_absent_from_database"] == 1
    assert mismatch["database_files_absent_from_disk"] == 1
    assert {item["kind"] for item in errors} == {
        "disk_file_absent_from_database",
        "database_file_absent_from_disk",
    }


def test_ocr_integrity_records_each_failure_class(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    conn = sqlite3.connect(db_path)
    ok_id = insert_screenshot(
        conn,
        rel_path="ok.png",
        sha256="a" * 64,
        ocr_status="ok",
    )
    insert_ocr_receipt(conn, ok_id)
    insert_screenshot(
        conn,
        rel_path="missing-receipt.png",
        sha256="b" * 64,
        ocr_status="pending",
    )
    failed_id = insert_screenshot(
        conn,
        rel_path="errorless.png",
        sha256="c" * 64,
        ocr_status="failed",
    )
    insert_ocr_receipt(conn, failed_id, status="failed", error=None)
    conn.execute(
        """INSERT INTO processing_runs
           (run_kind, started_at, status, n_inputs, n_processed, n_failed)
           VALUES ('broken_completed', '2026-01-01T00:00:00Z',
                   'completed', 2, 1, 0)"""
    )
    conn.execute(
        """INSERT INTO processing_runs
           (run_kind, started_at, status, n_inputs, n_processed, n_failed)
           VALUES ('stale', '2026-01-01T00:00:00Z',
                   'in_progress', 1, 0, 0)"""
    )
    conn.commit()

    base_result, errors = rlsm_intelligence_audit.audit_ocr_integrity(conn)
    strict_result, strict_errors = rlsm_intelligence_audit_v2.audit_ocr_integrity(conn)
    conn.close()

    kinds = {item["kind"] for item in errors}
    assert "missing_ocr_receipt" in kinds
    assert "failed_ocr_without_error" in kinds
    assert "completed_run_with_unaccounted_inputs" in kinds
    assert "processing_run_left_in_progress" in kinds
    assert base_result["silent_failure_count"] == 3
    assert strict_result["silent_failure_count"] == 4
    assert strict_result["complete"] is False
    assert strict_errors == errors


def test_v2_capabilities_and_gates_require_receipt_coverage(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    conn = sqlite3.connect(db_path)
    screenshot_id = insert_screenshot(
        conn,
        rel_path="frame.png",
        sha256="a" * 64,
        ocr_status="ok",
    )
    insert_ocr_receipt(conn, screenshot_id)
    rlsm_frame_artifacts.ensure_schema(conn)
    rlsm_standalone_icons.ensure_schema(conn)
    rlsm_flight_track_certified.ensure_schema(conn)
    conn.execute(
        """INSERT INTO frame_observations
           (screenshot_id, frame_type, provider, orientation, confidence,
            classification_method, evidence_json, review_status, observed_at)
           VALUES (?, 'fr24_map', 'flightradar24', 'portrait', 0.8,
                   'test', '{}', 'unreviewed', '2026-01-01T00:00:00Z')""",
        (screenshot_id,),
    )
    frame_id = int(conn.execute("SELECT frame_obs_id FROM frame_observations").fetchone()[0])
    conn.execute(
        """INSERT INTO gui_artifact_observations
           (screenshot_id, frame_obs_id, artifact_type, raw_text,
            normalized_text, extraction_status, method, observed_at)
           VALUES (?, ?, 'top_navigation', 'FR24', 'FR24', 'ok',
                   'test', '2026-01-01T00:00:00Z')""",
        (screenshot_id, frame_id),
    )
    conn.execute(
        """INSERT INTO track_extraction_receipts
           (screenshot_id, method, cv_status, candidate_count,
            extractor_mode, heuristic_fallback, observed_at)
           VALUES (?, 'pixel_first_track_v2', 'no_track_detected', 0,
                   'test', 1, '2026-01-01T00:00:00Z')""",
        (screenshot_id,),
    )
    conn.execute(
        """INSERT INTO icon_scan_receipts
           (screenshot_id, method, scan_status, regions_scanned,
            windows_scanned, candidates_inserted, observed_at)
           VALUES (?, 'standalone_tiled_salience_v1', 'ok', 3, 20, 0,
                   '2026-01-01T00:00:00Z')""",
        (screenshot_id,),
    )
    conn.commit()

    capabilities = rlsm_intelligence_audit_v2.audit_capabilities(conn)
    conn.close()
    gates = rlsm_intelligence_audit_v2.build_gates(
        {
            "complete": True,
            "coverage_percent": 100.0,
            "disk_files_absent_from_database": 0,
            "database_files_absent_from_disk": 0,
        },
        {"complete": True, "silent_failure_count": 0},
        capabilities,
        {"complete": True, "unsupported_rows_with_coordinates": 0},
        {"complete": True, "coverage_percent": 100.0, "missing_core_fields": 0},
        {"status": "missing", "records": 0, "label_metrics": None},
    )

    assert capabilities["track_extraction_receipts"]["status"] == "complete"
    assert capabilities["standalone_icon_scan"]["status"] == "complete"
    assert gates["track_extraction_accounting_100"]["status"] == "PASS"
    assert gates["icon_scan_accounting_100"]["status"] == "PASS"
    assert gates["gui_artifact_frame_coverage_100"]["status"] == "PASS"
    assert gates["icon_capture_complete"]["status"] == "FAIL"
    assert gates["location_label_recall_gte_0_98"]["status"] == "BLOCKED"


def test_gold_evaluation_reports_unresolved_and_wrong_size(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    conn = sqlite3.connect(db_path)
    gold = tmp_path / "gold.jsonl"
    gold.write_text(
        json.dumps({"filename": "not-in-database.png", "labels": ["San Juan"]})
        + "\n",
        encoding="utf-8",
    )

    result, errors = rlsm_intelligence_audit.evaluate_gold(
        conn,
        gold,
        expected_size=300,
    )
    conn.close()

    assert result["status"] == "incomplete"
    assert result["unresolved_records"] == 1
    assert {item["kind"] for item in errors} == {
        "gold_screenshot_unresolved",
        "gold_sample_wrong_size",
    }


def test_full_v2_audit_writes_fail_closed_reports(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "frame.png").write_bytes(b"frame")
    conn = sqlite3.connect(db_path)
    screenshot_id = insert_screenshot(
        conn,
        rel_path="frame.png",
        sha256="a" * 64,
        ocr_status="ok",
    )
    insert_ocr_receipt(conn, screenshot_id)
    conn.commit()
    conn.close()

    outputs = tmp_path / "outputs"
    report = rlsm_intelligence_audit_v2.run(
        db_path=db_path,
        corpus_root=corpus,
        gold_path=tmp_path / "missing-gold.jsonl",
        outputs_dir=outputs,
        sample_limit=1,
    )

    assert report["schema_version"] == "skywatcher_screenshot_intelligence_audit.v2"
    assert report["certification_status"] == "FAIL"
    assert report["gates"]["location_label_recall_gte_0_98"]["status"] == "BLOCKED"
    assert (outputs / "screenshot_intelligence_audit.json").exists()
    assert (outputs / "screenshot_intelligence_audit.md").exists()
    assert (outputs / "screenshot_intelligence_errors.jsonl").exists()
    assert (outputs / "screenshot_intelligence_structured_sample.jsonl").exists()


def test_pipeline_stage_resolution_and_icon_geometry_helpers() -> None:
    args = argparse.Namespace(
        stage=None,
        from_stage="tracks",
        skip_icons=False,
        skip_tracks=False,
    )
    stages = rlsm_intelligence_pipeline.resolve_stages(args)
    assert stages[0] == "preflight"
    assert stages[1] == "tracks"
    assert "audit" in stages

    direct = argparse.Namespace(
        stage="frames",
        from_stage=None,
        skip_icons=False,
        skip_tracks=False,
    )
    assert rlsm_intelligence_pipeline.resolve_stages(direct) == ["preflight", "frames"]

    portrait = rlsm_standalone_icons._regions(100, 200)
    landscape = rlsm_standalone_icons._regions(200, 100)
    windows = rlsm_standalone_icons._windows((0, 0, 100, 100))
    assert {name for name, _box in portrait} == {"map", "top_gui", "bottom_gui"}
    assert {name for name, _box in landscape} == {
        "map",
        "top_gui",
        "side_gui",
        "bottom_gui",
    }
    assert len(windows) == 4
    assert rlsm_standalone_icons._overlap_ratio((0, 0, 10, 10), (5, 5, 10, 10)) == 0.25
    assert rlsm_standalone_icons._near_existing(
        (0, 0, 10, 10),
        [(2, 2, 10, 10)],
    ) is True
    assert rlsm_standalone_icons._near_existing(
        (0, 0, 10, 10),
        [(100, 100, 10, 10)],
    ) is False
