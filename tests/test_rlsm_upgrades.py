"""Theme 8 — RLSM pipeline upgrade tests (T8-70 OCR-failure JSONL, T8-71 drift)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCHEMA = REPO / "data" / "rlsm" / "schema.sql"


def _make_rlsm_db(path: Path) -> None:
    """Build a tiny RLSM DB from the canonical schema with a few rows."""
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA.read_text())
    now = "2026-06-09T00:00:00Z"
    # Three screenshots: ok, failed, failed.
    conn.executemany(
        """INSERT INTO screenshots
           (sha256, filename, rel_path, month_bucket, filename_ts, ext,
            size_bytes, ingest_status, ocr_status, ingested_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'ok', ?, ?)""",
        [
            ("sha_ok", "ok.png", "2026-06/ok.png", "2026-06", now, ".png", 100, "ok", now),
            ("sha_f1", "f1.png", "2026-06/f1.png", "2026-06", now, ".png", 100, "failed", now),
            ("sha_f2", "f2.png", "2026-06/f2.png", "2026-06", now, ".png", 100, "failed", now),
        ],
    )
    # OCR observations across two zones and two engines, mixed status.
    conn.executemany(
        """INSERT INTO ocr_observations
           (screenshot_id, zone, raw_text, confidence_mean, engine, ocr_status, observed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [
            (1, "top_bar", "N123", 90.0, "tesseract", "ok", now),
            (1, "map_center", "", 0.0, "tesseract", "empty", now),
            (1, "aircraft_card", "x", 40.0, "easyocr", "ok", now),
            (1, "aircraft_card", "", 0.0, "easyocr", "failed", now),
        ],
    )
    conn.commit()
    conn.close()


# ── T8-70 OCR-failure JSONL ──────────────────────────────────────────────────

def test_ocr_failures_jsonl_written(tmp_path, monkeypatch):
    from fr24 import rlsm_export

    db = tmp_path / "rlsm.sqlite"
    outs = tmp_path / "outputs"
    _make_rlsm_db(db)
    monkeypatch.setattr(rlsm_export, "DB", db)
    monkeypatch.setattr(rlsm_export, "OUTS", outs)

    written = rlsm_export.export_all()
    assert "ocr_failures.jsonl" in written

    lines = (outs / "ocr_failures.jsonl").read_text().splitlines()
    assert len(lines) == 2  # two failed screenshots
    for line in lines:
        obj = json.loads(line)
        assert obj["ocr_status"] == "failed"
        assert {"screenshot_id", "filename", "month_bucket"} <= set(obj)


def test_ocr_failures_jsonl_empty_when_no_failures(tmp_path, monkeypatch):
    from fr24 import rlsm_export

    db = tmp_path / "rlsm.sqlite"
    outs = tmp_path / "outputs"
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA.read_text())
    conn.execute(
        """INSERT INTO screenshots
           (sha256, filename, rel_path, ext, size_bytes, ingest_status, ocr_status, ingested_at)
           VALUES ('s', 'a.png', 'p/a.png', '.png', 1, 'ok', 'ok', '2026-06-09T00:00:00Z')"""
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(rlsm_export, "DB", db)
    monkeypatch.setattr(rlsm_export, "OUTS", outs)

    rlsm_export.export_all()
    assert (outs / "ocr_failures.jsonl").read_text() == ""


# ── T8-71 per-zone / per-engine drift section ────────────────────────────────

def test_coverage_report_has_zone_and_engine_sections(tmp_path):
    from fr24 import rlsm_coverage

    db = tmp_path / "rlsm.sqlite"
    _make_rlsm_db(db)
    conn = sqlite3.connect(db)
    md = rlsm_coverage.build(conn)
    conn.close()

    assert "Per-zone OCR coverage / drift" in md
    assert "Per-engine OCR coverage / drift" in md
    # Both engines from the fixture appear.
    assert "tesseract" in md
    assert "easyocr" in md
    # Zone rows present.
    assert "top_bar" in md and "map_center" in md


def test_coverage_zone_counts_reflect_db(tmp_path):
    from fr24 import rlsm_coverage

    db = tmp_path / "rlsm.sqlite"
    _make_rlsm_db(db)
    conn = sqlite3.connect(db)
    md = rlsm_coverage.build(conn)
    conn.close()

    # aircraft_card zone has 2 obs (1 ok, 1 failed) → a row with "| 2 |".
    line = next(ln for ln in md.splitlines() if ln.startswith("| aircraft_card "))
    assert "| 2 |" in line
