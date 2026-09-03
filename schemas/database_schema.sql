-- ===========================================================================
-- SKYWATCHER FR24 CANONICAL DATABASE SCHEMA
-- ===========================================================================
-- Owner: skywatcher-pr (FR24 screenshot-processing repository boundary).
-- Consolidates the two previously divergent schemas:
--   * data/rlsm/schema.sql            (INTEGER-PK screenshots, sha256 UNIQUE)
--   * ad-hoc FlightDatabase tables     (TEXT-sha256-PK screenshots, flights,
--                                       track_points, aircraft_profiles, ...)
--
-- Design invariants (mission Phase 3):
--   * SHA-256 provenance          -> screenshots.sha256 UNIQUE NOT NULL
--   * UTC timestamps              -> all *_at / *_time columns are ISO-8601 UTC
--   * source references           -> *.source_ref, ingestion_batches.source_ref
--   * OCR confidence              -> ocr_observations.confidence_mean/_min
--   * coordinate method + conf    -> track_points / flights (widened enum)
--   * parser version              -> ocr_observations.parser_version, flights
--   * review status               -> screenshots/flights/anomalies.review_status
--   * append-only ingestion       -> ingestion_batches (never updated in place
--                                    except to close a batch)
--   * explicit foreign keys       -> PRAGMA foreign_keys = ON + FK clauses
--   * indexes + uniqueness        -> see per-table indexes below
--
-- This file is applied by src/skywatcher/fr24/database.py as migration 0001.
-- It is idempotent (CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS).
-- It NEVER creates or populates an operational database as a side effect.
-- ===========================================================================

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- ---------------------------------------------------------------------------
-- 1. schema_version  (migration ledger; append-only)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_version (
    version      INTEGER PRIMARY KEY,           -- monotonically increasing
    description  TEXT    NOT NULL,
    applied_at   TEXT    NOT NULL               -- ISO-8601 UTC
);

-- ---------------------------------------------------------------------------
-- 2. ingestion_batches  (one row per ingest run; append-only history)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ingestion_batches (
    batch_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_kind   TEXT    NOT NULL,              -- 'inventory'|'ocr'|'fusion'|'export'|...
    source_ref   TEXT,                          -- provenance: source dir / manifest id
    started_at   TEXT    NOT NULL,              -- ISO-8601 UTC
    ended_at     TEXT,
    status       TEXT    NOT NULL DEFAULT 'in_progress'
                 CHECK (status IN ('in_progress','completed','failed')),
    n_inputs     INTEGER NOT NULL DEFAULT 0,
    n_processed  INTEGER NOT NULL DEFAULT 0,
    n_failed     INTEGER NOT NULL DEFAULT 0,
    git_sha      TEXT,
    notes        TEXT
);
CREATE INDEX IF NOT EXISTS ix_batches_kind   ON ingestion_batches(batch_kind);
CREATE INDEX IF NOT EXISTS ix_batches_status ON ingestion_batches(status);

-- ---------------------------------------------------------------------------
-- 3. screenshots  (one row per unique image; sha256 is the content identity)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS screenshots (
    screenshot_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    sha256            TEXT    UNIQUE NOT NULL,   -- content-addressed identity
    filename          TEXT    NOT NULL,
    rel_path          TEXT,
    source_ref        TEXT,                      -- provenance (batch source)
    month_bucket      TEXT,
    filename_ts       TEXT,                      -- ISO-8601 (from filename)
    ext               TEXT    NOT NULL,
    size_bytes        INTEGER NOT NULL,
    width             INTEGER,
    height            INTEGER,
    phash             TEXT,                      -- perceptual hash (near-dup)
    dup_group_id      INTEGER,                   -- exact-sha duplicate group
    near_dup_group_id INTEGER,                   -- perceptual-hash dup group
    ingest_status     TEXT    NOT NULL DEFAULT 'ok'
                      CHECK (ingest_status IN ('ok','corrupt','unreadable')),
    ingest_error      TEXT,
    ocr_status        TEXT    NOT NULL DEFAULT 'pending'
                      CHECK (ocr_status IN ('pending','ok','partial','failed')),
    review_status     TEXT    NOT NULL DEFAULT 'pending',
    batch_id          INTEGER REFERENCES ingestion_batches(batch_id),
    ingested_at       TEXT    NOT NULL           -- ISO-8601 UTC
);
CREATE INDEX IF NOT EXISTS ix_screenshots_filename   ON screenshots(filename);
CREATE INDEX IF NOT EXISTS ix_screenshots_month      ON screenshots(month_bucket);
CREATE INDEX IF NOT EXISTS ix_screenshots_ocr_status ON screenshots(ocr_status);
CREATE INDEX IF NOT EXISTS ix_screenshots_phash      ON screenshots(phash);
CREATE INDEX IF NOT EXISTS ix_screenshots_batch      ON screenshots(batch_id);

-- ---------------------------------------------------------------------------
-- 4. ocr_observations  (append-only raw OCR; raw_text is immutable evidence)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ocr_observations (
    obs_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    screenshot_id   INTEGER NOT NULL REFERENCES screenshots(screenshot_id),
    batch_id        INTEGER REFERENCES ingestion_batches(batch_id),
    zone            TEXT    NOT NULL,            -- 'bottom_panel'|'aircraft_card'|...
    bbox_x          REAL, bbox_y REAL, bbox_w REAL, bbox_h REAL,
    raw_text        TEXT    NOT NULL,            -- immutable
    raw_lines_json  TEXT,
    confidence_mean REAL,                        -- OCR confidence 0..1
    confidence_min  REAL,
    n_words         INTEGER,
    engine          TEXT    NOT NULL DEFAULT 'tesseract',
    engine_version  TEXT,
    psm             INTEGER,
    parser_version  TEXT,
    ocr_status      TEXT    NOT NULL DEFAULT 'ok'
                    CHECK (ocr_status IN ('ok','empty','partial','failed')),
    ocr_error       TEXT,
    observed_at     TEXT    NOT NULL             -- ISO-8601 UTC
);
CREATE INDEX IF NOT EXISTS ix_ocr_screenshot ON ocr_observations(screenshot_id, zone);
CREATE INDEX IF NOT EXISTS ix_ocr_batch      ON ocr_observations(batch_id);
CREATE INDEX IF NOT EXISTS ix_ocr_status     ON ocr_observations(ocr_status);

-- ---------------------------------------------------------------------------
-- 5. aircraft  (canonical aircraft identity; merges observation + registry)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS aircraft (
    aircraft_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    registration    TEXT,                        -- N-number / tail
    callsign        TEXT,
    aircraft_type   TEXT,
    operator_text   TEXT,
    identity_status TEXT    NOT NULL DEFAULT 'unknown'
                    CHECK (identity_status IN
                        ('confirmed','partial','conflicting','unknown','recovered')),
    confidence      REAL,                        -- 0..1
    source_ref      TEXT,
    first_seen      TEXT,
    last_seen       TEXT
);
-- One canonical row per non-empty registration.
CREATE UNIQUE INDEX IF NOT EXISTS ux_aircraft_registration
    ON aircraft(registration)
    WHERE registration IS NOT NULL AND TRIM(registration) <> '';
CREATE INDEX IF NOT EXISTS ix_aircraft_callsign ON aircraft(callsign);

-- ---------------------------------------------------------------------------
-- 6. flights  (reconstructed flights)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS flights (
    flight_id               TEXT    PRIMARY KEY,   -- deterministic id
    aircraft_id             INTEGER REFERENCES aircraft(aircraft_id),
    callsign                TEXT,
    aircraft_type           TEXT,
    operator                TEXT,
    origin_airport          TEXT,
    destination_airport     TEXT,
    origin_lat REAL, origin_lon REAL,
    dest_lat   REAL, dest_lon   REAL,
    takeoff_time            TEXT,                  -- ISO-8601 UTC
    landing_time            TEXT,
    flight_duration_minutes INTEGER,
    max_altitude_ft         INTEGER,
    avg_speed_mph           REAL,
    -- Gated mission classification (speculative-until-evidence-gated policy):
    mission_type            TEXT,
    mission_status          TEXT    NOT NULL DEFAULT 'highly_speculative'
                            CHECK (mission_status IN
                                ('highly_speculative','evidence_gated')),
    mission_confidence      REAL,
    num_screenshots         INTEGER NOT NULL DEFAULT 0,
    confidence              REAL,                  -- overall 0..1
    coordinate_method       TEXT
                            CHECK (coordinate_method IS NULL OR coordinate_method IN
                                ('fixed_pr_bounds','airport_anchor','manual_anchor_csv',
                                 'per_screenshot_affine','synthetic_wgs84_point','unknown')),
    coordinate_confidence   REAL,
    review_status           TEXT    NOT NULL DEFAULT 'pending',
    parser_version          TEXT,
    source_ref              TEXT,
    created_at              TEXT    NOT NULL        -- ISO-8601 UTC
);
CREATE INDEX IF NOT EXISTS ix_flights_callsign ON flights(callsign);
CREATE INDEX IF NOT EXISTS ix_flights_aircraft ON flights(aircraft_id);
CREATE INDEX IF NOT EXISTS ix_flights_origin   ON flights(origin_airport);
CREATE INDEX IF NOT EXISTS ix_flights_dest     ON flights(destination_airport);

-- ---------------------------------------------------------------------------
-- 7. flight_screenshots  (junction: which screenshots compose a flight)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS flight_screenshots (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    flight_id         TEXT    NOT NULL REFERENCES flights(flight_id),
    screenshot_id     INTEGER NOT NULL REFERENCES screenshots(screenshot_id),
    match_kind        TEXT,                        -- 'fusion'|'manual_log'|...
    time_diff_minutes REAL,
    confidence        REAL,
    created_at        TEXT    NOT NULL,            -- ISO-8601 UTC
    UNIQUE (flight_id, screenshot_id)
);
CREATE INDEX IF NOT EXISTS ix_fs_flight     ON flight_screenshots(flight_id);
CREATE INDEX IF NOT EXISTS ix_fs_screenshot ON flight_screenshots(screenshot_id);

-- ---------------------------------------------------------------------------
-- 8. track_points  (ordered geo points for a flight)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS track_points (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    flight_id             TEXT    NOT NULL REFERENCES flights(flight_id),
    screenshot_id         INTEGER REFERENCES screenshots(screenshot_id),
    seq                   INTEGER,                 -- order within the flight
    timestamp             TEXT,                    -- ISO-8601 UTC
    latitude              REAL,
    longitude             REAL,
    altitude_ft           INTEGER,
    ground_speed_mph      REAL,
    coordinate_method     TEXT
                          CHECK (coordinate_method IS NULL OR coordinate_method IN
                              ('fixed_pr_bounds','airport_anchor','manual_anchor_csv',
                               'per_screenshot_affine','synthetic_wgs84_point','unknown')),
    coordinate_confidence REAL,
    estimated_error_m     REAL
);
CREATE INDEX IF NOT EXISTS ix_track_flight ON track_points(flight_id);
CREATE INDEX IF NOT EXISTS ix_track_coords ON track_points(latitude, longitude);

-- ---------------------------------------------------------------------------
-- 9. anomalies  (derived anomaly flags; review-gated)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS anomalies (
    anomaly_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    flight_id      TEXT    REFERENCES flights(flight_id),
    screenshot_id  INTEGER REFERENCES screenshots(screenshot_id),
    category       TEXT    NOT NULL,
    severity       TEXT    NOT NULL DEFAULT 'info'
                   CHECK (severity IN ('info','low','medium','high','critical')),
    description    TEXT,
    source_ref     TEXT,
    review_status  TEXT    NOT NULL DEFAULT 'pending',
    detected_at    TEXT    NOT NULL               -- ISO-8601 UTC
);
CREATE INDEX IF NOT EXISTS ix_anomalies_flight   ON anomalies(flight_id);
CREATE INDEX IF NOT EXISTS ix_anomalies_severity ON anomalies(severity);

-- ---------------------------------------------------------------------------
-- 10. processing_failures  (structured error accounting; append-only)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS processing_failures (
    failure_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id      INTEGER REFERENCES ingestion_batches(batch_id),
    screenshot_id INTEGER REFERENCES screenshots(screenshot_id),
    stage         TEXT    NOT NULL,               -- 'ingest'|'ocr'|'parse'|...
    reason        TEXT    NOT NULL,
    detail        TEXT,
    occurred_at   TEXT    NOT NULL                -- ISO-8601 UTC
);
CREATE INDEX IF NOT EXISTS ix_failures_batch ON processing_failures(batch_id);
CREATE INDEX IF NOT EXISTS ix_failures_stage ON processing_failures(stage);
