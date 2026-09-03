from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from skywatcher.replay.foundation import (
    QueryBounds,
    ReplayQueryError,
    build_replay_receipt,
    canonical_json_sha256,
    open_read_only_sqlite,
    replay_enabled,
    stable_object_id,
)

BASE = datetime(2026, 7, 31, 20, 0, tzinfo=timezone.utc)
SHA = "e171e81fb1ef8419386aa2b7e85c9a0e546c5ec8"


def test_feature_flag_defaults_disabled() -> None:
    assert replay_enabled({}) is False
    assert replay_enabled({"SKYWATCHER_OPENMCT_REPLAY_ENABLED": "true"}) is True


def test_stable_object_id_is_deterministic() -> None:
    assert stable_object_id("RLSM Frame", "12983") == "skywatcher:rlsm-frame:12983"
    assert stable_object_id("RLSM Frame", "12983") == stable_object_id("rlsm frame", "12983")


def test_query_bounds_fail_closed() -> None:
    with pytest.raises(ReplayQueryError):
        QueryBounds(BASE, BASE, 1).validate()
    with pytest.raises(ReplayQueryError):
        QueryBounds(BASE, BASE + timedelta(days=8), 1).validate()
    with pytest.raises(ReplayQueryError):
        QueryBounds(BASE, BASE + timedelta(minutes=1), 0).validate()


def test_receipt_is_deterministic_and_stream_order_independent() -> None:
    bounds = QueryBounds(BASE, BASE + timedelta(hours=1))
    kwargs = {
        "session_id": "replay:fixture-1",
        "created_at_utc": BASE,
        "skywatcher_git_sha": SHA,
        "bounds": bounds,
        "accounting_complete": True,
    }
    first = build_replay_receipt(selected_streams=["b", "a", "a"], **kwargs)
    second = build_replay_receipt(selected_streams=["a", "b"], **kwargs)
    assert first == second
    digest = first.pop("receipt_sha256")
    assert digest == canonical_json_sha256(first)


def test_sqlite_connection_is_read_only(tmp_path) -> None:
    path = tmp_path / "canonical.sqlite"
    with sqlite3.connect(path) as writable:
        writable.execute("CREATE TABLE evidence(id INTEGER PRIMARY KEY, value TEXT)")
        writable.execute("INSERT INTO evidence(value) VALUES ('preserved')")

    connection = open_read_only_sqlite(path)
    try:
        assert connection.execute("SELECT value FROM evidence").fetchone() == ("preserved",)
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("INSERT INTO evidence(value) VALUES ('forbidden')")
    finally:
        connection.close()
