"""Registration watchlist alerts: 'seen' + 'expected but missing' + dedup."""

import sqlite3
from datetime import datetime
from pathlib import Path

from server.ingestion.registration_alerts import generate_alerts, load_watchlist

SCHEMA = Path(__file__).resolve().parents[1] / "server" / "database" / "schema_sqlite.sql"


def _fresh_db(tmp_path) -> sqlite3.Connection:
    conn = sqlite3.connect(tmp_path / "priis.db")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA.read_text())
    return conn


def _add_event(conn, event_id, at, registration):
    conn.execute(
        "INSERT INTO events (id, kind, at, label, registration) VALUES (?,?,?,?,?)",
        (event_id, "flight", at, registration, registration),
    )
    conn.commit()


def test_seen_and_missing_alerts(tmp_path):
    conn = _fresh_db(tmp_path)
    _add_event(conn, "e1", "2026-05-30T09:00:00", "N5854Z")  # recently seen

    watchlist = [
        {"registration": "N5854Z", "label": "PREPA", "expected_within_days": None},
        {"registration": "N767PD", "label": "FURA", "expected_within_days": 7},  # never seen
    ]
    now = datetime(2026, 6, 1, 12, 0, 0)
    summary = generate_alerts(conn, watchlist, now=now, notify=False)

    assert summary["seen_matches"] == 1
    assert summary["missing_matches"] == 1
    assert summary["new_alerts"] == 2

    kinds = {r["id"]: r["registration"] for r in conn.execute(
        "SELECT id, registration FROM alerts WHERE kind='aircraft'").fetchall()}
    assert "REG-SEEN-N5854Z-2026-06-01" in kinds
    assert "REG-MISS-N767PD-2026-06-01" in kinds


def test_alerts_dedupe_same_day(tmp_path):
    conn = _fresh_db(tmp_path)
    _add_event(conn, "e1", "2026-05-30T09:00:00", "N5854Z")
    watchlist = [{"registration": "N5854Z", "expected_within_days": None}]
    now = datetime(2026, 6, 1, 12, 0, 0)

    first = generate_alerts(conn, watchlist, now=now, notify=False)
    second = generate_alerts(conn, watchlist, now=now, notify=False)

    assert first["new_alerts"] == 1
    assert second["new_alerts"] == 0  # deterministic id dedupes
    assert conn.execute("SELECT COUNT(*) FROM alerts WHERE kind='aircraft'").fetchone()[0] == 1


def test_recent_sighting_suppresses_missing(tmp_path):
    conn = _fresh_db(tmp_path)
    _add_event(conn, "e1", "2026-05-31T09:00:00", "N767PD")  # 1 day ago
    watchlist = [{"registration": "N767PD", "expected_within_days": 7}]
    now = datetime(2026, 6, 1, 12, 0, 0)

    summary = generate_alerts(conn, watchlist, now=now, notify=False)
    assert summary["missing_matches"] == 0
    assert summary["seen_matches"] == 1


def test_load_watchlist_reads_seed_config(tmp_path):
    import pytest
    pytest.importorskip("yaml")  # load_watchlist parses YAML; skip if PyYAML absent
    cfg = tmp_path / "wl.yaml"
    cfg.write_text(
        "registrations:\n"
        "  - registration: N5854Z\n"
        "    expected_within_days: 14\n"
        "  - N767PD\n"
    )
    entries = load_watchlist(cfg)
    regs = {e["registration"]: e["expected_within_days"] for e in entries}
    assert regs["N5854Z"] == 14
    assert "N767PD" in regs
