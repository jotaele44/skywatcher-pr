"""Reconciliation: ingest gaps + true misses are reported and queued."""

import csv
import sqlite3
from pathlib import Path

from server.ingestion.ingest_data import ingest_fr24_csv
from server.ingestion.reconcile_registrations import reconcile

SCHEMA = Path(__file__).resolve().parents[1] / "server" / "database" / "schema_sqlite.sql"


def _fresh_db(tmp_path) -> sqlite3.Connection:
    conn = sqlite3.connect(tmp_path / "priis.db")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA.read_text())
    return conn


def _write_csv(path: Path, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "at", "registration", "image_path"])
        w.writeheader()
        w.writerows(rows)


def test_reconcile_reports_gaps_and_misses(tmp_path):
    conn = _fresh_db(tmp_path)

    # DB already has N111AA (ingested).
    db_csv = tmp_path / "db.csv"
    _write_csv(db_csv, [{"id": "fr24-1", "at": "2026-05-30T09:00:00",
                         "registration": "N111AA", "image_path": "/img/1.heic"}])
    ingest_fr24_csv(conn, db_csv)

    # FR24 export CSV has N111AA (already in DB) and N222BB (ingest gap).
    source_csv = tmp_path / "fr24.csv"
    _write_csv(source_csv, [
        {"id": "fr24-1", "at": "2026-05-30T09:00:00", "registration": "N111AA", "image_path": "/img/1.heic"},
        {"id": "fr24-2", "at": "2026-05-30T10:00:00", "registration": "N222BB", "image_path": "/img/2.heic"},
    ])

    # Known list: one in DB, the gap, and a true miss (N333CC, nowhere).
    known = tmp_path / "known.txt"
    known.write_text("N111AA\nN222BB\nN333CC\n")

    queue = tmp_path / "recovery.csv"
    summary = reconcile(conn, source_csv, known, queue)

    assert summary["ingest_gaps"] == 1   # N222BB
    assert summary["true_misses"] == 1   # N333CC
    assert summary["new_alerts"] == 1

    rows = list(csv.DictReader(queue.open()))
    cats = {r["registration_normalized"]: r["category"] for r in rows}
    assert cats["N222BB"] == "ingest_gap"
    assert cats["N333CC"] == "known_miss"

    # The true miss raised an aircraft alert.
    alert_regs = [r[0] for r in conn.execute(
        "SELECT registration FROM alerts WHERE kind='aircraft'").fetchall()]
    assert "N333CC" in alert_regs


def test_reconcile_matches_ignore_formatting(tmp_path):
    conn = _fresh_db(tmp_path)
    db_csv = tmp_path / "db.csv"
    _write_csv(db_csv, [{"id": "fr24-1", "at": "2026-05-30T09:00:00",
                         "registration": "N111AA", "image_path": ""}])
    ingest_fr24_csv(conn, db_csv)

    source_csv = tmp_path / "fr24.csv"
    _write_csv(source_csv, [{"id": "fr24-1", "at": "2026-05-30T09:00:00",
                             "registration": "N111AA", "image_path": ""}])

    # Known list uses dashes/lowercase/spaces — must still match.
    known = tmp_path / "known.txt"
    known.write_text("n-111 aa\n")

    queue = tmp_path / "recovery.csv"
    summary = reconcile(conn, source_csv, known, queue, raise_alerts=False)
    assert summary["true_misses"] == 0  # normalized match, not a miss
