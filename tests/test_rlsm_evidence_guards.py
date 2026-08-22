from __future__ import annotations

import sqlite3
from pathlib import Path

from PIL import Image

from fr24 import rlsm_corpus_ingest as corpus


def test_ocr_aircraft_run_cannot_leave_identity_confirmed(tmp_path: Path) -> None:
    baseline = tmp_path / "data" / "FR24_baseline"
    archives = tmp_path / "data" / "FR24_archives"
    database = tmp_path / "data" / "rlsm" / "test.sqlite"
    output = tmp_path / "outputs" / "rlsm_corpus"
    baseline.mkdir(parents=True)
    archives.mkdir(parents=True)
    Image.new("RGB", (20, 20), (30, 40, 50)).save(baseline / "capture.png")

    corpus.run(
        db_path=database,
        repo_root=tmp_path,
        baseline=baseline,
        archive_roots=[archives],
        output_dir=output,
    )

    conn = sqlite3.connect(database)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        screenshot_id = conn.execute(
            "SELECT screenshot_id FROM screenshots"
        ).fetchone()[0]
        run_id = conn.execute(
            """INSERT INTO processing_runs(run_kind, started_at, status)
               VALUES ('aircraft', '2026-08-22T00:00:00Z', 'in_progress')"""
        ).lastrowid
        observation_id = conn.execute(
            """INSERT INTO aircraft_observations
               (screenshot_id, run_id, registration, aircraft_type,
                identity_status, confidence, source_zone, raw_excerpt, observed_at)
               VALUES (?, ?, 'N407PR', 'B06', 'confirmed', 0.95,
                       'aircraft_card', 'N407PR B06', '2026-08-22T00:00:00Z')""",
            (screenshot_id, run_id),
        ).lastrowid

        state = conn.execute(
            """SELECT identity_status, confidence
               FROM aircraft_observations WHERE aircraft_obs_id=?""",
            (observation_id,),
        ).fetchone()
        assert state == ("partial", 0.75)
        audit = conn.execute(
            """SELECT old_status, new_status, reason_code
               FROM aircraft_identity_transition_audit WHERE aircraft_obs_id=?""",
            (observation_id,),
        ).fetchone()
        assert audit == ("confirmed", "partial", "OCR_ONLY_NOT_IDENTITY")
    finally:
        conn.close()
