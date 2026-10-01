"""Integration gates against Skywatcher's released 0001 and 0003 database states.

These tests deliberately DO NOT register a migration 0004. They prove only that
the inactive sidecar can be applied to isolated representative databases without
altering pre-existing rows, identities, or the migration ledger.
"""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from skywatcher.fr24 import database as db
from skywatcher.fr24 import database_migrations as migrations
from skywatcher.fr24.flight_corpus import persist_corpus_snapshot

REPO = Path(__file__).resolve().parents[1]
SIDE_SQL = (REPO / "schemas" / "knowledge_implications_v1.sql").read_text(
    encoding="utf-8"
)
SIDE_DDL = SIDE_SQL.replace("PRAGMA foreign_keys = ON;", "", 1)
ZERO = hashlib.sha256(b"").hexdigest()


def _install_sidecar_atomic(conn: sqlite3.Connection) -> None:
    """Apply the draft DDL in one explicit transaction and leave no partial DDL."""
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.executescript("BEGIN IMMEDIATE;\n" + SIDE_DDL)
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
        raise


def _table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = [
        row[0]
        for row in conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table'
              AND name NOT LIKE 'sqlite_%'
              AND name NOT LIKE 'swk_%'
            ORDER BY name
            """
        )
    ]
    return {
        name: conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        for name in tables
    }


def _open(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _record(uid: str) -> dict:
    return {
        "corpusUid": uid,
        "monthBucket": "2026-09",
        "sourceFlightIdRaw": "feed1234",
        "callsignRaw": "NTEST1",
        "pointCount": 2,
        "startTimeUtc": "2026-09-29T12:00:00Z",
        "endTimeUtc": "2026-09-29T12:10:00Z",
        "start": {"lat": 18.0, "lon": -67.0},
        "end": {"lat": 18.1, "lon": -67.1},
        "sourceManifestations": [
            {
                "folderRaw": "NTEST1",
                "filenameRaw": "feed1234.csv",
                "sourceSha256": "a" * 64,
                "mtimeRaw": 1790683200,
                "raw": {"n": "feed1234.csv"},
            }
        ],
        "raw": {"uid": uid, "fid": "feed1234"},
    }


def test_sidecar_on_released_0001_preserves_existing_rows_and_version(tmp_path):
    path = tmp_path / "v1.db"
    conn = db.connect(path)
    try:
        assert migrations.apply_migrations(conn, target=1) == [1]
        conn.execute(
            """
            INSERT INTO ingestion_batches(batch_kind, started_at)
            VALUES('test', '2026-09-30T00:00:00Z')
            """
        )
        batch_id = conn.execute("SELECT batch_id FROM ingestion_batches").fetchone()[0]
        conn.execute(
            """
            INSERT INTO screenshots(
              sha256,filename,ext,size_bytes,batch_id,ingested_at
            ) VALUES(?,?,?,?,?,?)
            """,
            ("b" * 64, "frame.png", ".png", 123, batch_id, "2026-09-30T00:00:00Z"),
        )
        screenshot_id = conn.execute("SELECT screenshot_id FROM screenshots").fetchone()[0]
        conn.execute("INSERT INTO aircraft(registration) VALUES('NTEST1')")
        aircraft_id = conn.execute("SELECT aircraft_id FROM aircraft").fetchone()[0]
        conn.execute(
            """
            INSERT INTO flights(flight_id,aircraft_id,created_at)
            VALUES('flight-v1',?,?)
            """,
            (aircraft_id, "2026-09-30T00:00:00Z"),
        )
        conn.execute(
            """
            INSERT INTO flight_screenshots(
              flight_id,screenshot_id,match_kind,created_at
            ) VALUES('flight-v1',?,'fixture',?)
            """,
            (screenshot_id, "2026-09-30T00:00:00Z"),
        )
        conn.commit()

        before = _table_counts(conn)
        version_before = db.get_schema_version(conn)
        _install_sidecar_atomic(conn)
        after = _table_counts(conn)

        assert before == after
        assert version_before == db.get_schema_version(conn) == 1
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []

        # CREATE IF NOT EXISTS semantics are repeatable and row-conserving.
        _install_sidecar_atomic(conn)
        assert _table_counts(conn) == before
        assert db.get_schema_version(conn) == 1
    finally:
        conn.close()


def test_sidecar_on_released_0003_preserves_mfl_and_allows_bounded_pairing(tmp_path):
    path = tmp_path / "v3.db"
    conn = db.connect(path)
    try:
        assert migrations.apply_migrations(conn, target=3) == [1, 2, 3]
    finally:
        conn.close()

    result = persist_corpus_snapshot(
        path,
        source_bytes=b"<html>representative mfl</html>",
        source_kind="master_flight_log_html",
        source_filename="Master Flight Log.html",
        format_name="master-flight-log-backup",
        format_version=1,
        records=[_record("mfl:fixture:1")],
    )

    conn = _open(path)
    try:
        before = _table_counts(conn)
        version_before = db.get_schema_version(conn)
        corpus_before = conn.execute(
            "SELECT corpus_record_id, corpus_uid, identity_status "
            "FROM flight_corpus_records ORDER BY corpus_record_id"
        ).fetchall()
        manifestations_before = conn.execute(
            "SELECT manifestation_id, source_filename_raw, binding_status "
            "FROM flight_source_manifestations ORDER BY manifestation_id"
        ).fetchall()

        _install_sidecar_atomic(conn)

        assert _table_counts(conn) == before
        assert db.get_schema_version(conn) == version_before == 3
        assert conn.execute(
            "SELECT corpus_record_id, corpus_uid, identity_status "
            "FROM flight_corpus_records ORDER BY corpus_record_id"
        ).fetchall() == corpus_before
        assert conn.execute(
            "SELECT manifestation_id, source_filename_raw, binding_status "
            "FROM flight_source_manifestations ORDER BY manifestation_id"
        ).fetchall() == manifestations_before

        # Two source namespaces can support one review subject without altering
        # the MFL corpus record or manufacturing a canonical event.
        when = "2026-09-30T00:00:00Z"
        mfl_sha = result.source_sha256
        conn.execute(
            """
            INSERT INTO swk_source_artifact(
              artifact_id,source_namespace,external_source_key_raw,
              source_snapshot_sha256,byte_sha256,source_kind,
              evidence_tier,visibility_class,provenance_status,created_utc
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "art-mfl",
                "MFL_SNAPSHOT",
                "mfl:fixture:1",
                mfl_sha,
                mfl_sha,
                "MFL_RECORD",
                "T1",
                "V2",
                "COMPLETE",
                when,
            ),
        )
        conn.execute(
            """
            INSERT INTO swk_source_artifact(
              artifact_id,source_namespace,external_source_key_raw,
              source_snapshot_sha256,byte_sha256,source_kind,
              evidence_tier,visibility_class,provenance_status,created_utc
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "art-shot",
                "RLSM_LOCAL",
                "screenshot:fixture:1",
                "c" * 64,
                "d" * 64,
                "SCREENSHOT",
                "UNKNOWN",
                "V0",
                "COMPLETE",
                when,
            ),
        )
        conn.execute(
            """
            INSERT INTO swk_subject_ref(
              subject_id,subject_kind,source_namespace,external_record_key_raw,
              source_snapshot_sha256,identity_state,binding_basis_json,created_utc
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                "subject-review-1",
                "RECONSTRUCTED_FLIGHT",
                "SKYWATCHER_PRIMARY",
                "review-only:fixture:1",
                None,
                "PROVISIONAL",
                '{"basis":"manual test fixture; not event identity proof"}',
                when,
            ),
        )
        for artifact_id in ("art-mfl", "art-shot"):
            conn.execute(
                """
                INSERT INTO swk_subject_evidence(
                  subject_id,artifact_id,relation,binding_state,evidence_basis_json
                ) VALUES(?,?,?,?,?)
                """,
                (
                    "subject-review-1",
                    artifact_id,
                    "SUPPORT",
                    "PROVISIONAL",
                    '{"basis":"independent fixture association"}',
                ),
            )
        conn.commit()

        assert conn.execute(
            "SELECT COUNT(*) FROM swk_subject_evidence "
            "WHERE subject_id='subject-review-1'"
        ).fetchone()[0] == 2
        assert conn.execute(
            "SELECT COUNT(*) FROM flight_corpus_records WHERE snapshot_id=?",
            (result.snapshot_id,),
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM swk_knowledge_state "
            "WHERE canonical_event_count IS NOT NULL"
        ).fetchone()[0] == 0
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()


def test_near_duplicate_and_contradictory_sources_remain_distinct(tmp_path):
    path = tmp_path / "contradiction.db"
    conn = db.connect(path)
    try:
        migrations.apply_migrations(conn, target=3)
    finally:
        conn.close()

    conn = _open(path)
    try:
        _install_sidecar_atomic(conn)
        when = "2026-09-30T00:00:00Z"
        for artifact_id, digest in (("near-a", "1" * 64), ("near-b", "2" * 64)):
            conn.execute(
                """
                INSERT INTO swk_source_artifact(
                  artifact_id,source_namespace,external_source_key_raw,
                  byte_sha256,source_kind,evidence_tier,visibility_class,created_utc
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    artifact_id,
                    "RLSM_LOCAL",
                    "same-discovery-key",
                    digest,
                    "SCREENSHOT",
                    "UNKNOWN",
                    "V0",
                    when,
                ),
            )
        conn.execute(
            """
            INSERT INTO swk_subject_ref(
              subject_id,subject_kind,source_namespace,external_record_key_raw,
              identity_state,binding_basis_json,created_utc
            ) VALUES('subject-c','AIRCRAFT_CANDIDATE','RLSM_LOCAL',
                     'same-discovery-key','UNRESOLVED','{}',?)
            """,
            (when,),
        )
        conn.execute(
            """
            INSERT INTO swk_subject_evidence VALUES(
              'subject-c','near-a','SUPPORT','OPEN','{"claim":"candidate A"}'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO swk_subject_evidence VALUES(
              'subject-c','near-b','COUNTEREVIDENCE','OPEN','{"claim":"candidate B"}'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO swk_knowledge_run(
              run_id,input_manifest_sha256,ruleset_sha256,baseline_commit,started_utc
            ) VALUES('run-c',?,?,?,?)
            """,
            (ZERO, ZERO, "fixture", when),
        )
        conn.execute(
            """
            INSERT INTO swk_contradiction(
              contradiction_id,run_id,contradiction_class,
              observation_a_ref,observation_b_ref,status,created_utc
            ) VALUES('con-c','run-c','IDENTITY','near-a','near-b','UNRESOLVED',?)
            """,
            (when,),
        )
        conn.commit()

        assert conn.execute(
            "SELECT COUNT(*) FROM swk_source_artifact "
            "WHERE external_source_key_raw='same-discovery-key'"
        ).fetchone()[0] == 2
        roles = [
            row[0]
            for row in conn.execute(
                "SELECT relation FROM swk_subject_evidence "
                "WHERE subject_id='subject-c' ORDER BY relation"
            )
        ]
        assert roles == ["COUNTEREVIDENCE", "SUPPORT"]
        assert conn.execute(
            "SELECT status FROM swk_contradiction WHERE contradiction_id='con-c'"
        ).fetchone()[0] == "UNRESOLVED"
        assert conn.execute(
            "SELECT identity_state FROM swk_subject_ref WHERE subject_id='subject-c'"
        ).fetchone()[0] == "UNRESOLVED"
    finally:
        conn.close()


def test_sidecar_schema_has_no_mission_or_intent_output_field():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        _install_sidecar_atomic(conn)
        columns = {
            row[1].lower()
            for table in (
                "swk_subject_ref",
                "swk_implication",
                "swk_knowledge_state",
                "swk_knowledge_delta",
            )
            for row in conn.execute(f'PRAGMA table_info("{table}")')
        }
        assert "mission" not in columns
        assert "mission_type" not in columns
        assert "intent" not in columns
        assert "purpose" not in columns
    finally:
        conn.close()
