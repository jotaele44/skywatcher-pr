-- ============================================================================
-- SKYWATCHER CANONICAL FLIGHT CORPUS V1
-- ============================================================================
-- Purpose:
--   Corpus/coverage authority for acquired flight manifests. This layer is
--   deliberately distinct from the analytical/reconstructed "flights" table.
--   A corpus record may exist without track geometry or a promoted flight entity.
--
-- Identity invariants:
--   * source snapshot identity is byte/content-addressed where available
--   * source flight ids/callsigns are discovery/binding evidence, not identity alone
--   * one corpus record may bind 0..N source manifestations
--   * contradictory manifestations are preserved; no destructive merge
-- ============================================================================

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS flight_corpus_snapshots (
    snapshot_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    source_kind       TEXT    NOT NULL,
    source_ref        TEXT,
    source_filename   TEXT,
    source_sha256     TEXT,
    format_name       TEXT    NOT NULL,
    format_version    TEXT,
    exported_at       TEXT,
    ingested_at       TEXT    NOT NULL,
    record_count      INTEGER NOT NULL DEFAULT 0,
    status            TEXT    NOT NULL DEFAULT 'provisional'
                      CHECK (status IN ('provisional','validated','failed','superseded')),
    notes             TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_flight_corpus_snapshot_sha
    ON flight_corpus_snapshots(source_sha256)
    WHERE source_sha256 IS NOT NULL AND TRIM(source_sha256) <> '';
CREATE INDEX IF NOT EXISTS ix_flight_corpus_snapshots_kind
    ON flight_corpus_snapshots(source_kind);

CREATE TABLE IF NOT EXISTS flight_corpus_snapshot_sources (
    source_observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id           INTEGER NOT NULL REFERENCES flight_corpus_snapshots(snapshot_id),
    source_kind           TEXT    NOT NULL,
    source_ref            TEXT    NOT NULL DEFAULT '',
    source_filename       TEXT    NOT NULL DEFAULT '',
    observed_at           TEXT    NOT NULL,
    UNIQUE(snapshot_id, source_kind, source_ref, source_filename)
);
CREATE INDEX IF NOT EXISTS ix_flight_corpus_snapshot_sources_snapshot
    ON flight_corpus_snapshot_sources(snapshot_id);

CREATE TABLE IF NOT EXISTS flight_corpus_records (
    corpus_record_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    corpus_uid              TEXT    NOT NULL,
    snapshot_id             INTEGER NOT NULL REFERENCES flight_corpus_snapshots(snapshot_id),
    source_flight_id_raw    TEXT,
    callsign_raw            TEXT,
    month_bucket            TEXT,
    start_time_utc          TEXT,
    end_time_utc            TEXT,
    point_count             INTEGER,
    start_lat               REAL,
    start_lon               REAL,
    end_lat                 REAL,
    end_lon                 REAL,
    raw_record_json         TEXT    NOT NULL,
    normalized_record_json  TEXT,
    identity_status         TEXT    NOT NULL DEFAULT 'unresolved'
                            CHECK (identity_status IN
                              ('unresolved','candidate','bound','conflicting')),
    analytical_flight_id    TEXT REFERENCES flights(flight_id),
    created_at              TEXT    NOT NULL,
    UNIQUE(snapshot_id, corpus_uid)
);
CREATE INDEX IF NOT EXISTS ix_flight_corpus_records_snapshot
    ON flight_corpus_records(snapshot_id);
CREATE INDEX IF NOT EXISTS ix_flight_corpus_records_source_id
    ON flight_corpus_records(source_flight_id_raw);
CREATE INDEX IF NOT EXISTS ix_flight_corpus_records_callsign
    ON flight_corpus_records(callsign_raw);
CREATE INDEX IF NOT EXISTS ix_flight_corpus_records_time
    ON flight_corpus_records(start_time_utc, end_time_utc);

CREATE TABLE IF NOT EXISTS flight_source_manifestations (
    manifestation_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    corpus_record_id    INTEGER NOT NULL REFERENCES flight_corpus_records(corpus_record_id),
    source_kind         TEXT    NOT NULL,
    source_folder_raw   TEXT,
    source_filename_raw TEXT,
    source_sha256       TEXT,
    source_mtime_raw    TEXT,
    binding_status      TEXT    NOT NULL DEFAULT 'candidate'
                        CHECK (binding_status IN
                          ('candidate','bound','conflicting','rejected','unresolved')),
    raw_manifest_json   TEXT    NOT NULL,
    created_at          TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_flight_manifestations_record
    ON flight_source_manifestations(corpus_record_id);
CREATE INDEX IF NOT EXISTS ix_flight_manifestations_sha
    ON flight_source_manifestations(source_sha256);
CREATE INDEX IF NOT EXISTS ix_flight_manifestations_name
    ON flight_source_manifestations(source_filename_raw);
