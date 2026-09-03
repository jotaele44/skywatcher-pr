-- RLSM screenshot analysis schema
-- Lossless extraction-first pipeline; raw OCR is append-only.
-- Created 2026-05-28

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- One logical row per unique screenshot payload SHA-256.
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
    source_availability TEXT NOT NULL DEFAULT 'present'
        CHECK (source_availability IN ('present','missing_on_disk','restored','archived')),
    availability_checked_at TEXT,
    availability_detail TEXT,
    availability_source TEXT,
    ingested_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_screenshots_filename     ON screenshots(filename);
CREATE INDEX IF NOT EXISTS ix_screenshots_month        ON screenshots(month_bucket);
CREATE INDEX IF NOT EXISTS ix_screenshots_status       ON screenshots(ingest_status);
CREATE INDEX IF NOT EXISTS ix_screenshots_ocr_status   ON screenshots(ocr_status);
CREATE INDEX IF NOT EXISTS ix_screenshots_phash        ON screenshots(phash);
CREATE UNIQUE INDEX IF NOT EXISTS ux_screenshots_rel_path ON screenshots(rel_path);
CREATE INDEX IF NOT EXISTS ix_screenshots_source_availability ON screenshots(source_availability);

-- Physical source manifestations are distinct from logical screenshot payloads.
-- Multiple rel_paths may map N:1 to one screenshots row when their SHA-256
-- payloads are identical. This preserves every source manifestation without
-- duplicating OCR/derived logical state.
CREATE TABLE IF NOT EXISTS source_manifestations (
    manifestation_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    rel_path             TEXT UNIQUE NOT NULL,
    sha256               TEXT NOT NULL,
    screenshot_id        INTEGER NOT NULL REFERENCES screenshots(screenshot_id),
    filename             TEXT NOT NULL,
    ext                  TEXT NOT NULL,
    size_bytes           INTEGER NOT NULL,
    manifestation_role   TEXT NOT NULL CHECK (
        manifestation_role IN ('canonical_payload','duplicate_payload')
    ),
    source_availability  TEXT NOT NULL DEFAULT 'present' CHECK (
        source_availability IN (
            'present','missing_on_disk','restored','archived'
        )
    ),
    observed_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_source_manifestations_sha256
    ON source_manifestations(sha256);
CREATE INDEX IF NOT EXISTS ix_source_manifestations_screenshot
    ON source_manifestations(screenshot_id);
CREATE INDEX IF NOT EXISTS ix_source_manifestations_availability
    ON source_manifestations(source_availability);

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
    word_boxes_version TEXT,
    confidence_mean  REAL,
    confidence_min   REAL,
    n_words          INTEGER,
    engine           TEXT NOT NULL DEFAULT 'tesseract',
    engine_version   TEXT,
    psm              INTEGER,
    preprocess       TEXT,                                 -- fr24.rlsm_preprocess mode: 'none'|'high_contrast'|'label_mask'
    preprocess_scale REAL,                                 -- upscale applied before OCR; word boxes already divide it out
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
    pixel_x          REAL CHECK (pixel_x IS NULL OR pixel_x >= 0),
    pixel_y          REAL CHECK (pixel_y IS NULL OR pixel_y >= 0),
    icon_rotation_deg REAL CHECK (
        icon_rotation_deg IS NULL OR
        (icon_rotation_deg >= 0 AND icon_rotation_deg < 360)
    ),
    marker_confidence REAL CHECK (
        marker_confidence IS NULL OR
        (marker_confidence >= 0 AND marker_confidence <= 1)
    ),
    marker_method    TEXT,
    position_lat     REAL CHECK (
        position_lat IS NULL OR (position_lat >= -90 AND position_lat <= 90)
    ),
    position_lon     REAL CHECK (
        position_lon IS NULL OR (position_lon >= -180 AND position_lon <= 180)
    ),
    position_method  TEXT,
    position_confidence REAL CHECK (
        position_confidence IS NULL OR
        (position_confidence >= 0 AND position_confidence <= 1)
    ),
    position_error_m REAL CHECK (position_error_m IS NULL OR position_error_m >= 0),
    position_observed_at TEXT,
    observed_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_air_screenshot   ON aircraft_observations(screenshot_id);
CREATE INDEX IF NOT EXISTS ix_air_registration ON aircraft_observations(registration);
CREATE INDEX IF NOT EXISTS ix_air_callsign     ON aircraft_observations(callsign);
CREATE INDEX IF NOT EXISTS ix_air_position
    ON aircraft_observations(position_lat, position_lon)
    WHERE position_lat IS NOT NULL AND position_lon IS NOT NULL;
-- Spatial observation fields are atomic.  A marker binding may have nullable
-- rotation, but its pixel/provenance quartet must be complete.  A published
-- coordinate additionally requires complete uncertainty metadata, a supported
-- method, an accepted marker binding, and the v0.1 500 m ceiling.
CREATE TRIGGER IF NOT EXISTS tr_air_spatial_contract_insert
BEFORE INSERT ON aircraft_observations
WHEN
    NOT (
        (
            NEW.pixel_x IS NULL AND NEW.pixel_y IS NULL AND
            NEW.icon_rotation_deg IS NULL AND NEW.marker_confidence IS NULL AND
            NEW.marker_method IS NULL
        ) OR (
            NEW.pixel_x IS NOT NULL AND NEW.pixel_y IS NOT NULL AND
            NEW.marker_confidence IS NOT NULL AND NEW.marker_method IS NOT NULL
        )
    )
    OR NOT (
        (
            NEW.position_lat IS NULL AND NEW.position_lon IS NULL AND
            NEW.position_method IS NULL AND NEW.position_confidence IS NULL AND
            NEW.position_error_m IS NULL AND NEW.position_observed_at IS NULL
        ) OR (
            NEW.position_lat IS NOT NULL AND NEW.position_lon IS NOT NULL AND
            NEW.position_method IN (
                'multi_anchor_affine','one_anchor_zoom_rung'
            ) AND
            NEW.position_confidence IS NOT NULL AND
            NEW.position_error_m IS NOT NULL AND NEW.position_error_m <= 500 AND
            NEW.position_observed_at IS NOT NULL AND
            NEW.pixel_x IS NOT NULL AND NEW.pixel_y IS NOT NULL AND
            NEW.marker_confidence IS NOT NULL AND NEW.marker_method IS NOT NULL
        )
    )
BEGIN
    SELECT RAISE(ABORT, 'aircraft spatial fields violate the v0.1 contract');
END;

CREATE TRIGGER IF NOT EXISTS tr_air_spatial_contract_update
BEFORE UPDATE ON aircraft_observations
WHEN
    NOT (
        (
            NEW.pixel_x IS NULL AND NEW.pixel_y IS NULL AND
            NEW.icon_rotation_deg IS NULL AND NEW.marker_confidence IS NULL AND
            NEW.marker_method IS NULL
        ) OR (
            NEW.pixel_x IS NOT NULL AND NEW.pixel_y IS NOT NULL AND
            NEW.marker_confidence IS NOT NULL AND NEW.marker_method IS NOT NULL
        )
    )
    OR NOT (
        (
            NEW.position_lat IS NULL AND NEW.position_lon IS NULL AND
            NEW.position_method IS NULL AND NEW.position_confidence IS NULL AND
            NEW.position_error_m IS NULL AND NEW.position_observed_at IS NULL
        ) OR (
            NEW.position_lat IS NOT NULL AND NEW.position_lon IS NOT NULL AND
            NEW.position_method IN (
                'multi_anchor_affine','one_anchor_zoom_rung'
            ) AND
            NEW.position_confidence IS NOT NULL AND
            NEW.position_error_m IS NOT NULL AND NEW.position_error_m <= 500 AND
            NEW.position_observed_at IS NOT NULL AND
            NEW.pixel_x IS NOT NULL AND NEW.pixel_y IS NOT NULL AND
            NEW.marker_confidence IS NOT NULL AND NEW.marker_method IS NOT NULL
        )
    )
BEGIN
    SELECT RAISE(ABORT, 'aircraft spatial fields violate the v0.1 contract');
END;
-- Dedup: prevent the run-53/run-67 N999ZY-style double-inserts. Partial index so
-- it only fires when a registration is actually set (NULL/empty rows are valid
-- and shouldn't collide). The recover-tails script and rlsm_extractors both
-- INSERT under this constraint; conflicts surface as sqlite3.IntegrityError.
CREATE UNIQUE INDEX IF NOT EXISTS ix_air_dedup
    ON aircraft_observations(screenshot_id, registration, source_zone)
    WHERE registration IS NOT NULL AND TRIM(registration) != '';

-- One terminal marker decision per screenshot and detector version.  This is
-- the 100%-accounting table: selected, ambiguous, missing, unreadable and
-- no-marker frames all receive a row.  Candidate geometry is stored separately
-- so a fail-closed decision never destroys the alternatives that produced it.
CREATE TABLE IF NOT EXISTS aircraft_marker_frames (
    marker_frame_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    screenshot_id        INTEGER NOT NULL REFERENCES screenshots(screenshot_id),
    run_id               INTEGER REFERENCES processing_runs(run_id),
    detector_version     TEXT NOT NULL,
    status               TEXT NOT NULL CHECK (status IN (
        'selected','ambiguous_candidates','ambiguous_observation',
        'no_marker','missing_source','unreadable'
    )),
    candidate_count      INTEGER NOT NULL DEFAULT 0 CHECK (candidate_count >= 0),
    selected_candidate_rank INTEGER,
    viewport_x           INTEGER,
    viewport_y           INTEGER,
    viewport_w           INTEGER,
    viewport_h           INTEGER,
    reason               TEXT,
    observed_at          TEXT NOT NULL,
    CHECK (status != 'selected' OR (
        candidate_count >= 1 AND selected_candidate_rank >= 1
    )),
    CHECK (status = 'selected' OR selected_candidate_rank IS NULL),
    UNIQUE(screenshot_id, detector_version)
);
CREATE INDEX IF NOT EXISTS ix_marker_frame_status
    ON aircraft_marker_frames(status);

CREATE TABLE IF NOT EXISTS aircraft_marker_detections (
    marker_detection_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    marker_frame_id      INTEGER NOT NULL
        REFERENCES aircraft_marker_frames(marker_frame_id) ON DELETE CASCADE,
    screenshot_id        INTEGER NOT NULL REFERENCES screenshots(screenshot_id),
    aircraft_obs_id      INTEGER REFERENCES aircraft_observations(aircraft_obs_id),
    candidate_rank       INTEGER NOT NULL CHECK (candidate_rank >= 1),
    selected             INTEGER NOT NULL DEFAULT 0 CHECK (selected IN (0,1)),
    bbox_x               INTEGER NOT NULL CHECK (bbox_x >= 0),
    bbox_y               INTEGER NOT NULL CHECK (bbox_y >= 0),
    bbox_w               INTEGER NOT NULL CHECK (bbox_w > 0),
    bbox_h               INTEGER NOT NULL CHECK (bbox_h > 0),
    centroid_x           REAL NOT NULL CHECK (centroid_x >= 0),
    centroid_y           REAL NOT NULL CHECK (centroid_y >= 0),
    rotation_deg         REAL CHECK (
        rotation_deg IS NULL OR (rotation_deg >= 0 AND rotation_deg < 360)
    ),
    rotation_status      TEXT NOT NULL CHECK (rotation_status IN (
        'resolved','axis_only','isotropic'
    )),
    area_px              INTEGER NOT NULL CHECK (area_px > 0),
    hue_deg              REAL,
    saturation           REAL,
    value                REAL,
    fill_ratio           REAL,
    axis_ratio           REAL,
    direction_asymmetry  REAL,
    silhouette_hash      TEXT,
    confidence           REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    features_json        TEXT NOT NULL,
    observed_at          TEXT NOT NULL,
    CHECK (
        (selected = 1 AND aircraft_obs_id IS NOT NULL) OR
        (selected = 0 AND aircraft_obs_id IS NULL)
    ),
    UNIQUE(marker_frame_id, candidate_rank)
);
CREATE INDEX IF NOT EXISTS ix_marker_detection_screenshot
    ON aircraft_marker_detections(screenshot_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_marker_selected_per_frame
    ON aircraft_marker_detections(marker_frame_id)
    WHERE selected = 1;

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
CREATE TABLE IF NOT EXISTS labeled_pins (
    pin_id           INTEGER PRIMARY KEY AUTOINCREMENT,
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
    pin_type_guess   TEXT,                                  -- 'city'|'airport'|'water'|'mountain'|'highway'|'neighborhood'|'unknown'
    confidence       REAL,
    review_status    TEXT NOT NULL DEFAULT 'unreviewed',
    observed_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_lpin_screenshot ON labeled_pins(screenshot_id);
CREATE INDEX IF NOT EXISTS ix_lpin_normalized ON labeled_pins(normalized_label);

-- Unlabeled POI candidates (visual features WITHOUT labels). Separate table by design.
CREATE TABLE IF NOT EXISTS unlabeled_pin_candidates (
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
CREATE INDEX IF NOT EXISTS ix_upin_screenshot ON unlabeled_pin_candidates(screenshot_id);
CREATE INDEX IF NOT EXISTS ix_upin_type       ON unlabeled_pin_candidates(candidate_type);

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

-- Persisted screenshot transforms.  Unlike the legacy geocoder's in-memory
-- dictionary, these rows preserve the scale, residual, anchor count and exact
-- evidence used to locate (or deliberately not locate) a frame.
CREATE TABLE IF NOT EXISTS screenshot_georeferences (
    georef_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    screenshot_id        INTEGER NOT NULL REFERENCES screenshots(screenshot_id),
    run_id               INTEGER REFERENCES processing_runs(run_id),
    georef_version       TEXT NOT NULL,
    status               TEXT NOT NULL CHECK (status IN (
        'located','unclassified','rejected_residual','rejected_geometry'
    )),
    method               TEXT NOT NULL CHECK (method IN (
        'multi_anchor_affine','one_anchor_zoom_rung','unclassified'
    )),
    viewport_profile     TEXT NOT NULL,
    viewport_x           INTEGER NOT NULL CHECK (viewport_x >= 0),
    viewport_y           INTEGER NOT NULL CHECK (viewport_y >= 0),
    viewport_w           INTEGER NOT NULL CHECK (viewport_w > 0),
    viewport_h           INTEGER NOT NULL CHECK (viewport_h > 0),
    anchor_count         INTEGER NOT NULL DEFAULT 0 CHECK (anchor_count >= 0),
    lon0                 REAL,
    dlon_dx              REAL,
    lat0                 REAL,
    dlat_dy              REAL,
    scale_x_m_per_px     REAL CHECK (
        scale_x_m_per_px IS NULL OR scale_x_m_per_px > 0
    ),
    scale_y_m_per_px     REAL CHECK (
        scale_y_m_per_px IS NULL OR scale_y_m_per_px > 0
    ),
    scale_m_per_px       REAL CHECK (
        scale_m_per_px IS NULL OR scale_m_per_px > 0
    ),
    scale_axis_disagreement REAL CHECK (
        scale_axis_disagreement IS NULL OR scale_axis_disagreement >= 0
    ),
    fit_residual_m       REAL CHECK (
        fit_residual_m IS NULL OR fit_residual_m >= 0
    ),
    zoom_rung            INTEGER,
    zoom_support         INTEGER CHECK (zoom_support IS NULL OR zoom_support > 0),
    confidence           REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    estimated_error_m    REAL CHECK (
        estimated_error_m IS NULL OR estimated_error_m >= 0
    ),
    evidence_json        TEXT NOT NULL,
    observed_at          TEXT NOT NULL,
    CHECK (method != 'multi_anchor_affine' OR anchor_count >= 2),
    CHECK (method != 'one_anchor_zoom_rung' OR (
        status = 'located' AND anchor_count = 1 AND zoom_rung IS NOT NULL
    )),
    CHECK (status != 'located' OR (
        method IN ('multi_anchor_affine','one_anchor_zoom_rung') AND
        lon0 IS NOT NULL AND dlon_dx IS NOT NULL AND
        lat0 IS NOT NULL AND dlat_dy IS NOT NULL AND
        dlon_dx > 0 AND dlat_dy < 0 AND
        scale_m_per_px IS NOT NULL AND scale_m_per_px > 0 AND
        estimated_error_m IS NOT NULL AND estimated_error_m <= 500
    )),
    UNIQUE(screenshot_id, georef_version)
);
CREATE INDEX IF NOT EXISTS ix_georef_status
    ON screenshot_georeferences(status, method);
CREATE INDEX IF NOT EXISTS ix_georef_zoom
    ON screenshot_georeferences(viewport_profile, zoom_rung);

-- A self-calibrated, relative ladder.  Rung numbers are intentionally local to
-- one viewport profile; they are not asserted to be FR24's private absolute
-- zoom identifier.  Only rungs with enough independent multi-anchor support
-- may be used for one-anchor recovery.
CREATE TABLE IF NOT EXISTS zoom_ladder_rungs (
    georef_version       TEXT NOT NULL,
    viewport_profile     TEXT NOT NULL,
    zoom_rung            INTEGER NOT NULL,
    scale_m_per_px       REAL NOT NULL CHECK (scale_m_per_px > 0),
    dlon_dx              REAL NOT NULL CHECK (dlon_dx > 0),
    dlat_dy              REAL NOT NULL CHECK (dlat_dy < 0),
    support_count        INTEGER NOT NULL CHECK (support_count > 0),
    dispersion_log2      REAL NOT NULL CHECK (dispersion_log2 >= 0),
    eligible_for_transfer INTEGER NOT NULL CHECK (eligible_for_transfer IN (0,1)),
    evidence_json        TEXT NOT NULL,
    observed_at          TEXT NOT NULL,
    CHECK (eligible_for_transfer = 0 OR support_count >= 3),
    PRIMARY KEY(georef_version, viewport_profile, zoom_rung)
);

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
    item_kind        TEXT NOT NULL,                         -- 'labeled_pin_low_conf'|'unlabeled_candidate'|'aircraft_identity_conflict'|'time_conflict'|'geo_anchor_fail'|'ocr_low_conf'
    item_ref_table   TEXT,
    item_ref_id      INTEGER,
    reason           TEXT,
    severity         TEXT,                                  -- 'low'|'medium'|'high'
    review_status    TEXT NOT NULL DEFAULT 'unreviewed',
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_review_kind   ON manual_review_queue(item_kind);
CREATE INDEX IF NOT EXISTS ix_review_status ON manual_review_queue(review_status);

-- FR24 map icons detected beside labeled pins (fr24/rlsm_icons.py).
-- The glyph FR24 draws next to a map label — airport, heliport, aircraft,
-- navaid, city dot. Cropped from the original RGB at a fixed offset from the
-- pin's text box, so it exists only because labeled_pins carries real geometry.
-- pin_id is nullable: a standalone glyph with no adjacent readable text still
-- types the feature ("heliport here") without reading a character.
-- ahash/cluster_id/icon_class carry the cluster-first review workflow: identical
-- UI glyphs hash identically across renders, so the operator names each cluster
-- once (scripts/rlsm_icon_cluster.py) and every recurrence inherits the type.
CREATE TABLE IF NOT EXISTS icon_observations (
    icon_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    screenshot_id  INTEGER NOT NULL REFERENCES screenshots(screenshot_id),
    pin_id         INTEGER REFERENCES labeled_pins(pin_id),
    run_id         INTEGER REFERENCES processing_runs(run_id),
    bbox_x         INTEGER,
    bbox_y         INTEGER,
    bbox_w         INTEGER,
    bbox_h         INTEGER,
    centroid_x     INTEGER,
    centroid_y     INTEGER,
    area_px        INTEGER,
    aspect         REAL,
    fill_ratio     REAL,
    hue_deg        REAL,                                   -- circular mean, 0-360
    saturation     REAL,                                   -- 0-1
    value          REAL,                                   -- 0-1
    ahash          TEXT,                                   -- 64-bit average hash, 16 hex chars
    anchor_side    TEXT,                                   -- 'left'|'right': which side of the label the glyph was found on
    cluster_id     INTEGER,
    icon_class     TEXT,
    confidence     REAL,
    review_status  TEXT NOT NULL DEFAULT 'unreviewed',
    observed_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_icon_screenshot ON icon_observations(screenshot_id);
CREATE INDEX IF NOT EXISTS ix_icon_pin        ON icon_observations(pin_id);
CREATE INDEX IF NOT EXISTS ix_icon_ahash      ON icon_observations(ahash);
CREATE INDEX IF NOT EXISTS ix_icon_cluster    ON icon_observations(cluster_id);
