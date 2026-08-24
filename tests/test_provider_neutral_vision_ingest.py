from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from skywatcher.ai_imagery.vision_result_ingest import ENGINE, ingest_extractions


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE screenshots (
            screenshot_id INTEGER PRIMARY KEY,
            sha256 TEXT UNIQUE NOT NULL
        );
        CREATE TABLE ocr_observations (
            obs_id INTEGER PRIMARY KEY AUTOINCREMENT,
            screenshot_id INTEGER NOT NULL REFERENCES screenshots(screenshot_id),
            zone TEXT NOT NULL,
            raw_text TEXT NOT NULL,
            raw_lines_json TEXT,
            engine TEXT NOT NULL,
            engine_version TEXT,
            ocr_status TEXT NOT NULL,
            observed_at TEXT NOT NULL
        );
        CREATE TABLE aircraft_observations (
            aircraft_obs_id INTEGER PRIMARY KEY AUTOINCREMENT,
            screenshot_id INTEGER NOT NULL REFERENCES screenshots(screenshot_id),
            registration TEXT,
            callsign TEXT,
            aircraft_type TEXT,
            altitude_ft INTEGER,
            speed_kt INTEGER,
            heading_deg INTEGER,
            operator_text TEXT,
            identity_status TEXT,
            source_zone TEXT,
            raw_excerpt TEXT,
            observed_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX ix_air_dedup
          ON aircraft_observations(screenshot_id, registration, source_zone)
          WHERE registration IS NOT NULL AND TRIM(registration) != '';
        INSERT INTO screenshots (screenshot_id, sha256)
        VALUES (1, 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa');
        """
    )
    return conn


def _record() -> dict:
    return {
        "schema_version": "aviation_vision_extraction.v1",
        "extraction_id": "extract-1",
        "source_artifact_id": "sha256:" + "a" * 64,
        "model_run_receipt_id": "run-1",
        "extraction_schema_version": "aviation-fields.v1",
        "fields": [
            {
                "field_name": "registration",
                "value": "N999ZY",
                "provenance_id": "prov-reg",
                "validation_outcome": "VALID",
            },
            {
                "field_name": "callsign",
                "value": "TEST1",
                "provenance_id": "prov-call",
                "validation_outcome": "UNVERIFIED",
            },
            {
                "field_name": "altitude",
                "value": 4500,
                "provenance_id": "prov-alt",
                "validation_outcome": "VALID",
            },
        ],
        "review_status": "NEEDS_REVIEW",
        "reviewer_id": None,
        "provisional": True,
        "supersedes_extraction_id": None,
    }


def test_ingest_is_provider_neutral_append_only_and_idempotent() -> None:
    conn = _connection()
    first = ingest_extractions(conn, [_record()], observed_at="2026-07-30T15:00:00Z")
    second = ingest_extractions(conn, [_record()], observed_at="2026-07-30T15:00:00Z")
    assert first["inserted"] == 1
    assert first["aircraft_rows_inserted"] == 1
    assert second["skipped_existing"] == 1
    row = conn.execute("SELECT engine, raw_lines_json FROM ocr_observations").fetchone()
    assert row[0] == ENGINE
    payload = json.loads(row[1])
    assert payload["model_run_receipt_id"] == "run-1"
    assert conn.execute("SELECT COUNT(*) FROM ocr_observations").fetchone()[0] == 1


def test_field_level_provenance_is_linked_without_relabeling() -> None:
    conn = _connection()
    ingest_extractions(conn, [_record()], observed_at="2026-07-30T15:00:00Z")
    rows = conn.execute(
        "SELECT field_name, provenance_id, validation_outcome, model_run_receipt_id"
        " FROM vision_field_provenance ORDER BY field_name"
    ).fetchall()
    assert rows == [
        ("altitude", "prov-alt", "VALID", "run-1"),
        ("callsign", "prov-call", "UNVERIFIED", "run-1"),
        ("registration", "prov-reg", "VALID", "run-1"),
    ]
    excerpt = conn.execute("SELECT raw_excerpt FROM aircraft_observations").fetchone()[0]
    assert json.loads(excerpt)["fields"][0]["provenance_id"] == "prov-reg"
    assert "ocr" not in ENGINE


def test_dry_run_and_unmatched_inputs_do_not_write() -> None:
    conn = _connection()
    dry = ingest_extractions(
        conn, [_record()], observed_at="2026-07-30T15:00:00Z", dry_run=True
    )
    assert dry["inserted"] == 1
    assert conn.execute("SELECT COUNT(*) FROM ocr_observations").fetchone()[0] == 0
    unmatched = _record()
    unmatched["extraction_id"] = "extract-2"
    unmatched["source_artifact_id"] = "sha256:" + "b" * 64
    result = ingest_extractions(conn, [unmatched], observed_at="2026-07-30T15:00:00Z")
    assert result["unmatched"] == 1
    assert result["failures"][0]["reason"] == "source_artifact_not_matched"


def test_ingest_source_contains_no_provider_or_network_runtime() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "skywatcher"
        / "ai_imagery"
        / "vision_result_ingest.py"
    ).read_text().lower()
    for forbidden in (
        "import requests",
        "import urllib",
        "import socket",
        "anthropic",
        "openai",
        "claude",
    ):
        assert forbidden not in source
