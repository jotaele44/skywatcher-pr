"""Adversarial gate: migration 0004 MUST use an explicit DDL transaction.

Standalone sidecar SQL is intentionally NOT in the migration registry.
These tests document the unsafe sqlite3.executescript default and the minimum
atomic-rollback behavior required before any future migration registration.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

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
