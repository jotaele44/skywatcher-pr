"""Gate: canonical flight-corpus migration 0003 and upgrade behavior."""

from __future__ import annotations

import sqlite3

from skywatcher.fr24 import database as db
from skywatcher.fr24 import database_migrations as migrations


CORPUS_TABLES = {
    "flight_corpus_snapshots",
    "flight_corpus_snapshot_sources",
    "flight_corpus_records",
    "flight_source_manifestations",
}


def test_migration_0003_creates_corpus_tables(tmp_path):
    dbp = tmp_path / "s.db"
    result = migrations.initialize_database(dbp)
    assert 3 in result.applied
    assert result.schema_version == migrations.LATEST_VERSION

    conn = db.connect(dbp, readonly=True)
    try:
        assert CORPUS_TABLES.issubset(set(db.list_tables(conn)))
    finally:
        conn.close()


def test_upgrade_from_0002_applies_only_0003(tmp_path):
    dbp = tmp_path / "s.db"

    conn = db.connect(dbp)
    try:
        applied = migrations.apply_migrations(conn, target=2)
        assert applied == [1, 2]
        assert db.get_schema_version(conn) == 2
        assert CORPUS_TABLES.isdisjoint(set(db.list_tables(conn)))
    finally:
        conn.close()

    upgraded = migrations.initialize_database(dbp)
    assert upgraded.applied == [3]
    assert upgraded.schema_version == migrations.LATEST_VERSION

    conn = db.connect(dbp, readonly=True)
    try:
        assert CORPUS_TABLES.issubset(set(db.list_tables(conn)))
    finally:
        conn.close()


def test_corpus_migration_is_idempotent(tmp_path):
    dbp = tmp_path / "s.db"
    first = migrations.initialize_database(dbp)
    second = migrations.initialize_database(dbp)

    assert 3 in first.applied
    assert second.applied == []
    assert second.ok


def test_corpus_record_requires_snapshot_foreign_key(tmp_path):
    dbp = tmp_path / "s.db"
    migrations.initialize_database(dbp)

    conn = db.connect(dbp)
    try:
        try:
            conn.execute(
                """
                INSERT INTO flight_corpus_records (
                    corpus_uid, snapshot_id, raw_record_json, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                ("mfl:test", 999999, "{}", "2026-09-25T00:00:00Z"),
            )
        except sqlite3.IntegrityError as exc:
            assert "FOREIGN KEY" in str(exc).upper()
        else:
            raise AssertionError("orphan corpus record unexpectedly accepted")
    finally:
        conn.close()
