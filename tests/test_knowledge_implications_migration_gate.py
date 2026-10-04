"""Adversarial gate: migration 0004 MUST use an explicit DDL transaction.

Standalone sidecar SQL is intentionally NOT in the migration registry.
These tests document the unsafe sqlite3.executescript default and the minimum
atomic-rollback behavior required before any future migration registration.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from skywatcher.fr24 import database as db
from skywatcher.fr24 import database_migrations as migrations

SQL = (Path(__file__).resolve().parents[1] / "schemas" / "knowledge_implications_v1.sql").read_text(encoding="utf-8")
# sqlite PRAGMA foreign_keys must be enabled outside the explicit transaction.
DDL = SQL.replace("PRAGMA foreign_keys = ON;", "", 1)


def _sidecar_objects(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE name LIKE 'swk_%' ORDER BY name"
    )]


def test_explicit_transaction_rolls_back_all_ddl_after_injected_failure():
    db = sqlite3.connect(":memory:")
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("CREATE TABLE unrelated_existing (id INTEGER PRIMARY KEY, value TEXT)")
    db.execute("INSERT INTO unrelated_existing VALUES (1, 'unchanged')")
    db.commit()
    with pytest.raises(sqlite3.OperationalError, match="already exists"):
        db.executescript(
            "BEGIN IMMEDIATE;\n" + DDL
            + "\nCREATE TABLE swk_implication (deliberate_duplicate INTEGER);\n"
            + "COMMIT;"
        )
    db.rollback()
    assert _sidecar_objects(db) == []
    assert db.execute("SELECT * FROM unrelated_existing").fetchall() == [(1, "unchanged")]
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_unwrapped_executescript_is_demonstrably_not_atomic():
    """Negative control: a naive migration leaves orphan DDL after an error.

    Do not register the sidecar migration while this danger remains possible.
    """
    db = sqlite3.connect(":memory:")
    with pytest.raises(sqlite3.OperationalError, match="already exists"):
        db.executescript(DDL + "\nCREATE TABLE swk_implication (deliberate_duplicate INTEGER);")
    db.rollback()
    assert len(_sidecar_objects(db)) > 0

def test_prospective_0004_ledger_receipt_commits_with_sidecar(tmp_path, monkeypatch):
    path = tmp_path / "future-success.db"
    conn = db.connect(path)
    try:
        assert migrations.apply_migrations(conn, target=3) == [1, 2, 3]

        def apply_future(connection: sqlite3.Connection) -> None:
            migrations._begin_atomic_sql_script(connection, SQL)

        future = migrations.Migration(
            4,
            "knowledge implication sidecar prospective fixture",
            apply_future,
            requires_open_transaction=True,
        )
        monkeypatch.setattr(migrations, "MIGRATIONS", [*migrations.MIGRATIONS, future])

        assert migrations.apply_migrations(conn, target=4) == [4]
        assert db.get_schema_version(conn) == 4
        assert len(_sidecar_objects(conn)) > 0
        assert conn.execute(
            "SELECT description FROM schema_version WHERE version=4"
        ).fetchone()[0] == "knowledge implication sidecar prospective fixture"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()


def test_prospective_0004_failure_rolls_back_ddl_and_ledger(tmp_path, monkeypatch):
    path = tmp_path / "future-failure.db"
    conn = db.connect(path)
    try:
        assert migrations.apply_migrations(conn, target=3) == [1, 2, 3]

        def apply_future(connection: sqlite3.Connection) -> None:
            migrations._begin_atomic_sql_script(
                connection,
                SQL
                + "\nCREATE TABLE swk_implication "
                  "(deliberate_duplicate INTEGER);\n",
            )

        future = migrations.Migration(
            4,
            "knowledge implication sidecar deliberate failure",
            apply_future,
            requires_open_transaction=True,
        )
        monkeypatch.setattr(migrations, "MIGRATIONS", [*migrations.MIGRATIONS, future])

        with pytest.raises(migrations.MigrationError, match="migration 4"):
            migrations.apply_migrations(conn, target=4)

        assert db.get_schema_version(conn) == 3
        assert conn.execute(
            "SELECT COUNT(*) FROM schema_version WHERE version=4"
        ).fetchone()[0] == 0
        assert _sidecar_objects(conn) == []
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()


def test_atomic_migration_helper_rejects_embedded_transaction_control():
    conn = sqlite3.connect(":memory:")
    try:
        with pytest.raises(sqlite3.OperationalError, match="transaction-control"):
            migrations._begin_atomic_sql_script(
                conn,
                "BEGIN; CREATE TABLE forbidden(id INTEGER); COMMIT;",
            )
        assert conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='forbidden'"
        ).fetchone()[0] == 0
    finally:
        conn.close()

def test_released_migrations_require_open_transaction():
    assert [migration.version for migration in migrations.MIGRATIONS] == [1, 2, 3]
    assert all(migration.requires_open_transaction for migration in migrations.MIGRATIONS)


def test_released_0001_failure_rolls_back_schema_and_version_receipt(
    tmp_path, monkeypatch
):
    original = db.read_schema_sql()
    monkeypatch.setattr(
        db,
        "read_schema_sql",
        lambda: original
        + "\nCREATE TABLE aircraft(deliberate_duplicate INTEGER);\n",
    )
    path = tmp_path / "released-0001-failure.db"
    conn = db.connect(path)
    try:
        with pytest.raises(migrations.MigrationError, match="migration 1"):
            migrations.apply_migrations(conn, target=1)

        assert db.get_schema_version(conn) == 0
        present = set(db.list_tables(conn))
        assert "schema_version" in present
        assert "aircraft" not in present
        assert "screenshots" not in present
        assert "ingestion_batches" not in present
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()

