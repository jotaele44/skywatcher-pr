"""Regression gates for the interactive screenshot -> Master Flight Log workflow."""

from __future__ import annotations

import base64
import io
import json
import sqlite3
import zipfile
from pathlib import Path

from skywatcher.fr24.screenshot_processor import ScreenshotJobStore


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9ZQmcAAAAASUVORK5CYII="
)


def _upload(name: str, payload: bytes) -> dict[str, str]:
    return {
        "name": name,
        "content_base64": base64.b64encode(payload).decode("ascii"),
    }


def _store(tmp_path: Path) -> ScreenshotJobStore:
    return ScreenshotJobStore(
        db_path=tmp_path / "jobs.sqlite3",
        job_root=tmp_path / "jobs",
        rlsm_db=tmp_path / "rlsm.sqlite3",
        corpus_db=tmp_path / "corpus.sqlite3",
    )


def _seed_corpus(path: Path) -> int:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE flight_corpus_records (
            corpus_record_id INTEGER PRIMARY KEY AUTOINCREMENT,
            corpus_uid TEXT NOT NULL,
            snapshot_id INTEGER NOT NULL,
            source_flight_id_raw TEXT,
            callsign_raw TEXT,
            start_time_utc TEXT,
            end_time_utc TEXT,
            identity_status TEXT NOT NULL DEFAULT 'unresolved'
        );
        CREATE TABLE flight_source_manifestations (
            manifestation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            corpus_record_id INTEGER NOT NULL,
            source_kind TEXT NOT NULL,
            source_folder_raw TEXT,
            source_filename_raw TEXT,
            source_sha256 TEXT,
            source_mtime_raw TEXT,
            binding_status TEXT NOT NULL,
            raw_manifest_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    cursor = conn.execute(
        """
        INSERT INTO flight_corpus_records
            (corpus_uid, snapshot_id, callsign_raw, start_time_utc, end_time_utc, identity_status)
        VALUES ('mfl:test', 1, 'TEST123', '2026-09-30T12:00:00Z', '2026-09-30T13:00:00Z', 'unresolved')
        """
    )
    record_id = int(cursor.lastrowid)
    conn.commit()
    conn.close()
    return record_id


def test_zip_manifestations_preserve_duplicate_payload_paths(tmp_path: Path) -> None:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("a/one.png", PNG_1X1)
        archive.writestr("b/two.png", PNG_1X1)
        archive.writestr("notes/readme.txt", "not an image")

    store = _store(tmp_path)
    job = store.create_job([_upload("batch.zip", payload.getvalue())])

    assert job["source_count"] == 1
    assert job["manifestation_count"] == 3
    assert job["processable_count"] == 2
    image_rows = [row for row in job["files"] if row["media_kind"] == "native_image"]
    assert len(image_rows) == 2
    assert image_rows[0]["payload_sha256"] == image_rows[1]["payload_sha256"]
    assert image_rows[0]["source_locator"] != image_rows[1]["source_locator"]
    assert image_rows[1]["within_job_duplicate_of"] == image_rows[0]["ordinal"]


def test_reconciliation_is_candidate_not_identity(tmp_path: Path) -> None:
    store = _store(tmp_path)
    record_id = _seed_corpus(store.corpus_db)
    job = store.create_job([_upload("2026-09-30 12-30-00.png", PNG_1X1)])

    conn = store._connect()
    try:
        file_id = conn.execute(
            "SELECT file_id FROM screenshot_processing_files WHERE job_id=?",
            (job["job_id"],),
        ).fetchone()["file_id"]
        conn.execute(
            """
            UPDATE screenshot_processing_files
            SET extracted_fields_json=?, extraction_status='PROVISIONAL'
            WHERE file_id=?
            """,
            (json.dumps({"callsign": "TEST123"}), file_id),
        )
        conn.commit()
        store._run_reconciliation(conn, job["job_id"])
    finally:
        conn.close()

    result = store.get_job(job["job_id"])
    row = result["files"][0]
    assert row["reconciliation_status"] == "CANDIDATE_NOT_IDENTITY"
    assert row["candidate_matches"][0]["corpus_record_id"] == record_id
    assert row["candidate_matches"][0]["relationship"] == "CANDIDATE_NOT_IDENTITY"

    corpus = sqlite3.connect(store.corpus_db)
    try:
        identity = corpus.execute(
            "SELECT identity_status FROM flight_corpus_records WHERE corpus_record_id=?",
            (record_id,),
        ).fetchone()[0]
    finally:
        corpus.close()
    assert identity == "unresolved"


def test_commit_persists_candidate_manifestation_without_identity_promotion(tmp_path: Path) -> None:
    store = _store(tmp_path)
    record_id = _seed_corpus(store.corpus_db)
    job = store.create_job([_upload("capture.png", PNG_1X1)])

    conn = store._connect()
    try:
        row = conn.execute(
            "SELECT file_id FROM screenshot_processing_files WHERE job_id=?",
            (job["job_id"],),
        ).fetchone()
        file_id = int(row["file_id"])
        candidates = [
            {
                "corpus_record_id": record_id,
                "relationship": "CANDIDATE_NOT_IDENTITY",
                "basis": ["EXACT_CALLSIGN"],
            }
        ]
        conn.execute(
            """
            UPDATE screenshot_processing_files
            SET candidate_matches_json=?, reconciliation_status='CANDIDATE_NOT_IDENTITY'
            WHERE file_id=?
            """,
            (json.dumps(candidates), file_id),
        )
        conn.commit()
    finally:
        conn.close()

    receipt = store.commit_candidate_links(
        job["job_id"],
        [
            {
                "file_id": file_id,
                "corpus_record_id": record_id,
                "rationale": "Reviewed exact callsign candidate; retained as candidate evidence only.",
            }
        ],
    )
    assert receipt == {
        "job_id": job["job_id"],
        "committed": 1,
        "identity_promotions": 0,
    }

    corpus = sqlite3.connect(store.corpus_db)
    try:
        manifestation = corpus.execute(
            """
            SELECT binding_status, raw_manifest_json
            FROM flight_source_manifestations
            WHERE corpus_record_id=?
            """,
            (record_id,),
        ).fetchone()
        identity = corpus.execute(
            "SELECT identity_status FROM flight_corpus_records WHERE corpus_record_id=?",
            (record_id,),
        ).fetchone()[0]
    finally:
        corpus.close()

    assert manifestation[0] == "candidate"
    assert json.loads(manifestation[1])["relationship"] == "CANDIDATE_NOT_IDENTITY"
    assert identity == "unresolved"


def test_job_rejects_aggregate_oversize_before_writing_sources(tmp_path: Path, monkeypatch) -> None:
    import skywatcher.fr24.screenshot_processor as module

    monkeypatch.setattr(module, "MAX_JOB_BYTES", 3)
    store = _store(tmp_path)

    try:
        store.create_job([_upload("a.png", b"12"), _upload("b.png", b"34")])
    except module.ScreenshotProcessingError as exc:
        assert "aggregate limit" in str(exc)
    else:
        raise AssertionError("oversize job should fail closed")

    assert not store.job_root.exists()
