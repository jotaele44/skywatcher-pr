"""Bounded regression gates for the screenshot-to-MFL staging seam."""
from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from skywatcher.fr24.screenshot_jobs import ScreenshotJobs, validate_settings
from skywatcher.fr24.screenshot_rlsm_adapter import provisional_fields


def fake_extractor(path, sha, root, rlsm_db, corpus_db, *, filename_raw=None):
    assert hashlib.sha256(path.read_bytes()).hexdigest() == sha
    assert filename_raw
    return {
        "status": "NEEDS_REVIEW",
        "screenshot_id": 12,
        "fields": {"registration": {"value": "N123AB", "certification": "CANDIDATE_NOT_IDENTITY"}},
        "contradictions": [],
        "candidates": [],
    }


def test_strict_settings_reject_unimplemented_promotion():
    assert validate_settings({}) == {
        "ocr_mode": "local", "vision_mode": "off", "duplicate_mode": "exact"
    }
    with pytest.raises(ValueError, match="not implemented"):
        validate_settings({"vision_mode": "comprehensive"})
    with pytest.raises(ValueError, match="unsupported"):
        validate_settings({"auto_publish": True})


def test_manifest_conserves_same_payload_at_distinct_source_paths(tmp_path):
    service = ScreenshotJobs(tmp_path, extractor=fake_extractor)
    first = service.create([("photo-a.png", b"same-image"), ("photo-b.png", b"same-image")])
    assert first["total"] == 2
    assert first["complete"] == 0
    service._drain()
    result = service.detail(first["job_id"], include_items=True)
    assert result["status"] == "READY_FOR_REVIEW"
    assert result["complete"] == result["total"] == 2
    assert len(result["sources"]) == 2
    assert result["sources"][0]["sha256"] == result["sources"][1]["sha256"]
    assert len({r["filename_raw"] for r in result["items"]}) == 2
    assert all(item["status"] == "NEEDS_REVIEW" for item in result["items"])
    assert all(item["candidates"] == [] for item in result["items"])


def test_zip_paths_and_duplicate_payloads_are_preserved_without_traversal(tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../../escape.png", b"identical")
        archive.writestr("nested/second.png", b"identical")
        archive.writestr("unsupported.txt", b"not an image")
    service = ScreenshotJobs(tmp_path, extractor=fake_extractor)
    result = service.create([("archive.zip", buffer.getvalue())])
    full = service.detail(result["job_id"], include_items=True)
    assert full["total"] == 3
    assert full["counts"] == {"BLOCKED": 1, "QUEUED": 2}
    assert full["items"][0]["member_path"] == "0:../../escape.png"
    assert full["items"][1]["member_path"] == "1:nested/second.png"
    assert full["items"][0]["sha256"] == full["items"][1]["sha256"]
    assert not (tmp_path / "escape.png").exists()
    service._drain()
    terminal = service.detail(result["job_id"], include_items=True)
    assert terminal["status"] == "COMPLETE_WITH_BLOCKERS"
    assert terminal["complete"] == terminal["total"] == 3
    assert terminal["items"][2]["error"] == "unsupported source type"


def test_failed_extractor_is_explicit_and_cannot_report_certified(tmp_path):
    def fails(*args, **kwargs):
        raise RuntimeError("OCR dependency missing")
    service = ScreenshotJobs(tmp_path, extractor=fails)
    run = service.create([("one.png", b"source")])
    service._drain()
    result = service.detail(run["job_id"], include_items=True)
    assert result["status"] == "COMPLETE_WITH_BLOCKERS"
    assert result["counts"] == {"FAILED": 1}
    assert "OCR dependency missing" in result["items"][0]["error"]


def test_restart_resumes_only_unfinished_items(tmp_path):
    service = ScreenshotJobs(tmp_path, extractor=fake_extractor)
    run = service.create([("a.png", b"a"), ("b.png", b"b")])
    with service._connect() as conn:
        rows = conn.execute("SELECT item_id FROM items ORDER BY ordinal").fetchall()
        conn.execute("UPDATE jobs SET status='RUNNING' WHERE job_id=?", (run["job_id"],))
        conn.execute("UPDATE items SET status='NEEDS_REVIEW' WHERE item_id=?", (rows[0][0],))
        conn.execute("UPDATE items SET status='RUNNING' WHERE item_id=?", (rows[1][0],))
    restarted = ScreenshotJobs(tmp_path, extractor=fake_extractor)
    assert restarted.detail(run["job_id"])["counts"] == {"NEEDS_REVIEW": 1, "QUEUED": 1}
    restarted._drain()
    assert restarted.detail(run["job_id"])["counts"] == {"NEEDS_REVIEW": 2}


def test_review_is_not_a_canonical_flight_promotion(tmp_path):
    service = ScreenshotJobs(tmp_path, extractor=fake_extractor)
    run = service.create([("one.png", b"source")])
    service._drain()
    item = service.detail(run["job_id"], include_items=True)["items"][0]
    with pytest.raises(ValueError, match="3"):
        service.review(run["job_id"], item["item_id"], "")
    accepted = service.review(run["job_id"], item["item_id"], "OCR field reviewed; identity remains unbound")
    assert accepted["items"][0]["status"] == "REVIEWED"
    assert accepted["items"][0]["candidates"] == []
    assert accepted["status"] == "READY_FOR_REVIEW"  # run status is immutable history


def test_conflicting_ocr_registration_is_not_silently_selected():
    fields, contradictions = provisional_fields([
        {"obs_id": 1, "zone": "aircraft_card", "raw_text": "N123AB 1000 ft",
         "confidence_mean": 94, "ocr_status": "ok"},
        {"obs_id": 2, "zone": "top_bar", "raw_text": "N987ZY",
         "confidence_mean": 96, "ocr_status": "ok"},
    ])
    assert "registration" not in fields
    assert contradictions[0]["class"] == "IDENTITY"
    assert contradictions[0]["status"] == "UNRESOLVED"
    assert set(contradictions[0]["raw_registration_candidates"]) == {"N123AB", "N987ZY"}


def test_authenticated_access_fails_closed(monkeypatch):
    fastapi = pytest.importorskip("fastapi")
    from server.backend.screenshot_router import require_screenshot_access

    monkeypatch.delenv("SKYWATCHER_SCREENSHOT_TOKEN", raising=False)
    monkeypatch.delenv("PRII_WRITE_TOKEN", raising=False)
    with pytest.raises(fastapi.HTTPException) as exc:
        require_screenshot_access(SimpleNamespace(headers={}))
    assert exc.value.status_code == 503
    monkeypatch.setenv("SKYWATCHER_SCREENSHOT_TOKEN", "fixture-secret")
    with pytest.raises(fastapi.HTTPException) as exc:
        require_screenshot_access(SimpleNamespace(headers={"authorization": "Bearer wrong"}))
    assert exc.value.status_code == 401
    require_screenshot_access(SimpleNamespace(headers={"authorization": "Bearer fixture-secret"}))


def test_rlsm_exact_byte_reuse_and_complete_corpus_candidate_set(tmp_path, monkeypatch):
    pytest.importorskip("PIL")
    from fr24 import rlsm_ocr
    from skywatcher.fr24 import screenshot_rlsm_adapter as adapter

    corpus = tmp_path / "data" / "skywatcher.db"
    corpus.parent.mkdir(parents=True)
    with sqlite3.connect(corpus) as conn:
        conn.execute("""CREATE TABLE flight_corpus_records (
            corpus_record_id INTEGER, snapshot_id INTEGER, corpus_uid TEXT,
            callsign_raw TEXT, start_time_utc TEXT, end_time_utc TEXT)""")
        conn.executemany("INSERT INTO flight_corpus_records VALUES (?,?,?,?,?,?)", [
            (1, 5, "mfl:1", "ABC123", None, None),
            (2, 6, "mfl:2", "ABC123", None, None),
        ])
    schema = Path(__file__).resolve().parents[1] / "data" / "rlsm" / "schema.sql"
    (tmp_path / "data" / "rlsm").mkdir(parents=True)
    (tmp_path / "data" / "rlsm" / "schema.sql").write_bytes(schema.read_bytes())
    from PIL import Image
    first = tmp_path / "inputs" / "screenshots" / "first.png"
    second = tmp_path / "inputs" / "screenshots" / "second.png"
    first.parent.mkdir(parents=True)
    Image.new("RGB", (20, 20)).save(first)
    second.write_bytes(first.read_bytes())
    sha = hashlib.sha256(first.read_bytes()).hexdigest()
    monkeypatch.setattr(adapter.shutil, "which", lambda _: "/usr/bin/tesseract")
    monkeypatch.setattr(rlsm_ocr, "pytesseract", object())
    observed = []

    def stub(conn, sid, rel, run_id):
        observed.append(sid)
        conn.execute("""INSERT INTO ocr_observations
           (screenshot_id,run_id,zone,raw_text,confidence_mean,ocr_status,observed_at)
           VALUES (?,?,?,'ABC123 1000 ft',92,'ok',datetime('now'))""",
           (sid, run_id, "aircraft_card"))
        conn.execute("UPDATE screenshots SET ocr_status='ok' WHERE screenshot_id=?", (sid,))
        conn.commit()
        return {"ok": True, "n_obs": 1}

    monkeypatch.setattr(rlsm_ocr, "process_screenshot", stub)
    rlsm = tmp_path / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
    one = adapter.extract_into_rlsm(first, sha, tmp_path, rlsm, corpus, filename_raw="IMG A.png")
    two = adapter.extract_into_rlsm(second, sha, tmp_path, rlsm, corpus, filename_raw="IMG B.png")
    assert len(observed) == 1
    assert one["status"] == two["status"] == "NEEDS_REVIEW"
    assert two["was_reused"] is True
    assert len(one["candidates"]) == len(two["candidates"]) == 2
    assert {r["corpus_uid"] for r in one["candidates"]} == {"mfl:1", "mfl:2"}
    with sqlite3.connect(rlsm) as conn:
        assert conn.execute("SELECT COUNT(*) FROM screenshots").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM source_manifestations").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM ocr_observations").fetchone()[0] == 1
    with sqlite3.connect(corpus) as conn:
        assert conn.execute("SELECT COUNT(*) FROM flight_corpus_records").fetchone()[0] == 2
