"""Transactional persistence for the Skywatcher canonical flight corpus."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import database as db
from . import database_migrations as migrations

__all__ = [
    "CorpusPersistenceError",
    "PersistResult",
    "persist_corpus_snapshot",
    "read_corpus_snapshot",
]


class CorpusPersistenceError(db.DatabaseError):
    """Raised when a corpus snapshot cannot be persisted without violating invariants."""


@dataclass(frozen=True)
class PersistResult:
    snapshot_id: int
    source_sha256: str
    record_count: int
    manifestation_count: int
    duplicate_snapshot: bool


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _as_number(value: Any) -> float | int | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _endpoint(record: dict[str, Any], key: str) -> tuple[float | None, float | None]:
    value = record.get(key)
    if not isinstance(value, dict):
        return None, None
    lat = _as_number(value.get("lat"))
    lon = _as_number(value.get("lon"))
    return (
        float(lat) if lat is not None else None,
        float(lon) if lon is not None else None,
    )


def _manifestation_kind(item: dict[str, Any]) -> str:
    name = str(item.get("filenameRaw") or "")
    suffix = Path(name).suffix.lower()
    if suffix == ".kml":
        return "kml"
    if suffix == ".csv":
        return "csv"
    return "source_manifestation"


def persist_corpus_snapshot(
    db_path: str | Path,
    *,
    source_bytes: bytes,
    source_kind: str,
    format_name: str,
    records: list[dict[str, Any]],
    source_ref: str | None = None,
    source_filename: str | None = None,
    format_version: str | int | None = None,
    exported_at: str | None = None,
    ingested_at: str | None = None,
) -> PersistResult:
    """Persist one immutable source snapshot and its records atomically.

    Exact byte re-imports are idempotent by SHA-256. A new snapshot may reuse
    logical corpus_uid values; record identity is snapshot-local.
    """
    if not isinstance(source_bytes, bytes):
        raise CorpusPersistenceError("source_bytes must be bytes")
    if not source_kind.strip():
        raise CorpusPersistenceError("source_kind is required")
    if not format_name.strip():
        raise CorpusPersistenceError("format_name is required")
    if not isinstance(records, list):
        raise CorpusPersistenceError("records must be a list")

    migrations.initialize_database(db_path)
    digest = hashlib.sha256(source_bytes).hexdigest()
    when = ingested_at or _utc_now_iso()

    conn = db.connect(db_path)
    try:
        existing = conn.execute(
            """
            SELECT snapshot_id, record_count
            FROM flight_corpus_snapshots
            WHERE source_sha256 = ?
            """,
            (digest,),
        ).fetchone()
        if existing is not None:
            actual = conn.execute(
                "SELECT COUNT(*) AS n FROM flight_corpus_records WHERE snapshot_id = ?",
                (existing["snapshot_id"],),
            ).fetchone()["n"]
            if actual != existing["record_count"]:
                raise CorpusPersistenceError(
                    "duplicate snapshot exists but stored record_count does not match read-back"
                )
            manifestations = conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM flight_source_manifestations m
                JOIN flight_corpus_records r
                  ON r.corpus_record_id = m.corpus_record_id
                WHERE r.snapshot_id = ?
                """,
                (existing["snapshot_id"],),
            ).fetchone()["n"]
            return PersistResult(
                snapshot_id=int(existing["snapshot_id"]),
                source_sha256=digest,
                record_count=int(actual),
                manifestation_count=int(manifestations),
                duplicate_snapshot=True,
            )

        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO flight_corpus_snapshots (
                source_kind, source_ref, source_filename, source_sha256,
                format_name, format_version, exported_at, ingested_at,
                record_count, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'provisional')
            """,
            (
                source_kind,
                source_ref,
                source_filename,
                digest,
                format_name,
                str(format_version) if format_version is not None else None,
                exported_at,
                when,
                len(records),
            ),
        )
        if cursor.rowcount == 0:
            conn.rollback()
            raced = conn.execute(
                """
                SELECT snapshot_id, record_count
                FROM flight_corpus_snapshots
                WHERE source_sha256 = ?
                """,
                (digest,),
            ).fetchone()
            if raced is None:
                raise CorpusPersistenceError(
                    "duplicate SHA insert was ignored but no snapshot could be read back"
                )
            actual = conn.execute(
                "SELECT COUNT(*) AS n FROM flight_corpus_records WHERE snapshot_id = ?",
                (raced["snapshot_id"],),
            ).fetchone()["n"]
            if actual != raced["record_count"]:
                raise CorpusPersistenceError(
                    "concurrent duplicate snapshot has inconsistent stored record_count"
                )
            manifestations = conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM flight_source_manifestations m
                JOIN flight_corpus_records r
                  ON r.corpus_record_id = m.corpus_record_id
                WHERE r.snapshot_id = ?
                """,
                (raced["snapshot_id"],),
            ).fetchone()["n"]
            return PersistResult(
                snapshot_id=int(raced["snapshot_id"]),
                source_sha256=digest,
                record_count=int(actual),
                manifestation_count=int(manifestations),
                duplicate_snapshot=True,
            )

        snapshot_id = int(cursor.lastrowid)
        manifestation_count = 0

        for ordinal, record in enumerate(records):
            if not isinstance(record, dict):
                raise CorpusPersistenceError(f"record {ordinal} is not an object")
            corpus_uid = record.get("corpusUid")
            raw = record.get("raw")
            if not isinstance(corpus_uid, str) or not corpus_uid.strip():
                raise CorpusPersistenceError(f"record {ordinal} missing corpusUid")
            if not isinstance(raw, dict):
                raise CorpusPersistenceError(f"record {ordinal} missing raw source object")

            start_lat, start_lon = _endpoint(record, "start")
            end_lat, end_lon = _endpoint(record, "end")
            rec_cursor = conn.execute(
                """
                INSERT INTO flight_corpus_records (
                    corpus_uid, snapshot_id, source_flight_id_raw, callsign_raw,
                    month_bucket, start_time_utc, end_time_utc, point_count,
                    start_lat, start_lon, end_lat, end_lon,
                    raw_record_json, normalized_record_json, identity_status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'unresolved', ?)
                """,
                (
                    corpus_uid,
                    snapshot_id,
                    record.get("sourceFlightIdRaw"),
                    record.get("callsignRaw"),
                    record.get("monthBucket"),
                    record.get("startTimeUtc"),
                    record.get("endTimeUtc"),
                    record.get("pointCount"),
                    start_lat,
                    start_lon,
                    end_lat,
                    end_lon,
                    _canonical_json(raw),
                    _canonical_json({key: value for key, value in record.items() if key != "raw"}),
                    when,
                ),
            )
            corpus_record_id = int(rec_cursor.lastrowid)

            manifestations = record.get("sourceManifestations") or []
            if not isinstance(manifestations, list):
                raise CorpusPersistenceError(
                    f"record {ordinal} sourceManifestations must be a list"
                )
            for item in manifestations:
                if not isinstance(item, dict):
                    raise CorpusPersistenceError(
                        f"record {ordinal} has non-object source manifestation"
                    )
                conn.execute(
                    """
                    INSERT INTO flight_source_manifestations (
                        corpus_record_id, source_kind, source_folder_raw,
                        source_filename_raw, source_sha256, source_mtime_raw,
                        binding_status, raw_manifest_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'candidate', ?, ?)
                    """,
                    (
                        corpus_record_id,
                        _manifestation_kind(item),
                        item.get("folderRaw"),
                        item.get("filenameRaw"),
                        item.get("sourceSha256"),
                        str(item.get("mtimeRaw")) if item.get("mtimeRaw") is not None else None,
                        _canonical_json(item.get("raw", item)),
                        when,
                    ),
                )
                manifestation_count += 1

        persisted_count = conn.execute(
            "SELECT COUNT(*) AS n FROM flight_corpus_records WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()["n"]
        if persisted_count != len(records):
            raise CorpusPersistenceError(
                f"row conservation failed: expected {len(records)}, persisted {persisted_count}"
            )

        manifestation_read_back = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM flight_source_manifestations m
            JOIN flight_corpus_records r
              ON r.corpus_record_id = m.corpus_record_id
            WHERE r.snapshot_id = ?
            """,
            (snapshot_id,),
        ).fetchone()["n"]
        if manifestation_read_back != manifestation_count:
            raise CorpusPersistenceError(
                "manifestation row conservation failed: "
                f"expected {manifestation_count}, persisted {manifestation_read_back}"
            )

        conn.execute(
            "UPDATE flight_corpus_snapshots SET status = 'validated' WHERE snapshot_id = ?",
            (snapshot_id,),
        )
        verified = conn.execute(
            """
            SELECT status, record_count
            FROM flight_corpus_snapshots
            WHERE snapshot_id = ?
            """,
            (snapshot_id,),
        ).fetchone()
        if verified is None or verified["status"] != "validated":
            raise CorpusPersistenceError("snapshot read-back verification failed before commit")
        if verified["record_count"] != persisted_count:
            raise CorpusPersistenceError("snapshot record_count changed during transaction")

        conn.commit()

        return PersistResult(
            snapshot_id=snapshot_id,
            source_sha256=digest,
            record_count=len(records),
            manifestation_count=manifestation_count,
            duplicate_snapshot=False,
        )
    except (sqlite3.Error, CorpusPersistenceError) as exc:
        conn.rollback()
        if isinstance(exc, CorpusPersistenceError):
            raise
        raise CorpusPersistenceError(f"corpus persistence failed: {exc}") from exc
    finally:
        conn.close()


def read_corpus_snapshot(db_path: str | Path, snapshot_id: int) -> dict[str, Any]:
    """Read one snapshot and its records/manifestations without mutating the DB."""
    conn = db.connect(db_path, readonly=True)
    try:
        snapshot = conn.execute(
            "SELECT * FROM flight_corpus_snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        if snapshot is None:
            raise CorpusPersistenceError(f"snapshot not found: {snapshot_id}")

        record_rows = conn.execute(
            """
            SELECT *
            FROM flight_corpus_records
            WHERE snapshot_id = ?
            ORDER BY corpus_record_id
            """,
            (snapshot_id,),
        ).fetchall()
        records: list[dict[str, Any]] = []
        for row in record_rows:
            manifestations = conn.execute(
                """
                SELECT *
                FROM flight_source_manifestations
                WHERE corpus_record_id = ?
                ORDER BY manifestation_id
                """,
                (row["corpus_record_id"],),
            ).fetchall()
            records.append(
                {
                    **dict(row),
                    "raw_record": json.loads(row["raw_record_json"]),
                    "normalized_record": (
                        json.loads(row["normalized_record_json"])
                        if row["normalized_record_json"]
                        else None
                    ),
                    "manifestations": [dict(item) for item in manifestations],
                }
            )
        return {"snapshot": dict(snapshot), "records": records}
    finally:
        conn.close()
