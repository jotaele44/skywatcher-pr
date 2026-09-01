"""Gate: adsb_state_vectors migration + persist_batch write path."""

from __future__ import annotations

from adsb.models import StateVector
from adsb.sink import persist_batch
from skywatcher.fr24 import database as db
from skywatcher.fr24 import database_migrations as migrations


def _state(**overrides) -> StateVector:
    base = dict(
        icao24="a1b2c3",
        callsign="N767PD",
        origin_country="United States",
        time_position=1700000000,
        last_contact=1700000005,
        longitude=-66.4,
        latitude=18.2,
        baro_altitude=1500.0,
        on_ground=False,
        velocity=120.5,
        true_track=270.0,
        vertical_rate=0.0,
        geo_altitude=1520.0,
        squawk="1200",
        position_source=0,
    )
    base.update(overrides)
    return StateVector(**base)


def test_migration_0002_creates_table(tmp_path):
    dbp = tmp_path / "s.db"
    result = migrations.initialize_database(dbp)
    assert result.applied == [1, 2]
    conn = db.connect(dbp, readonly=True)
    try:
        assert "adsb_state_vectors" in db.list_tables(conn)
    finally:
        conn.close()


def test_persist_batch_writes_rows_and_batch_record(tmp_path):
    dbp = tmp_path / "s.db"
    result = persist_batch([_state(), _state(icao24="d4e5f6", callsign=None)], db_path=dbp)

    assert result["persisted"] is True
    assert result["n_written"] == 2
    assert result["errors"] == []

    conn = db.connect(dbp, readonly=True)
    try:
        rows = conn.execute("SELECT icao24, callsign, batch_id FROM adsb_state_vectors").fetchall()
        assert {r["icao24"] for r in rows} == {"a1b2c3", "d4e5f6"}
        assert all(r["batch_id"] == result["batch_id"] for r in rows)

        batch = conn.execute(
            "SELECT batch_kind, status, n_processed FROM ingestion_batches WHERE batch_id=?",
            (result["batch_id"],),
        ).fetchone()
        assert batch["batch_kind"] == "adsb_poll"
        assert batch["status"] == "completed"
        assert batch["n_processed"] == 2
    finally:
        conn.close()


def test_persist_batch_is_idempotent_on_migrations(tmp_path):
    dbp = tmp_path / "s.db"
    persist_batch([_state()], db_path=dbp)
    result = persist_batch([_state(icao24="d4e5f6")], db_path=dbp)
    assert result["persisted"] is True

    conn = db.connect(dbp, readonly=True)
    try:
        n = conn.execute("SELECT COUNT(*) AS n FROM adsb_state_vectors").fetchone()["n"]
        assert n == 2
    finally:
        conn.close()


def test_persist_batch_empty_list(tmp_path):
    dbp = tmp_path / "s.db"
    result = persist_batch([], db_path=dbp)
    assert result["persisted"] is True
    assert result["n_written"] == 0
