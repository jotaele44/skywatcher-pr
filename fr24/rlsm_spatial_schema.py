"""Canonical, idempotent schema migration for RLSM spatial truth.

``data/rlsm/schema.sql`` is authoritative for a new database.  This module is
the matching in-place migration for operator databases that already contain
the 13k-frame corpus and therefore cannot be rebuilt merely to gain columns.
"""
from __future__ import annotations

import sqlite3

AIRCRAFT_SPATIAL_COLUMNS = {
    "pixel_x": "REAL CHECK (pixel_x IS NULL OR pixel_x >= 0)",
    "pixel_y": "REAL CHECK (pixel_y IS NULL OR pixel_y >= 0)",
    "icon_rotation_deg": (
        "REAL CHECK (icon_rotation_deg IS NULL OR "
        "(icon_rotation_deg >= 0 AND icon_rotation_deg < 360))"
    ),
    "marker_confidence": (
        "REAL CHECK (marker_confidence IS NULL OR "
        "(marker_confidence >= 0 AND marker_confidence <= 1))"
    ),
    "marker_method": "TEXT",
    "position_lat": (
        "REAL CHECK (position_lat IS NULL OR (position_lat >= -90 AND position_lat <= 90))"
    ),
    "position_lon": (
        "REAL CHECK (position_lon IS NULL OR "
        "(position_lon >= -180 AND position_lon <= 180))"
    ),
    "position_method": "TEXT",
    "position_confidence": (
        "REAL CHECK (position_confidence IS NULL OR "
        "(position_confidence >= 0 AND position_confidence <= 1))"
    ),
    "position_error_m": (
        "REAL CHECK (position_error_m IS NULL OR position_error_m >= 0)"
    ),
    "position_observed_at": "TEXT",
}


SPATIAL_SCHEMA = """
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
"""


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def ensure_spatial_schema(conn: sqlite3.Connection) -> None:
    """Apply the spatial migration without rewriting existing observations."""
    if not table_exists(conn, "aircraft_observations"):
        raise sqlite3.OperationalError(
            "aircraft_observations is missing; initialize data/rlsm/schema.sql first"
        )
    existing = {
        row[1] for row in conn.execute("PRAGMA table_info(aircraft_observations)")
    }
    for name, declaration in AIRCRAFT_SPATIAL_COLUMNS.items():
        if name not in existing:
            conn.execute(
                f"ALTER TABLE aircraft_observations ADD COLUMN {name} {declaration}"
            )
    conn.executescript(SPATIAL_SCHEMA)
    conn.commit()
