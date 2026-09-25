"""Gate: transactional persistence for canonical flight-corpus snapshots."""

from __future__ import annotations

import hashlib

import pytest

from skywatcher.fr24 import database as db
from skywatcher.fr24.flight_corpus import CorpusPersistenceError, persist_corpus_snapshot


def _record(uid: str, *, source_name: str = "f1.csv") -> dict:
    return {
        "corpusUid": uid,
        "monthBucket": "2026-09",
        "sourceFlightIdRaw": "deadbeef",
        "callsignRaw": "N1",
        "pointCount": 2,
        "startTimeUtc": "2026-09-24T00:00:00.000Z",
        "endTimeUtc": "2026-09-24T00:01:00.000Z",
        "start": {"lat": 18.1, "lon": -66.1},
        "end": {"lat": 18.2, "lon": -66.2},
        "sourceManifestations": [
            {
                "folderRaw": "N1",
                "filenameRaw": source_name,
                "mtimeRaw": 1790200000,
                "kmlPresent": True,
                "kmlPresentRaw": 1,
                "raw": {"f": "N1", "n": source_name, "m": 1790200000, "k": 1},
            }
        ],
        "metrics": {"maxAltitudeFt": 500},
        "kmlEnrichment": {"metadataTableIndexRaw": 1, "routeRaw": "SIG>SIG"},
        "raw": {"h": uid, "fid": "deadbeef", "cs": "N1", "n": 2},
    }


def test_persist_snapshot_hashes_and_reads_back(tmp_path):
    dbp = tmp_path / "s.db"
    payload = b"<html>snapshot-a</html>"
    result = persist_corpus_snapshot(
        dbp,
        source_bytes=payload,
        source_kind="master_flight_log_html",
        source_filename="Master Flight Log.html",
        format_name="master-flight-log-backup",
        format_version=1,
        records=[_record("mfl:a")],
    )

    assert result.duplicate_snapshot is False
    assert result.source_sha256 == hashlib.sha256(payload).hexdigest()
    assert result.record_count == 1
    assert result.manifestation_count == 1

    conn = db.connect(dbp, readonly=True)
    try:
        snapshot = conn.execute(
            "SELECT status, record_count FROM flight_corpus_snapshots WHERE snapshot_id = ?",
            (result.snapshot_id,),
        ).fetchone()
        assert snapshot["status"] == "validated"
        assert snapshot["record_count"] == 1

        record = conn.execute(
            "SELECT corpus_uid, callsign_raw FROM flight_corpus_records WHERE snapshot_id = ?",
            (result.snapshot_id,),
        ).fetchone()
        assert record["corpus_uid"] == "mfl:a"
        assert record["callsign_raw"] == "N1"
    finally:
        conn.close()


def test_exact_snapshot_reimport_is_idempotent(tmp_path):
    dbp = tmp_path / "s.db"
    payload = b"same bytes"
    kwargs = {
        "source_bytes": payload,
        "source_kind": "master_flight_log_html",
        "format_name": "master-flight-log-backup",
        "records": [_record("mfl:a")],
    }

    first = persist_corpus_snapshot(dbp, **kwargs)
    second = persist_corpus_snapshot(dbp, **kwargs)

    assert first.snapshot_id == second.snapshot_id
    assert second.duplicate_snapshot is True

    conn = db.connect(dbp, readonly=True)
    try:
        assert conn.execute("SELECT COUNT(*) AS n FROM flight_corpus_snapshots").fetchone()["n"] == 1
        assert conn.execute("SELECT COUNT(*) AS n FROM flight_corpus_records").fetchone()["n"] == 1
    finally:
        conn.close()


def test_same_logical_uid_can_exist_in_distinct_snapshots(tmp_path):
    dbp = tmp_path / "s.db"
    first = persist_corpus_snapshot(
        dbp,
        source_bytes=b"snapshot one",
        source_kind="master_flight_log_html",
        format_name="master-flight-log-backup",
        records=[_record("mfl:a")],
    )
    second = persist_corpus_snapshot(
        dbp,
        source_bytes=b"snapshot two",
        source_kind="master_flight_log_html",
        format_name="master-flight-log-backup",
        records=[_record("mfl:a")],
    )

    assert first.snapshot_id != second.snapshot_id

    conn = db.connect(dbp, readonly=True)
    try:
        rows = conn.execute(
            "SELECT snapshot_id, corpus_uid FROM flight_corpus_records ORDER BY snapshot_id"
        ).fetchall()
        assert [(row["snapshot_id"], row["corpus_uid"]) for row in rows] == [
            (first.snapshot_id, "mfl:a"),
            (second.snapshot_id, "mfl:a"),
        ]
    finally:
        conn.close()


def test_invalid_record_rolls_back_entire_snapshot(tmp_path):
    dbp = tmp_path / "s.db"
    invalid = _record("mfl:b")
    invalid.pop("corpusUid")

    with pytest.raises(CorpusPersistenceError, match="missing corpusUid"):
        persist_corpus_snapshot(
            dbp,
            source_bytes=b"rollback me",
            source_kind="master_flight_log_html",
            format_name="master-flight-log-backup",
            records=[_record("mfl:a"), invalid],
        )

    conn = db.connect(dbp, readonly=True)
    try:
        assert conn.execute("SELECT COUNT(*) AS n FROM flight_corpus_snapshots").fetchone()["n"] == 0
        assert conn.execute("SELECT COUNT(*) AS n FROM flight_corpus_records").fetchone()["n"] == 0
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM flight_source_manifestations"
        ).fetchone()["n"] == 0
    finally:
        conn.close()


def test_duplicate_snapshot_detects_corrupt_stored_count(tmp_path):
    dbp = tmp_path / "s.db"
    payload = b"snapshot"
    first = persist_corpus_snapshot(
        dbp,
        source_bytes=payload,
        source_kind="master_flight_log_html",
        format_name="master-flight-log-backup",
        records=[_record("mfl:a")],
    )

    conn = db.connect(dbp)
    try:
        conn.execute(
            "UPDATE flight_corpus_snapshots SET record_count = 99 WHERE snapshot_id = ?",
            (first.snapshot_id,),
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(CorpusPersistenceError, match="stored record_count"):
        persist_corpus_snapshot(
            dbp,
            source_bytes=payload,
            source_kind="master_flight_log_html",
            format_name="master-flight-log-backup",
            records=[_record("mfl:a")],
        )
