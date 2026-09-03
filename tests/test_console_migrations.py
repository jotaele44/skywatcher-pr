import json
import sqlite3

import pytest

from server.backend.console.migrations import (
    LATEST_VERSION,
    PHASE1_TABLES,
    applied_versions,
    migrate,
    migration_ledger,
    rollback,
)


def table_names(conn):
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_migration_apply_rollback_reapply():
    conn = sqlite3.connect(":memory:")
    ledger = migrate(conn)
    assert applied_versions(conn) == list(range(1, LATEST_VERSION + 1))
    assert set(PHASE1_TABLES).issubset(table_names(conn))
    checksum = ledger[0]["checksum"]

    assert rollback(conn, target_version=0) == []
    assert not set(PHASE1_TABLES).intersection(table_names(conn))

    reapplied = migrate(conn)
    assert reapplied[0]["checksum"] == checksum


def test_rollback_refuses_populated_tables_without_explicit_data_loss():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    provenance = json.dumps({
        "source_family": "synthetic_test",
        "source_provider": "fixture",
        "source_method": "adsb",
        "data_rights": "synthetic",
        "operational_mode": "batch",
        "source_record_id": "src-1",
        "lineage_id": "lin-1"
    })
    conn.execute(
        """
        INSERT INTO console_aircraft_states(
            state_id, aircraft_id, observed_at_utc, lat, lon, on_ground,
            position_status, source_family, source_provider, source_method,
            data_rights, operational_mode, source_record_id, lineage_id,
            provenance_json, synthetic
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "state-1", "aircraft-1", "2026-07-20T16:00:00Z", 18.4, -66.0, 0,
            "measured", "synthetic_test", "fixture", "adsb", "synthetic",
            "batch", "src-1", "lin-1", provenance, 1,
        ),
    )
    conn.commit()

    with pytest.raises(RuntimeError, match="discard console data"):
        rollback(conn, target_version=0)
    assert migration_ledger(conn)

    assert rollback(conn, target_version=0, allow_data_loss=True) == []
