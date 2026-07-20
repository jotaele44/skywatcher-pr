import json
import sqlite3

import pytest

from server.backend.console.migrations import PHASE1_TABLES, PHASE2_TABLES, applied_versions, migrate, rollback


def tables(connection):
    return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_migration_v2_can_roll_back_to_v1_without_dropping_v1_tables():
    connection = sqlite3.connect(":memory:")
    migrate(connection, target_version=2)
    assert applied_versions(connection) == [1, 2]
    assert set(PHASE1_TABLES + PHASE2_TABLES).issubset(tables(connection))

    rollback(connection, target_version=1)
    assert applied_versions(connection) == [1]
    assert set(PHASE1_TABLES).issubset(tables(connection))
    assert not set(PHASE2_TABLES).intersection(tables(connection))


def test_migration_v2_populated_rollback_requires_explicit_data_loss():
    connection = sqlite3.connect(":memory:")
    migrate(connection, target_version=2)
    connection.execute(
        """
        INSERT INTO console_source_artifacts(
          artifact_id, repository_name, artifact_kind, artifact_path,
          discovered_at_utc, availability_status, record_count, synthetic,
          provenance_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "artifact-1",
            "track_points",
            "fixture",
            "/tmp/fixture",
            "2026-07-20T16:00:00Z",
            "available",
            1,
            0,
            json.dumps({"fixture": True}),
        ),
    )
    connection.commit()
    with pytest.raises(RuntimeError, match="phase 2 console data"):
        rollback(connection, target_version=1)
    rollback(connection, target_version=1, allow_data_loss=True)
    assert applied_versions(connection) == [1]
