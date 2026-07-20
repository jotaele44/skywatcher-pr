"""Gate: idempotent, deterministic, migration-aware, validation-only DB init."""

from __future__ import annotations

from skywatcher.fr24 import database as db
from skywatcher.fr24 import database_migrations as migrations


def test_initialization_is_idempotent(tmp_path):
    dbp = tmp_path / "s.db"
    r1 = migrations.initialize_database(dbp)
    r2 = migrations.initialize_database(dbp)
    assert r1.applied == [1]
    assert r2.applied == []  # nothing re-applied
    assert r1.schema_version == r2.schema_version == migrations.LATEST_VERSION


def test_migration_order_is_deterministic():
    versions = [m.version for m in migrations.MIGRATIONS]
    assert versions == sorted(versions)
    assert versions[0] == 1
    assert migrations.LATEST_VERSION == versions[-1]


def test_validate_only_reports_empty_db(tmp_path):
    dbp = tmp_path / "empty.db"
    result = migrations.initialize_database(dbp, validate_only=True)
    assert not result.ok
    assert any("missing table" in p or "no migrations" in p for p in result.problems)


def test_validate_only_passes_after_init(tmp_path):
    dbp = tmp_path / "s.db"
    migrations.initialize_database(dbp)
    result = migrations.initialize_database(dbp, validate_only=True)
    assert result.ok, result.problems
    assert result.applied == []  # validate-only never writes


def test_schema_version_recorded(tmp_path):
    dbp = tmp_path / "s.db"
    migrations.initialize_database(dbp)
    conn = db.connect(dbp)
    try:
        rows = conn.execute("SELECT version, description FROM schema_version ORDER BY version").fetchall()
        assert [r["version"] for r in rows] == [1]
        assert rows[0]["description"]
    finally:
        conn.close()
