"""Bounded regression gates for the screenshot-to-MFL staging seam."""
from __future__ import annotations

import hashlib
import io
import sqlite3
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from skywatcher.fr24.screenshot_jobs import ScreenshotJobs, validate_settings
from skywatcher.fr24.screenshot_rlsm_adapter import provisional_fields


def fake_extractor(path, sha, root, rlsm_db, corpus_db, *, filename_raw=None, reprocess_existing=False):
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
        "ocr_mode": "local",
        "vision_mode": "off",
        "duplicate_mode": "exact",
        "rendered_track_mode": "off",
        "georeference_mode": "existing_only",
        "reprocess_existing": False,
        "pdf_scale": 1.0,
    }
    with pytest.raises(ValueError, match="not implemented"):
        validate_settings({"vision_mode": "comprehensive"})
    with pytest.raises(ValueError, match="unsupported"):
        validate_settings({"auto_publish": True})

    assert validate_settings({
        "duplicate_mode": "exact+perceptual_discovery",
        "rendered_track_mode": "local",
        "georeference_mode": "off",
    })["duplicate_mode"] == "exact+perceptual_discovery"
    with pytest.raises(ValueError, match="not implemented"):
        validate_settings({"rendered_track_mode": "raw_trajectory"})


def test_perceptual_similarity_preserves_full_candidate_set_as_discovery_only():
    from skywatcher.fr24.screenshot_rlsm_adapter import _perceptual_duplicate_candidates

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE screenshots (
            screenshot_id INTEGER PRIMARY KEY, sha256 TEXT, filename TEXT,
            rel_path TEXT, phash TEXT
        )"""
    )
    conn.executemany(
        "INSERT INTO screenshots VALUES (?,?,?,?,?)",
        [
            (1, "sha-a", "a.png", "a.png", "0000000000000000"),
            (2, "sha-b", "b.png", "b.png", "0000000000000001"),
            (3, "sha-c", "c.png", "c.png", "0000000000000003"),
            (4, "sha-d", "d.png", "d.png", "ffffffffffffffff"),
        ],
    )
    candidates = _perceptual_duplicate_candidates(
        conn, 1, "0000000000000000", threshold=2
    )
    conn.close()

    assert [row["screenshot_id"] for row in candidates] == [2, 3]
    assert [row["hamming_distance"] for row in candidates] == [1, 2]
    assert all(
        row["relationship"] == "PERCEPTUAL_SIMILARITY_DISCOVERY_ONLY"
        and row["certification"] == "CANDIDATE_NOT_IDENTITY"
        for row in candidates
    )


def test_rendered_track_receipt_never_claims_raw_trajectory(monkeypatch, tmp_path):
    from skywatcher.fr24 import screenshot_rlsm_adapter as adapter

    fixture = SimpleNamespace(
        path_shape="loop",
        has_loop=1,
        has_orbit=0,
        has_gap=1,
        track_length_px=123.4,
        bbox=(1, 2, 30, 40),
        component_count=2,
        confidence=0.6,
    )
    monkeypatch.setattr("fr24.track_vectorizer.vectorize_image", lambda _: fixture)
    receipt = adapter._rendered_track_observation(tmp_path / "unused.png")

    assert receipt["status"] == "OBSERVED"
    assert receipt["evidence_type"] == "RENDERED_TRAIL"
    assert receipt["raw_trajectory"] is False
    assert receipt["certification"] == "PROVISIONAL_PIXEL_OBSERVATION"


def test_persisted_georeference_is_consumed_without_synthesis():
    from skywatcher.fr24.screenshot_rlsm_adapter import _persisted_georeference_evidence

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE screenshot_georeferences (
            screenshot_id INTEGER, georef_version TEXT, status TEXT, method TEXT,
            viewport_profile TEXT, anchor_count INTEGER, scale_m_per_px REAL,
            fit_residual_m REAL, zoom_rung INTEGER, zoom_support INTEGER,
            confidence REAL, estimated_error_m REAL, observed_at TEXT
        )"""
    )
    conn.execute(
        """INSERT INTO screenshot_georeferences VALUES
           (7,'v1','located','multi_anchor_affine','portrait',3,4.2,11.0,NULL,NULL,
            0.91,48.0,'2026-09-30T12:00:00Z')"""
    )
    evidence = _persisted_georeference_evidence(conn, 7)
    conn.close()

    assert len(evidence) == 1
    assert evidence[0]["status"] == "located"
    assert evidence[0]["certification"] == "PROVISIONAL_SUPPORTED_GEOREFERENCE"


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
    assert accepted["status"] == "COMPLETE"  # review completion does not certify identity


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
    refreshed = adapter.extract_into_rlsm(second, sha, tmp_path, rlsm, corpus,
                                          filename_raw="IMG B.png", reprocess_existing=True)
    assert refreshed["was_reused"] is True
    assert len(observed) == 2
    assert one["status"] == two["status"] == "NEEDS_REVIEW"
    assert two["was_reused"] is True
    assert len(one["candidates"]) == len(two["candidates"]) == 2
    assert {r["corpus_uid"] for r in one["candidates"]} == {"mfl:1", "mfl:2"}
    with sqlite3.connect(rlsm) as conn:
        assert conn.execute("SELECT COUNT(*) FROM screenshots").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM source_manifestations").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM ocr_observations").fetchone()[0] == 2
    with sqlite3.connect(corpus) as conn:
        assert conn.execute("SELECT COUNT(*) FROM flight_corpus_records").fetchone()[0] == 2

def test_preview_hash_and_runtime_boundary(tmp_path):
    import base64

    service = ScreenshotJobs(tmp_path, extractor=fake_extractor)
    run = service.create([("source.png", b"pixel-fixture")])
    item = service.detail(run["job_id"], include_items=True)["items"][0]
    receipt = service.preview(run["job_id"], item["item_id"])
    assert base64.b64decode(receipt["data_base64"]) == b"pixel-fixture"
    assert receipt["sha256"] == item["sha256"]
    with service._connect() as conn:
        saved = Path(conn.execute("SELECT saved_path FROM items WHERE item_id=?",
                                  (item["item_id"],)).fetchone()[0])
    saved.write_bytes(b"altered-bytes")
    with pytest.raises(ValueError, match="hash"):
        service.preview(run["job_id"], item["item_id"])


def test_pdf_preprocessing_changes_only_derived_render_identity(tmp_path):
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    doc.new_page(width=120, height=80)
    payload = doc.tobytes()
    doc.close()
    service = ScreenshotJobs(tmp_path, extractor=fake_extractor)
    standard = service.create([("page.pdf", payload)], {"pdf_scale": 1.0})
    enhanced = service.create([("page.pdf", payload)], {"pdf_scale": 1.5})
    s = service.detail(standard["job_id"], include_items=True)
    e = service.detail(enhanced["job_id"], include_items=True)
    assert s["sources"][0]["sha256"] == e["sources"][0]["sha256"]
    assert s["items"][0]["sha256"] != e["items"][0]["sha256"]
    assert s["items"][0]["page_number"] == e["items"][0]["page_number"] == 1


def test_empty_zip_is_not_reported_as_zero_work(tmp_path):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w"):
        pass
    service = ScreenshotJobs(tmp_path, extractor=fake_extractor)
    run = service.create([("empty.zip", stream.getvalue())])
    detail = service.detail(run["job_id"], include_items=True)
    assert detail["total"] == detail["complete"] == 1
    assert detail["counts"] == {"BLOCKED": 1}
    assert detail["items"][0]["error"] == "empty ZIP archive"

def test_expanded_batch_budget_is_atomic(tmp_path, monkeypatch):
    from skywatcher.fr24 import screenshot_jobs as module

    monkeypatch.setattr(module, "MAX_EXPANDED_BYTES", 8)
    service = ScreenshotJobs(tmp_path, extractor=fake_extractor)
    with pytest.raises(ValueError, match="expanded batch"):
        service.create([("one.png", b"12345"), ("two.png", b"67890")])
    assert service.list_jobs() == []
    assert list(service.work.glob("*/source-*.bin")) == []


def test_zip_member_stream_read_is_bounded_and_preserves_blocker(monkeypatch):
    from skywatcher.fr24 import screenshot_jobs as module

    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("long.png", b"12345")
        archive.writestr("safe.png", b"12")
    monkeypatch.setattr(module, "MAX_SOURCE_BYTES", 4)
    expanded = list(module._expand_payload(archive_bytes.getvalue(), "packet.zip"))
    assert len(expanded) == 2
    assert expanded[0][4] == "member exceeds size limit"
    assert expanded[1][3] == b"12"
    assert expanded[1][4] is None


def test_pdf_budget_preserves_remaining_page_denominator(monkeypatch):
    fitz = pytest.importorskip("fitz")
    from skywatcher.fr24 import screenshot_jobs as module

    doc = fitz.open()
    doc.new_page(width=200, height=200)
    doc.new_page(width=200, height=200)
    content = doc.tobytes()
    doc.close()
    monkeypatch.setattr(module, "MAX_EXPANDED_BYTES", 1)
    page_items = list(module._expand_payload(content, "multipage.pdf"))
    assert len(page_items) == 2
    assert [entry[2] for entry in page_items] == [1, 2]
    assert page_items[0][4] == "expanded PDF budget exceeded"
    assert page_items[1][4] == "PDF render budget exhausted"

def test_explicit_source_flight_id_is_provisional_and_not_created_as_flight():
    from skywatcher.fr24.screenshot_mfl_projection import MFL_FIELDS, project_screenshot_fields

    fields, conflicts = provisional_fields([{
        "obs_id": 7, "zone": "aircraft_card",
        "raw_text": "ABC123 FLIGHT ID 3bf72561 2000 ft",
        "confidence_mean": 94, "ocr_status": "ok",
    }])
    assert not conflicts
    assert fields["source_flight_id_displayed"]["value"] == "3bf72561"
    proposal = project_screenshot_fields(
        fields, conflicts, [], screenshot_sha256="a" * 64
    )
    assert proposal["proposed_fields"]["sourceFlightIdRaw"]["value_raw"] == "3bf72561"
    assert proposal["proposed_fields"]["callsignRaw"]["value_raw"] == "ABC123"
    assert proposal["canonical_append_authorized"] is False
    assert proposal["certification"] == "NONCANONICAL"
    assert "metrics.maxAltitudeFt" in proposal["withheld_fields"]
    assert "startTimeUtc" in proposal["withheld_fields"]
    assert proposal["proposed_count"] + proposal["withheld_count"] == len(MFL_FIELDS)


def test_conflicting_explicit_flight_ids_withhold_id():
    from skywatcher.fr24.screenshot_mfl_projection import project_screenshot_fields

    fields, conflicts = provisional_fields([
        {"obs_id": 1, "zone": "aircraft_card", "raw_text": "ABC123 FLIGHT ID 3bf72561",
         "confidence_mean": 91, "ocr_status": "ok"},
        {"obs_id": 2, "zone": "top_bar", "raw_text": "FR24 ID 40998654",
         "confidence_mean": 93, "ocr_status": "ok"},
    ])
    assert "source_flight_id_displayed" not in fields
    assert any(c.get("field") == "source_flight_id_displayed" for c in conflicts)
    proposal = project_screenshot_fields(
        fields, conflicts, [], screenshot_sha256="b" * 64
    )
    assert "sourceFlightIdRaw" in proposal["withheld_fields"]
    assert proposal["canonical_append_authorized"] is False
