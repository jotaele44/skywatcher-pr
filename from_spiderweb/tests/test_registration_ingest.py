"""Registration persistence + backfill through the FR24 server ingest."""

import csv
import sqlite3
from pathlib import Path

from server.ingestion.ingest_data import ingest_fr24_csv
from server.ingestion.migrations import ensure_events_aircraft_columns, run_all

SCHEMA = Path(__file__).resolve().parents[1] / "server" / "database" / "schema_sqlite.sql"


def _fresh_db(tmp_path) -> sqlite3.Connection:
    conn = sqlite3.connect(tmp_path / "priis.db")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA.read_text())
    return conn


def _write_csv(path: Path, rows):
    fields = ["id", "at", "callsign", "registration", "aircraft_type", "operator",
              "origin_code", "destination_code", "altitude_ft", "ground_speed_mph",
              "flight_status", "image_path"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def test_registration_persisted_on_ingest(tmp_path):
    conn = _fresh_db(tmp_path)
    csv_path = tmp_path / "fr24.csv"
    _write_csv(csv_path, [
        {"id": "fr24-1", "at": "2026-03-24T09:40:01", "callsign": "N5854Z",
         "registration": "N5854Z", "aircraft_type": "Airbus H125",
         "operator": "PREPA", "altitude_ft": "500", "ground_speed_mph": "60"},
    ])

    n = ingest_fr24_csv(conn, csv_path)
    assert n == 1

    row = conn.execute(
        "SELECT registration, aircraft_type, operator, altitude_ft FROM events WHERE id='fr24-1'"
    ).fetchone()
    assert row["registration"] == "N5854Z"
    assert row["aircraft_type"] == "Airbus H125"
    assert row["operator"] == "PREPA"
    assert row["altitude_ft"] == 500


def test_reingest_backfills_registration(tmp_path):
    conn = _fresh_db(tmp_path)
    csv_path = tmp_path / "fr24.csv"

    # First ingest with a blank registration (simulates the old dropped state).
    _write_csv(csv_path, [{"id": "fr24-7", "at": "2026-03-24T10:00:00",
                           "callsign": "N767PD", "registration": ""}])
    ingest_fr24_csv(conn, csv_path)
    assert conn.execute("SELECT registration FROM events WHERE id='fr24-7'").fetchone()[0] == ""

    # Re-ingest the same id with the recovered registration → backfilled.
    _write_csv(csv_path, [{"id": "fr24-7", "at": "2026-03-24T10:00:00",
                           "callsign": "N767PD", "registration": "N767PD"}])
    ingest_fr24_csv(conn, csv_path)
    assert conn.execute("SELECT registration FROM events WHERE id='fr24-7'").fetchone()[0] == "N767PD"
    # No duplicate row created.
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1


def test_migration_idempotent_on_legacy_events(tmp_path):
    # Build a legacy events table without the aircraft columns.
    conn = sqlite3.connect(tmp_path / "legacy.db")
    conn.execute(
        "CREATE TABLE events (id TEXT PRIMARY KEY, kind TEXT, at TEXT, "
        "site_id TEXT, ref_id TEXT, label TEXT, tier TEXT)"
    )
    conn.commit()

    first = ensure_events_aircraft_columns(conn)
    assert first["registration"] is True  # added on first call

    second = ensure_events_aircraft_columns(conn)
    assert all(v is False for v in second.values())  # already present

    # run_all wires it in and is also safe to repeat.
    run_all(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(events)").fetchall()}
    assert {"registration", "callsign", "aircraft_type", "image_path"} <= cols
