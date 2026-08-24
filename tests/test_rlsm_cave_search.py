from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from fr24.rlsm_cave_search import build_terms, normalize_text, search_corpus

REPO = Path(__file__).resolve().parents[1]
BASELINE = REPO / "data" / "reference" / "caves" / "pr_cave_ocr_baseline_v2.json"
V1_MANIFEST = REPO / "data" / "reference" / "caves" / "pr_cave_v1_regression_manifest.json"


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.executescript(
        """
        CREATE TABLE screenshots(
            screenshot_id INTEGER PRIMARY KEY,
            filename TEXT NOT NULL,
            rel_path TEXT NOT NULL,
            filename_ts TEXT,
            source_availability TEXT
        );
        CREATE TABLE ocr_observations(
            obs_id INTEGER PRIMARY KEY,
            screenshot_id INTEGER NOT NULL,
            zone TEXT NOT NULL,
            raw_text TEXT NOT NULL,
            confidence_mean REAL,
            ocr_status TEXT NOT NULL
        );
        CREATE TABLE labeled_pins(
            pin_id INTEGER PRIMARY KEY,
            screenshot_id INTEGER NOT NULL,
            raw_label TEXT NOT NULL,
            normalized_label TEXT,
            confidence REAL,
            bbox_x INTEGER, bbox_y INTEGER, bbox_w INTEGER, bbox_h INTEGER,
            centroid_x INTEGER, centroid_y INTEGER
        );
        """
    )
    yield c
    c.close()


def _baseline() -> dict:
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def _add_screenshot(c: sqlite3.Connection, sid: int = 1) -> None:
    c.execute(
        "INSERT INTO screenshots VALUES (?,?,?,?,?)",
        (sid, f"{sid}.png", f"data/FR24_baseline/{sid}.png", "2026-01-01T12:00:00", "present"),
    )


def test_v1_regression_snapshot_is_frozen():
    payload = json.loads(V1_MANIFEST.read_text(encoding="utf-8"))
    assert payload["sha256"] == "8cb0ef11b8648651de32b8bf7e506c83e777bede765a4506d4159b0d4294f608"
    assert payload["source_data_rows"] == 37629
    assert payload["record_count"] == 2


def test_cave_baseline_preserves_open_identity_states():
    payload = _baseline()
    by_name = {r["canonical_name"]: r for r in payload["records"]}
    assert by_name["Cueva Las Tosas"]["identity_status"].startswith("OPEN_")
    assert by_name["Cueva Golondrinas"]["identity_status"].startswith("OPEN_")
    assert by_name["Cueva Las Golondrinas"]["identity_status"].startswith("OPEN_")
    assert by_name["Cueva Golondrinas"]["cave_id"] != by_name["Cueva Las Golondrinas"]["cave_id"]


def test_normalization_folds_accents_without_overwriting_raw():
    assert normalize_text("Cueva Ensueño") == "cueva ensueno"


def test_latest_ocr_observation_wins_and_history_is_not_double_counted(conn):
    _add_screenshot(conn)
    conn.execute("INSERT INTO ocr_observations VALUES (1,1,'label_layer','old Cueva Ventana',80,'ok')")
    conn.execute("INSERT INTO ocr_observations VALUES (2,1,'label_layer','Cueva Ventana Arecibo',90,'ok')")
    matches, coverage = search_corpus(conn, terms=build_terms(_baseline()), channels=("ocr",))
    cave = [m for m in matches if m.canonical_name == "Cueva Ventana"]
    assert [m.source_record_id for m in cave] == [2]
    assert coverage["matched_screenshots"] == 1


def test_latest_failed_reocr_blocks_older_success_and_coverage(conn):
    _add_screenshot(conn)
    conn.execute("INSERT INTO ocr_observations VALUES (1,1,'label_layer','Cueva Ventana',90,'ok')")
    conn.execute("INSERT INTO ocr_observations VALUES (2,1,'label_layer','',0,'failed')")
    matches, coverage = search_corpus(conn, terms=build_terms(_baseline()), channels=("ocr",))
    assert not [m for m in matches if m.canonical_name == "Cueva Ventana"]
    assert coverage["screenshots_with_any_ocr"] == 0
    assert coverage["screenshots_with_failed_ocr_observation"] == 1


def test_raw_ocr_and_extracted_label_are_separate_channels(conn):
    _add_screenshot(conn)
    conn.execute("INSERT INTO ocr_observations VALUES (1,1,'label_layer','Cueva Ventana',90,'ok')")
    conn.execute(
        """INSERT INTO labeled_pins
           VALUES (7,1,'Cueva Ventana','Cueva Ventana',0.91,10,20,30,40,25,40)"""
    )
    matches, _ = search_corpus(conn, terms=build_terms(_baseline()))
    cave = [m for m in matches if m.canonical_name == "Cueva Ventana"]
    assert {m.channel for m in cave} == {"RAW_OCR", "EXTRACTED_LABEL"}
    label = next(m for m in cave if m.channel == "EXTRACTED_LABEL")
    assert label.bbox_x == 10 and label.centroid_y == 40


def test_generic_term_is_lexical_evidence_not_identity(conn):
    _add_screenshot(conn)
    conn.execute("INSERT INTO ocr_observations VALUES (1,1,'label_layer','Cueva desconocida',90,'ok')")
    matches, _ = search_corpus(conn, terms=build_terms(_baseline()), channels=("ocr",))
    generic = [m for m in matches if m.match_class == "DIRECT_GENERIC_TERM"]
    assert generic
    assert all(m.cave_id is None and m.canonical_name is None for m in generic)


def test_fuzzy_matching_is_candidate_not_identity(conn):
    _add_screenshot(conn)
    conn.execute("INSERT INTO ocr_observations VALUES (1,1,'label_layer','Cueya Ventana',70,'ok')")
    matches, _ = search_corpus(
        conn,
        terms=build_terms(_baseline()),
        channels=("ocr",),
        fuzzy=True,
        fuzzy_threshold=0.80,
    )
    fuzzy = [m for m in matches if m.match_class == "FUZZY_CANDIDATE"]
    assert fuzzy
    assert all(m.identity_status == "CANDIDATE_NOT_IDENTITY" for m in fuzzy)


def test_distinct_near_names_are_not_deduped(conn):
    _add_screenshot(conn)
    conn.execute(
        "INSERT INTO ocr_observations VALUES "
        "(1,1,'label_layer','Cueva Las Golondrinas Cueva Golondrinas',92,'ok')"
    )
    matches, _ = search_corpus(conn, terms=build_terms(_baseline()), channels=("ocr",))
    ids = {
        m.cave_id
        for m in matches
        if m.canonical_name in {"Cueva Las Golondrinas", "Cueva Golondrinas"}
    }
    assert len(ids) == 2
