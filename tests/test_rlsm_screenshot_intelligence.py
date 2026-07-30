from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from fr24 import (
    rlsm_flight_track_certified,
    rlsm_frame_artifacts,
    rlsm_intelligence_audit,
    rlsm_intelligence_audit_v2,
    rlsm_intelligence_export,
    rlsm_intelligence_pipeline,
    rlsm_intelligence_pipeline_v2,
    rlsm_ocr_certified,
    rlsm_provenance,
    rlsm_standalone_icons,
)
from fr24.track_vectorizer_strict import VectorizationReceipt, vectorize_image_receipt

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
    sha256: str = "a" * 64,
    ocr_status: str = "pending",
    width: int = 100,
    height: int = 200,
) -> int:
    cursor = conn.execute(
        """INSERT INTO screenshots
           (sha256, filename, rel_path, month_bucket, filename_ts, ext,
            size_bytes, width, height, phash, ingest_status, ocr_status,
            ingested_at)
           VALUES (?, ?, ?, '2026-01', '2026-01-01T00:00:00-04:00', '.png',
                   10, ?, ?, '0', 'ok', ?, '2026-01-01T00:00:00Z')""",
        (sha256, Path(rel_path).name, rel_path, width, height, ocr_status),
    )
    return int(cursor.lastrowid)


def test_vectorizer_receipt_distinguishes_runtime_failure() -> None:
    class BrokenExtractor:
        def extract(self, _image_path: str):
            raise RuntimeError("boom")

    receipt = vectorize_image_receipt("missing.png", extractor=BrokenExtractor())

    assert receipt.status == "failed"
    assert receipt.features is None
    assert "RuntimeError" in (receipt.error or "")
    assert receipt.candidate_count == 0


def test_certified_ocr_finish_marks_unprocessed_as_failed(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    conn = sqlite3.connect(db_path)
    cursor = conn.execute(
        """INSERT INTO processing_runs
           (run_kind, started_at, status, n_inputs, n_processed, n_failed)
           VALUES ('ocr_strict_parallel', '2026-01-01T00:00:00Z',
                   'in_progress', 2, 0, 0)"""
    )
    run_id = int(cursor.lastrowid)
    result = rlsm_ocr_certified._finish_run(
        conn,
        run_id=run_id,
        targets=2,
        processed=1,
        counts={"ok": 1, "partial": 0, "failed": 0},
        stopped_for_budget=True,
        unexpected_error=None,
    )
    row = conn.execute(
        "SELECT status, n_inputs, n_processed, n_failed, notes FROM processing_runs WHERE run_id=?",
        (run_id,),
    ).fetchone()
    conn.close()

    assert result["status"] == "failed"
    assert result["unprocessed"] == 1
    assert row[:4] == ("failed", 2, 1, 1)
    assert json.loads(row[4])["budget_exhausted"] is True


def test_certified_track_failure_is_receipted_and_falls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = make_db(tmp_path)
    source = tmp_path / "frame.png"
    source.write_bytes(b"not decoded because vectorizer is patched")
    conn = sqlite3.connect(db_path)
    sid = insert_screenshot(conn, rel_path=str(source), ocr_status="ok")
    conn.execute(
        """INSERT INTO aircraft_observations
           (screenshot_id, registration, speed_kt, heading_deg,
            identity_status, confidence, source_zone, raw_excerpt, observed_at)
           VALUES (?, 'N123AB', 120, 90, 'confirmed', 0.9,
                   'aircraft_card', 'N123AB', '2026-01-01T00:00:00Z')""",
        (sid,),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(
        rlsm_flight_track_certified,
        "vectorize_image_receipt",
        lambda _path: VectorizationReceipt(
            status="failed",
            features=None,
            error="decoder failed",
            candidate_count=0,
            extractor_mode="test",
        ),
    )
    result = rlsm_flight_track_certified.run(
        db_path=db_path,
        image_root=tmp_path,
    )
    conn = sqlite3.connect(db_path)
    feature = conn.execute(
        "SELECT path_shape, confidence, bbox_x FROM flight_track_features"
    ).fetchone()
    receipt = conn.execute(
        "SELECT cv_status, cv_error, heuristic_fallback FROM track_extraction_receipts"
    ).fetchone()
    conn.close()

    assert result["status"] == "failed"
    assert result["failed"] == 1
    assert feature == ("linear", 0.3, None)
    assert receipt == ("failed", "decoder failed", 1)


def test_frame_gui_and_map_state_are_persisted_without_invented_coordinates(
    tmp_path: Path,
) -> None:
    db_path = make_db(tmp_path)
    conn = sqlite3.connect(db_path)
    sid = insert_screenshot(
        conn,
        rel_path="data/FR24_baseline/frame.png",
        ocr_status="ok",
    )
    conn.execute(
        """INSERT INTO ocr_observations
           (screenshot_id, zone, bbox_x, bbox_y, bbox_w, bbox_h, raw_text,
            raw_lines_json, confidence_mean, confidence_min, n_words,
            engine, engine_version, psm, ocr_status, observed_at)
           VALUES (?, 'aircraft_card', 0, 20, 100, 80,
                   'N123AB Altitude Ground speed Route',
                   '[]', 90, 80, 5, 'tesseract', '5', 6, 'ok',
                   '2026-01-01T00:00:00Z')""",
        (sid,),
    )
    conn.execute(
        """INSERT INTO ocr_observations
           (screenshot_id, zone, bbox_x, bbox_y, bbox_w, bbox_h, raw_text,
            raw_lines_json, confidence_mean, confidence_min, n_words,
            engine, engine_version, psm, ocr_status, observed_at)
           VALUES (?, 'top_bar', 0, 0, 100, 20,
                   'Flightradar24', '[]', 90, 90, 1,
                   'tesseract', '5', 6, 'ok',
                   '2026-01-01T00:00:00Z')""",
        (sid,),
    )
    conn.commit()
    conn.close()

    result = rlsm_frame_artifacts.run(db_path)
    conn = sqlite3.connect(db_path)
    frame = conn.execute("SELECT frame_type, provider FROM frame_observations").fetchone()
    map_state = conn.execute(
        """SELECT center_lat, center_lon, zoom, bearing_deg,
                  extent_geojson, geolocation_status
           FROM map_state_observations"""
    ).fetchone()
    gui_count = conn.execute("SELECT COUNT(*) FROM gui_artifact_observations").fetchone()[0]
    conn.close()

    assert result["failed"] == 0
    assert frame == ("fr24_selected_flight", "flightradar24")
    assert map_state == (None, None, None, None, None, "unsupported")
    assert gui_count == 2


def test_standalone_icon_scan_is_provisional_and_receipted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pil_image = pytest.importorskip("PIL.Image")
    db_path = make_db(tmp_path)
    source = tmp_path / "frame.png"
    pil_image.new("RGB", (100, 200), "white").save(source)
    conn = sqlite3.connect(db_path)
    sid = insert_screenshot(conn, rel_path=str(source), ocr_status="ok")
    cursor = conn.execute(
        """INSERT INTO processing_runs
           (run_kind, started_at, status, n_inputs)
           VALUES ('standalone_icon_detect', '2026-01-01T00:00:00Z',
                   'in_progress', 1)"""
    )
    run_id = int(cursor.lastrowid)
    rlsm_standalone_icons.ensure_schema(conn)

    monkeypatch.setattr(
        "fr24.rlsm_icons.detect_in_window",
        lambda _rgb, _hsv: {
            "x": 5,
            "y": 5,
            "w": 10,
            "h": 10,
            "area": 70,
            "aspect": 1.0,
            "fill_ratio": 0.7,
            "hue_deg": 10.0,
            "saturation": 0.9,
            "value": 0.9,
            "ahash": "0123456789abcdef",
        },
    )
    result = rlsm_standalone_icons.scan_screenshot(
        conn,
        sid,
        str(source),
        run_id,
    )
    icon = conn.execute(
        """SELECT pin_id, icon_class, review_status
           FROM icon_observations ORDER BY icon_id LIMIT 1"""
    ).fetchone()
    receipt = conn.execute(
        """SELECT scan_status, candidates_inserted
           FROM icon_scan_receipts"""
    ).fetchone()
    conn.close()

    assert result["ok"] is True
    assert result["candidates"] > 0
    assert icon[0] is None
    assert icon[1] in {"unclassified_map_icon", "unclassified_gui_icon"}
    assert icon[2] == "needs_review"
    assert receipt[0] == "ok"
    assert receipt[1] == result["candidates"]


def test_icon_crop_has_source_and_artifact_hashes(tmp_path: Path) -> None:
    pil_image = pytest.importorskip("PIL.Image")
    from scripts import rlsm_capture_icon_crops

    db_path = make_db(tmp_path)
    source = tmp_path / "frame.png"
    pil_image.new("RGB", (40, 40), "white").save(source)
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    conn = sqlite3.connect(db_path)
    sid = insert_screenshot(
        conn,
        rel_path=str(source),
        sha256=source_sha,
        ocr_status="ok",
        width=40,
        height=40,
    )
    rlsm_standalone_icons.ensure_schema(conn)
    conn.execute(
        """INSERT INTO icon_observations
           (screenshot_id, bbox_x, bbox_y, bbox_w, bbox_h, centroid_x,
            centroid_y, area_px, aspect, fill_ratio, hue_deg, saturation,
            value, ahash, confidence, review_status, observed_at)
           VALUES (?, 5, 5, 10, 10, 10, 10, 80, 1, 0.8, 0, 0, 1,
                   '0123456789abcdef', 0.6, 'needs_review',
                   '2026-01-01T00:00:00Z')""",
        (sid,),
    )
    conn.commit()
    conn.close()

    output_root = tmp_path / "icons"
    manifest = tmp_path / "manifest.jsonl"
    result = rlsm_capture_icon_crops.run(
        db_path,
        image_root=tmp_path,
        output_root=output_root,
        manifest_path=manifest,
    )
    conn = sqlite3.connect(db_path)
    artifact = conn.execute(
        """SELECT source_sha256, crop_rel_path, crop_sha256, capture_status
           FROM icon_artifacts"""
    ).fetchone()
    conn.close()
    crop_path = Path(artifact[1])

    assert result["captured"] == 1
    assert artifact[0] == source_sha
    assert artifact[3] == "ok"
    assert crop_path.is_absolute()
    assert crop_path.exists()
    assert hashlib.sha256(crop_path.read_bytes()).hexdigest() == artifact[2]
    assert manifest.exists()


def test_field_level_provenance_backfill(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    conn = sqlite3.connect(db_path)
    sid = insert_screenshot(
        conn,
        rel_path="data/FR24_baseline/frame.png",
        ocr_status="ok",
    )
    conn.execute(
        """INSERT INTO ocr_observations
           (screenshot_id, zone, raw_text, raw_lines_json, confidence_mean,
            confidence_min, n_words, engine, engine_version, psm,
            ocr_status, observed_at)
           VALUES (?, 'label_layer', 'San Juan', '[]', 90, 80, 2,
                   'tesseract', '5', 6, 'ok',
                   '2026-01-01T00:00:00Z')""",
        (sid,),
    )
    conn.execute(
        """INSERT INTO labeled_pins
           (screenshot_id, raw_label, normalized_label, bbox_x, bbox_y,
            bbox_w, bbox_h, centroid_x, centroid_y, pin_type_guess,
            confidence, review_status, observed_at)
           VALUES (?, 'San Juan', 'San Juan', 10, 10, 40, 10, 30, 15,
                   'place', 0.9, 'unreviewed',
                   '2026-01-01T00:00:00Z')""",
        (sid,),
    )
    conn.commit()
    conn.close()

    result = rlsm_provenance.run(db_path)
    conn = sqlite3.connect(db_path)
    fields = conn.execute(
        """SELECT field_name, source_type, validation_outcome
           FROM extraction_field_provenance
           WHERE object_type='labeled_pin'"""
    ).fetchall()
    conn.close()

    assert result["fields"] > 0
    assert ("raw_label", "ocr_observation", "VALID") in fields
    assert ("confidence", "ocr_observation", "VALID") in fields


def test_gold_label_metrics_are_computed_without_promoting_missing_gold(
    tmp_path: Path,
) -> None:
    db_path = make_db(tmp_path)
    conn = sqlite3.connect(db_path)
    sid = insert_screenshot(
        conn,
        rel_path="data/FR24_baseline/frame.png",
        ocr_status="ok",
    )
    conn.execute(
        """INSERT INTO labeled_pins
           (screenshot_id, raw_label, normalized_label, confidence,
            review_status, observed_at)
           VALUES (?, 'San Juan', 'San Juan', 0.9, 'unreviewed',
                   '2026-01-01T00:00:00Z')""",
        (sid,),
    )
    conn.commit()
    gold = tmp_path / "gold.jsonl"
    gold.write_text(
        json.dumps(
            {
                "screenshot_id": sid,
                "labels": [{"text": "San Juan"}],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    metrics, errors = rlsm_intelligence_audit.evaluate_gold(
        conn,
        gold,
        expected_size=1,
    )
    conn.close()

    assert errors == []
    assert metrics["status"] == "ready"
    assert metrics["label_metrics"]["precision"] == 1.0
    assert metrics["label_metrics"]["recall"] == 1.0


def test_certification_failure_precedes_blocked() -> None:
    gates = {
        name: {"status": "PASS", "evidence": {}}
        for name in rlsm_intelligence_audit_v2.REQUIRED_GATES
    }
    gates["screenshot_accounting_100"]["status"] = "FAIL"
    gates["location_label_recall_gte_0_98"]["status"] = "BLOCKED"

    assert rlsm_intelligence_audit_v2._certification_status(gates) == "FAIL"


def test_extended_export_is_deterministic(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    conn = sqlite3.connect(db_path)
    insert_screenshot(
        conn,
        rel_path="data/FR24_baseline/frame.png",
        ocr_status="ok",
    )
    conn.commit()
    conn.close()
    rlsm_frame_artifacts.run(db_path)

    out = tmp_path / "exports"
    first = rlsm_intelligence_export.export_all(db_path, out)
    first_sha = {item["table"]: item["sha256"] for item in first["exports"] if item["sha256"]}
    second = rlsm_intelligence_export.export_all(db_path, out)
    second_sha = {item["table"]: item["sha256"] for item in second["exports"] if item["sha256"]}

    assert first_sha == second_sha
    assert (out / "manifest.json").exists()


def test_v2_pipeline_policy_promotes_certified_stages() -> None:
    original = dict(rlsm_intelligence_pipeline.STAGE_FUNCS)
    original_refresh = rlsm_intelligence_pipeline._refresh_derived
    original_status = rlsm_intelligence_pipeline.collect_status
    try:
        rlsm_intelligence_pipeline_v2.install_policy()
        assert (
            rlsm_intelligence_pipeline.STAGE_FUNCS["ocr"] is rlsm_intelligence_pipeline_v2.stage_ocr
        )
        assert (
            rlsm_intelligence_pipeline.STAGE_FUNCS["tracks"]
            is rlsm_intelligence_pipeline_v2.stage_tracks
        )
        assert (
            rlsm_intelligence_pipeline.STAGE_FUNCS["audit"]
            is rlsm_intelligence_pipeline_v2.stage_audit
        )
    finally:
        rlsm_intelligence_pipeline.STAGE_FUNCS.clear()
        rlsm_intelligence_pipeline.STAGE_FUNCS.update(original)
        rlsm_intelligence_pipeline._refresh_derived = original_refresh
        rlsm_intelligence_pipeline.collect_status = original_status
