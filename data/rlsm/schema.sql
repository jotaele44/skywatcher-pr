-- RLSM screenshot analysis schema
-- Lossless extraction-first pipeline; raw OCR is append-only.
-- Created 2026-05-28

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- One row per image in the baseline.
CREATE TABLE IF NOT EXISTS screenshots (
    screenshot_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    sha256             TEXT UNIQUE NOT NULL,
    filename           TEXT NOT NULL,
    rel_path           TEXT NOT NULL,
    month_bucket       TEXT,
    filename_ts        TEXT,                              -- ISO 8601 (AST)
    ext                TEXT NOT NULL,
    size_bytes         INTEGER NOT NULL,
    width              INTEGER,
    height             INTEGER,
    phash              TEXT,                              -- 64-bit aHash hex
    dup_group_id       INTEGER,                           -- exact-sha duplicates
    near_dup_group_id  INTEGER,                           -- perceptual-hash duplicates
    ingest_status      TEXT NOT NULL,                     -- 'ok' | 'corrupt' | 'unreadable'
    ingest_error       TEXT,
    ocr_status         TEXT NOT NULL DEFAULT 'pending',   -- 'pending'|'ok'|'partial'|'failed'
    ingested_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_screenshots_filename     ON screenshots(filename);
CREATE INDEX IF NOT EXISTS ix_screenshots_month        ON screenshots(month_bucket);
CREATE INDEX IF NOT EXISTS ix_screenshots_status       ON screenshots(ingest_status);
CREATE INDEX IF NOT EXISTS ix_screenshots_ocr_status   ON screenshots(ocr_status);
CREATE INDEX IF NOT EXISTS ix_screenshots_phash        ON screenshots(phash);

-- Bookkeeping for each run.
CREATE TABLE IF NOT EXISTS processing_runs (
    run_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_kind      TEXT NOT NULL,                          -- 'inventory'|'ocr'|'labeled_poi'|'aircraft'|'track'|'unlabeled'|'review'
    started_at    TEXT NOT NULL,
    ended_at      TEXT,
    status        TEXT NOT NULL DEFAULT 'in_progress',    -- 'in_progress'|'completed'|'failed'
    n_inputs      INTEGER,
    n_processed   INTEGER,
    n_failed      INTEGER,
    git_sha       TEXT,
    notes         TEXT
);

-- Raw OCR per zone per attempt. raw_text is IMMUTABLE — never overwrite.
CREATE TABLE IF NOT EXISTS ocr_observations (
    obs_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    screenshot_id    INTEGER NOT NULL REFERENCES screenshots(screenshot_id),
    run_id           INTEGER REFERENCES processing_runs(run_id),
    zone             TEXT NOT NULL,                        -- 'top_bar'|'aircraft_card'|'map_center'|'label_layer'|'side_panel'|'bottom_panel'
    bbox_x           INTEGER,
    bbox_y           INTEGER,
    bbox_w           INTEGER,
    bbox_h           INTEGER,
    raw_text         TEXT NOT NULL,
    raw_lines_json   TEXT,
    confidence_mean  REAL,
    confidence_min   REAL,
    n_words          INTEGER,
    engine           TEXT NOT NULL DEFAULT 'tesseract',
    engine_version   TEXT,
    psm              INTEGER,
    ocr_status       TEXT NOT NULL,                        -- 'ok'|'empty'|'failed'
    ocr_error        TEXT,
    observed_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ocr_screenshot ON ocr_observations(screenshot_id, zone);
CREATE INDEX IF NOT EXISTS ix_ocr_run        ON ocr_observations(run_id);
CREATE INDEX IF NOT EXISTS ix_ocr_status     ON ocr_observations(ocr_status);

-- Aircraft metadata derived from OCR (plus backfill columns from the manual log).
CREATE TABLE IF NOT EXISTS aircraft_observations (
    aircraft_obs_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    screenshot_id    INTEGER NOT NULL REFERENCES screenshots(screenshot_id),
    run_id           INTEGER REFERENCES processing_runs(run_id),
    registration     TEXT,
    callsign         TEXT,
    aircraft_type    TEXT,
    altitude_ft      INTEGER,
    speed_kt         INTEGER,
    heading_deg      INTEGER,
    operator_text    TEXT,
    identity_status  TEXT,                                  -- 'confirmed'|'partial'|'conflicting'|'unknown'|'recovered'
    confidence       REAL,
    source_zone      TEXT,
    raw_excerpt      TEXT,
    observed_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_air_screenshot   ON aircraft_observations(screenshot_id);
CREATE INDEX IF NOT EXISTS ix_air_registration ON aircraft_observations(registration);
CREATE INDEX IF NOT EXISTS ix_air_callsign     ON aircraft_observations(callsign);
-- Dedup: prevent the run-53/run-67 N999ZY-style double-inserts. Partial index so
-- it only fires when a registration is actually set (NULL/empty rows are valid
-- and shouldn't collide). The recover-tails script and rlsm_extractors both
-- INSERT under this constraint; conflicts surface as sqlite3.IntegrityError.
CREATE UNIQUE INDEX IF NOT EXISTS ix_air_dedup
    ON aircraft_observations(screenshot_id, registration, source_zone)
    WHERE registration IS NOT NULL AND TRIM(registration) != '';

-- Track-shape descriptors per screenshot.
CREATE TABLE IF NOT EXISTS flight_track_features (
    track_feat_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    screenshot_id    INTEGER NOT NULL REFERENCES screenshots(screenshot_id),
    run_id           INTEGER REFERENCES processing_runs(run_id),
    path_shape       TEXT,                                  -- 'linear'|'curve'|'loop'|'orbit'|'hover'|'gap'|'multi'|'absent'
    has_loop         INTEGER,
    has_orbit        INTEGER,
    has_hover        INTEGER,
    has_gap          INTEGER,
    follows_coast    INTEGER,
    near_airport     INTEGER,
    track_length_px  REAL,
    bbox_x           INTEGER,
    bbox_y           INTEGER,
    bbox_w           INTEGER,
    bbox_h           INTEGER,
    confidence       REAL,
    observed_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_track_screenshot ON flight_track_features(screenshot_id);

-- Labeled POIs (text labels found on the map layer).
CREATE TABLE IF NOT EXISTS labeled_pois (
    poi_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    screenshot_id    INTEGER NOT NULL REFERENCES screenshots(screenshot_id),
    run_id           INTEGER REFERENCES processing_runs(run_id),
    raw_label        TEXT NOT NULL,
    normalized_label TEXT,
    bbox_x           INTEGER,
    bbox_y           INTEGER,
    bbox_w           INTEGER,
    bbox_h           INTEGER,
    centroid_x       INTEGER,
    centroid_y       INTEGER,
    poi_type_guess   TEXT,                                  -- 'city'|'airport'|'water'|'mountain'|'highway'|'neighborhood'|'unknown'
    confidence       REAL,
    review_status    TEXT NOT NULL DEFAULT 'unreviewed',
    observed_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_lpoi_screenshot ON labeled_pois(screenshot_id);
CREATE INDEX IF NOT EXISTS ix_lpoi_normalized ON labeled_pois(normalized_label);

-- Unlabeled POI candidates (visual features WITHOUT labels). Separate table by design.
CREATE TABLE IF NOT EXISTS unlabeled_poi_candidates (
    candidate_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    screenshot_id     INTEGER NOT NULL REFERENCES screenshots(screenshot_id),
    run_id            INTEGER REFERENCES processing_runs(run_id),
    candidate_type    TEXT NOT NULL,                        -- 'pad'|'clearing'|'road_scar'|'facility_cluster'|'antenna'|'tank'|'quarry'|'shoreline_infra'|'access_road'|'unknown'
    bbox_x            INTEGER,
    bbox_y            INTEGER,
    bbox_w            INTEGER,
    bbox_h            INTEGER,
    centroid_x        INTEGER,
    centroid_y        INTEGER,
    evidence_features TEXT,                                 -- JSON
    confidence        REAL,
    review_status     TEXT NOT NULL DEFAULT 'unreviewed',
    notes             TEXT,
    observed_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_upoi_screenshot ON unlabeled_poi_candidates(screenshot_id);
CREATE INDEX IF NOT EXISTS ix_upoi_type       ON unlabeled_poi_candidates(candidate_type);

-- Georeferencing anchors.
CREATE TABLE IF NOT EXISTS geo_anchors (
    anchor_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    screenshot_id    INTEGER REFERENCES screenshots(screenshot_id),
    anchor_kind      TEXT NOT NULL,                         -- 'static'|'derived'|'failed'
    name             TEXT,
    pixel_x          INTEGER,
    pixel_y          INTEGER,
    lat              REAL,
    lon              REAL,
    confidence       REAL,
    source           TEXT,
    notes            TEXT,
    observed_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_geo_screenshot ON geo_anchors(screenshot_id);

-- Manual flight log ingested from the operator's xlsx. Ground-truth observations.
CREATE TABLE IF NOT EXISTS manual_flight_log (
    log_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sheet_name          TEXT NOT NULL,
    sheet_row           INTEGER NOT NULL,
    fn_id               TEXT,
    uf_id               TEXT,
    flight_date         TEXT,                 -- ISO YYYY-MM-DD (AST)
    flight_time         TEXT,                 -- HH:MM (AST) or 'AM'/'PM'/'Midday'/'Noon'/'Evening'
    flight_time_24h_min INTEGER,              -- minutes since midnight (if parseable); NULL otherwise
    tail_raw            TEXT,
    tail_normalized     TEXT,                 -- 'N196DM', stripped of parens/quotes
    operator_raw        TEXT,
    operator_normalized TEXT,                 -- via alias map
    aircraft_type_hint  TEXT,                 -- from 'Operator / Type' field (e.g. 'B407', 'AS350')
    route_poi_chain     TEXT,
    behavior_notes      TEXT,
    mission_type        TEXT,
    corridor_zone       TEXT,                 -- AASB-1..7, OSAP, ILAP, named zones
    altitude_text       TEXT,
    speed_text          TEXT,
    confidence_text     TEXT,
    confidence_score    REAL,                 -- normalized 0..1
    status_text         TEXT,                 -- 'Confirmed', '✅', etc.
    raw_row_json        TEXT NOT NULL,        -- full original row preserved
    ingested_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_mlog_tail     ON manual_flight_log(tail_normalized);
CREATE INDEX IF NOT EXISTS ix_mlog_date     ON manual_flight_log(flight_date);
CREATE INDEX IF NOT EXISTS ix_mlog_corridor ON manual_flight_log(corridor_zone);
CREATE INDEX IF NOT EXISTS ix_mlog_operator ON manual_flight_log(operator_normalized);

-- Cross-references between manual log entries and screenshots
CREATE TABLE IF NOT EXISTS manual_flight_log_link (
    link_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    log_id            INTEGER NOT NULL REFERENCES manual_flight_log(log_id),
    screenshot_id     INTEGER NOT NULL REFERENCES screenshots(screenshot_id),
    match_kind        TEXT NOT NULL,         -- 'tail+date+time60'|'tail+date'|'tail+nearby_day'|'tail_only_unconstrained'
    time_diff_minutes INTEGER,
    confidence        REAL,
    created_at        TEXT NOT NULL,
    UNIQUE(log_id, screenshot_id)
);
CREATE INDEX IF NOT EXISTS ix_mlink_log        ON manual_flight_log_link(log_id);
CREATE INDEX IF NOT EXISTS ix_mlink_screenshot ON manual_flight_log_link(screenshot_id);
CREATE INDEX IF NOT EXISTS ix_mlink_match      ON manual_flight_log_link(match_kind);

-- FAA Aircraft Registry (source: registry.faa.gov ReleasableAircraft.zip).
-- One row per registration, joined to aircraft_observations via registration.
CREATE TABLE IF NOT EXISTS aircraft_registry (
    n_number              TEXT PRIMARY KEY,           -- 'N407PR' (canonical)
    serial_number         TEXT,
    mfr_mdl_code          TEXT,
    eng_mfr_mdl_code      TEXT,
    year_mfr              INTEGER,
    type_registrant       TEXT,
    name                  TEXT,                       -- owner name
    street                TEXT,
    street2               TEXT,
    city                  TEXT,
    state                 TEXT,
    zip_code              TEXT,
    region                TEXT,
    county                TEXT,
    country               TEXT,
    last_action_date      TEXT,
    cert_issue_date       TEXT,
    certification         TEXT,
    type_aircraft         TEXT,
    type_engine           TEXT,
    status_code           TEXT,
    mode_s_code           TEXT,
    fract_owner           TEXT,
    air_worth_date        TEXT,
    expiration_date       TEXT,
    unique_id             TEXT,
    -- Joined from ACFTREF on mfr_mdl_code
    manufacturer          TEXT,
    model                 TEXT,
    aircraft_category     TEXT,
    no_engines            INTEGER,
    no_seats              INTEGER,
    aircraft_weight       TEXT,
    cruise_speed          INTEGER,
    -- Bookkeeping
    fetched_at            TEXT NOT NULL,
    source                TEXT NOT NULL DEFAULT 'FAA_ReleasableAircraft'
);
CREATE INDEX IF NOT EXISTS ix_reg_name ON aircraft_registry(name);
CREATE INDEX IF NOT EXISTS ix_reg_mfr  ON aircraft_registry(manufacturer);

-- Manual review queue (covers all review categories).
CREATE TABLE IF NOT EXISTS manual_review_queue (
    review_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    screenshot_id    INTEGER REFERENCES screenshots(screenshot_id),
    item_kind        TEXT NOT NULL,                         -- 'labeled_poi_low_conf'|'unlabeled_candidate'|'aircraft_identity_conflict'|'time_conflict'|'geo_anchor_fail'|'ocr_low_conf'
    item_ref_table   TEXT,
    item_ref_id      INTEGER,
    reason           TEXT,
    severity         TEXT,                                  -- 'low'|'medium'|'high'
    review_status    TEXT NOT NULL DEFAULT 'unreviewed',
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_review_kind   ON manual_review_queue(item_kind);
CREATE INDEX IF NOT EXISTS ix_review_status ON manual_review_queue(review_status);
