"""Gate: database schema creation in a temporary directory (synthetic only)."""

from __future__ import annotations

import sqlite3

import pytest

from skywatcher.fr24 import database as db
from skywatcher.fr24 import database_migrations as migrations


def test_all_expected_tables_created(tmp_path):
    dbp = tmp_path / "s.db"
    result = migrations.initialize_database(dbp)
    assert result.ok, result.problems
    conn = db.connect(dbp)
    try:
        present = set(db.list_tables(conn))
        for table in db.EXPECTED_TABLES:
            assert table in present, f"missing {table}"
    finally:
        conn.close()


def test_foreign_keys_enabled(tmp_path):
    dbp = tmp_path / "s.db"
    migrations.initialize_database(dbp)
    conn = db.connect(dbp)
    try:
        assert db.foreign_keys_enabled(conn)
    finally:
        conn.close()


def test_coordinate_method_check_constraint_rejects_bad_value(tmp_path):
    dbp = tmp_path / "s.db"
    migrations.initialize_database(dbp)
    conn = db.connect(dbp)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO flights (flight_id, created_at, coordinate_method) VALUES (?,?,?)",
                ("F1", "2026-01-01T00:00:00Z", "not_a_method"),
            )
    finally:
        conn.close()


def test_widened_coordinate_method_accepted(tmp_path):
    dbp = tmp_path / "s.db"
    migrations.initialize_database(dbp)
    conn = db.connect(dbp)
    try:
        for method in ("per_screenshot_affine", "synthetic_wgs84_point", "unknown"):
            conn.execute(
                "INSERT INTO flights (flight_id, created_at, coordinate_method) VALUES (?,?,?)",
                (f"F_{method}", "2026-01-01T00:00:00Z", method),
            )
        conn.commit()
        n = conn.execute("SELECT COUNT(*) FROM flights").fetchone()[0]
        assert n == 3
    finally:
        conn.close()
