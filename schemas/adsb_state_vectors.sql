-- ===========================================================================
-- ADS-B STATE VECTORS  (migration 0002 — automated live-feed poll)
-- ===========================================================================
-- Raw state vectors polled from an automated ADS-B provider (OpenSky Network
-- by default; see adsb/providers/opensky.py). Kept as its own append-only
-- table, separate from flights/track_points: those tables encode invariants
-- specific to screenshot-reconstructed flights (coordinate_method enum,
-- flight_id derived from screenshot fusion, mission gating) that do not apply
-- to a live position report. aircraft.callsign / aircraft_intelligence.py
-- enrichment is looked up at read time from callsign; it is not duplicated
-- into this table.
--
-- This file is applied by src/skywatcher/fr24/database_migrations.py as
-- migration 0002, on top of migration 0001 (schemas/database_schema.sql). It
-- is idempotent (CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS).
-- ===========================================================================

CREATE TABLE IF NOT EXISTS adsb_state_vectors (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    provider          TEXT    NOT NULL DEFAULT 'opensky',
    icao24            TEXT    NOT NULL,
    callsign          TEXT,
    origin_country    TEXT,
    time_position     INTEGER,                    -- Unix epoch seconds
    last_contact      INTEGER,                     -- Unix epoch seconds
    longitude         REAL,
    latitude          REAL,
    baro_altitude_m   REAL,
    on_ground         INTEGER NOT NULL DEFAULT 0,  -- boolean (0/1)
    velocity_mps      REAL,
    true_track_deg    REAL,
    vertical_rate_mps REAL,
    geo_altitude_m    REAL,
    squawk            TEXT,
    position_source   INTEGER,
    batch_id          INTEGER REFERENCES ingestion_batches(batch_id),
    polled_at         TEXT    NOT NULL             -- ISO-8601 UTC
);
CREATE INDEX IF NOT EXISTS ix_adsb_icao24    ON adsb_state_vectors(icao24);
CREATE INDEX IF NOT EXISTS ix_adsb_callsign  ON adsb_state_vectors(callsign);
CREATE INDEX IF NOT EXISTS ix_adsb_polled_at ON adsb_state_vectors(polled_at);
CREATE INDEX IF NOT EXISTS ix_adsb_batch     ON adsb_state_vectors(batch_id);
