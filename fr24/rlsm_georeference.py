"""Persisted, evidence-gated screenshot and aircraft georeferencing.

The legacy unlabeled-feature geocoder computed per-frame affine fits in memory
and discarded their scale.  This module makes each fit an auditable database
record, derives a relative zoom ladder from trustworthy multi-anchor fits, and
uses a rung for one-anchor recovery only when an independent near-duplicate
frame supplies that zoom evidence.

No scale is guessed.  Static projected anchors are excluded, unsupported rungs
remain unclassified, and no aircraft position is promoted above the 500 metre
``located`` ceiling.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import time
from collections import defaultdict
from pathlib import Path
from statistics import median

from fr24.rlsm_aircraft_markers import map_viewport
from fr24.rlsm_anchors import anchors_for_screenshot, build_geo_lookup
from fr24.rlsm_spatial_schema import ensure_spatial_schema
from integration.geo_calibration import apply_affine, fit_affine

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
PLACES = REPO / "data" / "places.geojson"
GEOREF_VERSION = "rlsm-spatial-georef-v1"
MAX_LOCATED_ERROR_M = 500.0
MIN_AFFINE_ERROR_M = 50.0
MAX_AXIS_DISAGREEMENT = 0.35
ZOOM_LOG2_TOLERANCE = 0.18
MIN_RUNG_SUPPORT = 3
EARTH_DEG_M = 111_000.0


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def viewport_profile(width: int, height: int) -> tuple[str, tuple[int, int, int, int]]:
    viewport = map_viewport(width, height)
    x, y, w, h = viewport
    return f"{width}x{height}:{x},{y},{w},{h}", viewport


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Small-distance metric suitable for fit residuals over Puerto Rico."""
    mean_lat = math.radians((lat1 + lat2) / 2.0)
    dy = (lat2 - lat1) * EARTH_DEG_M
    dx = (lon2 - lon1) * EARTH_DEG_M * math.cos(mean_lat)
    return math.hypot(dx, dy)


def affine_scale_metrics(
    affine: tuple[float, float, float, float], center_lat: float
) -> tuple[float, float, float, float]:
    """Return x-scale, y-scale, median scale and normalized disagreement."""
    _, dlon_dx, _, dlat_dy = affine
    scale_x = abs(dlon_dx) * EARTH_DEG_M * math.cos(math.radians(center_lat))
    scale_y = abs(dlat_dy) * EARTH_DEG_M
    combined = median((scale_x, scale_y))
    disagreement = abs(scale_x - scale_y) / max(combined, 1e-9)
    return scale_x, scale_y, combined, disagreement


def fit_screenshot(
    anchors: list[tuple[float, float, float, float]],
    viewport: tuple[int, int, int, int],
) -> dict:
    """Fit and adjudicate a north-up, axis-aligned per-screenshot transform."""
    pixel_xy = [(a[0], a[1]) for a in anchors]
    geo_latlon = [(a[2], a[3]) for a in anchors]
    affine = fit_affine(pixel_xy, geo_latlon)
    if affine is None:
        return {"status": "rejected_geometry", "reason": "degenerate anchor spread"}
    lon0, dlon_dx, lat0, dlat_dy = affine
    if dlon_dx <= 0 or dlat_dy >= 0:
        return {
            "status": "rejected_geometry",
            "reason": "fit violates the north-up axis convention",
            "affine": affine,
        }
    residuals = []
    for (px, py), (lat, lon) in zip(pixel_xy, geo_latlon, strict=True):
        estimated_lat, estimated_lon = apply_affine(affine, px, py)
        residuals.append(distance_m(estimated_lat, estimated_lon, lat, lon))
    residual_m = float(median(residuals))
    x, y, w, h = viewport
    center_lat = lat0 + dlat_dy * (y + h / 2.0)

    # A map transform is physically invalid if extrapolating it to the viewport
    # center leaves the terrestrial latitude domain. Reject before scale
    # conversion so cos(latitude) can never turn metric x-scale negative.
    if (
        not math.isfinite(float(center_lat))
        or float(center_lat) < -90.0
        or float(center_lat) > 90.0
    ):
        return {
            "status": "rejected_geometry",
            "reason": (
                "viewport-center latitude outside physical range: "
                f"{center_lat!r}"
            ),
            "affine": affine,
            "residual_m": residual_m,
        }

    scale_x, scale_y, scale, disagreement = affine_scale_metrics(
        affine, center_lat
    )

    # Fail closed on numerically invalid scale geometry. The database contract
    # requires every persisted scale to be finite and strictly positive.
    scale_values = (scale_x, scale_y, scale)
    if any(
        not math.isfinite(float(value)) or float(value) <= 0.0
        for value in scale_values
    ):
        return {
            "status": "rejected_geometry",
            "reason": (
                "non-finite or non-positive affine scale: "
                f"x={scale_x!r}, y={scale_y!r}, combined={scale!r}"
            ),
            "affine": affine,
            "residual_m": residual_m,
        }

    if disagreement > MAX_AXIS_DISAGREEMENT:
        return {
            "status": "rejected_geometry",
            "reason": f"axis scale disagreement {disagreement:.3f} exceeds ceiling",
            "affine": affine,
            "residual_m": residual_m,
            "scale_x": scale_x,
            "scale_y": scale_y,
            "scale": scale,
            "disagreement": disagreement,
        }
    error_m = max(MIN_AFFINE_ERROR_M, residual_m)
    if error_m <= 150.0:
        confidence = 0.90
    elif error_m <= MAX_LOCATED_ERROR_M:
        confidence = 0.82
    else:
        confidence = 0.70
    return {
        "status": "located" if error_m <= MAX_LOCATED_ERROR_M else "rejected_residual",
        "reason": "fit accepted" if error_m <= MAX_LOCATED_ERROR_M else "fit exceeds 500 m",
        "affine": affine,
        "residual_m": residual_m,
        "scale_x": scale_x,
        "scale_y": scale_y,
        "scale": scale,
        "disagreement": disagreement,
        "error_m": error_m,
        "confidence": confidence,
    }


def derive_zoom_rungs(records: list[dict]) -> tuple[list[dict], list[int]]:
    """Derive power-of-two relative rungs from fitted scale observations.

    The densest local scale cluster becomes rung zero.  Every other observation
    must sit within ``ZOOM_LOG2_TOLERANCE`` of an integer log2 step from that
    reference; outliers are returned unassigned instead of being forced onto a
    ladder.
    """
    if not records:
        return [], []
    def evidence_key(row: dict) -> str:
        return str(
            row.get("evidence_group")
            or f"screenshot:{int(row['screenshot_id'])}"
        )

    logs = sorted(
        (
            math.log2(float(row["scale"])),
            int(row["screenshot_id"]),
            evidence_key(row),
        )
        for row in records
    )

    def independent_log_centers(
        members: list[tuple[float, int, str]],
    ) -> list[float]:
        grouped: dict[str, list[float]] = defaultdict(list)
        for log_scale, _screenshot_id, group in members:
            grouped[group].append(log_scale)
        return [float(median(values)) for values in grouped.values()]

    seed_clusters: list[list[tuple[float, int, str]]] = []
    for item in logs:
        placed = False
        for cluster in seed_clusters:
            if (
                abs(item[0] - median(independent_log_centers(cluster)))
                <= ZOOM_LOG2_TOLERANCE
            ):
                cluster.append(item)
                placed = True
                break
        if not placed:
            seed_clusters.append([item])

    seed = sorted(
        seed_clusters,
        key=lambda cluster: (
            -len(independent_log_centers(cluster)),
            median(independent_log_centers(cluster)),
        ),
    )[0]
    reference_log = float(median(independent_log_centers(seed)))
    by_rung: dict[int, list[dict]] = defaultdict(list)
    unassigned: list[int] = []
    for row in records:
        log_scale = math.log2(float(row["scale"]))
        rung = round(log_scale - reference_log)
        if abs(log_scale - (reference_log + rung)) > ZOOM_LOG2_TOLERANCE:
            unassigned.append(int(row["screenshot_id"]))
            continue
        by_rung[int(rung)].append(row)

    rungs: list[dict] = []
    for rung, members in sorted(by_rung.items()):
        by_evidence: dict[str, list[dict]] = defaultdict(list)
        for row in members:
            by_evidence[evidence_key(row)].append(row)
        group_logs = [
            float(median(math.log2(float(row["scale"])) for row in group))
            for group in by_evidence.values()
        ]
        group_dlon = [
            float(median(float(row["dlon_dx"]) for row in group))
            for group in by_evidence.values()
        ]
        group_dlat = [
            float(median(float(row["dlat_dy"]) for row in group))
            for group in by_evidence.values()
        ]
        log_center = float(median(group_logs))
        dispersion = float(median(abs(value - log_center) for value in group_logs))
        support = len(by_evidence)
        rungs.append(
            {
                "zoom_rung": rung,
                "scale_m_per_px": 2 ** log_center,
                "dlon_dx": float(median(group_dlon)),
                "dlat_dy": float(median(group_dlat)),
                "support_count": support,
                "dispersion_log2": dispersion,
                "eligible_for_transfer": int(support >= MIN_RUNG_SUPPORT),
                "screenshot_ids": sorted(int(row["screenshot_id"]) for row in members),
                "evidence_groups": sorted(by_evidence),
            }
        )
    return rungs, sorted(unassigned)


def _upsert_georef(conn: sqlite3.Connection, row: dict) -> None:
    fields = [
        "screenshot_id", "run_id", "georef_version", "status", "method",
        "viewport_profile", "viewport_x", "viewport_y", "viewport_w", "viewport_h",
        "anchor_count", "lon0", "dlon_dx", "lat0", "dlat_dy", "scale_x_m_per_px",
        "scale_y_m_per_px", "scale_m_per_px", "scale_axis_disagreement",
        "fit_residual_m", "zoom_rung", "zoom_support", "confidence",
        "estimated_error_m", "evidence_json", "observed_at",
    ]
    placeholders = ",".join("?" for _ in fields)
    updates = ",".join(f"{field}=excluded.{field}" for field in fields if field != "screenshot_id")
    conn.execute(
        f"INSERT INTO screenshot_georeferences ({','.join(fields)}) "
        f"VALUES ({placeholders}) ON CONFLICT(screenshot_id, georef_version) "
        f"DO UPDATE SET {updates}",
        [row.get(field) for field in fields],
    )


def _initial_georeferences(
    conn: sqlite3.Connection,
    run_id: int,
    places_geojson: Path,
) -> dict[int, list[tuple[float, float, float, float]]]:
    geo_lookup = build_geo_lookup(conn, places_geojson=places_geojson)
    anchors_by_sid: dict[int, list[tuple[float, float, float, float]]] = {}
    targets = conn.execute(
        """SELECT s.screenshot_id, s.width, s.height
           FROM screenshots s
           WHERE EXISTS (
               SELECT 1 FROM aircraft_observations a
               WHERE a.screenshot_id=s.screenshot_id
           )
           ORDER BY s.screenshot_id"""
    ).fetchall()
    for screenshot_id, width, height in targets:
        anchors = anchors_for_screenshot(
            conn, int(screenshot_id), geo_lookup, include_static_projected=False
        )
        anchors_by_sid[int(screenshot_id)] = anchors
        now = _iso_now()
        evidence = {
            "anchor_count": len(anchors),
            "anchor_pixels": [[a[0], a[1]] for a in anchors],
            "static_projected_anchors_excluded": True,
        }
        if not width or not height:
            _upsert_georef(
                conn,
                {
                    "screenshot_id": screenshot_id,
                    "run_id": run_id,
                    "georef_version": GEOREF_VERSION,
                    "status": "rejected_geometry",
                    "method": "unclassified",
                    "viewport_profile": "unknown",
                    "viewport_x": 0,
                    "viewport_y": 0,
                    "viewport_w": 1,
                    "viewport_h": 1,
                    "anchor_count": len(anchors),
                    "confidence": 0.0,
                    "evidence_json": json.dumps(
                        {**evidence, "reason": "missing screenshot dimensions"}, sort_keys=True
                    ),
                    "observed_at": now,
                },
            )
            continue
        profile, viewport = viewport_profile(int(width), int(height))
        vx, vy, vw, vh = viewport
        base = {
            "screenshot_id": screenshot_id,
            "run_id": run_id,
            "georef_version": GEOREF_VERSION,
            "viewport_profile": profile,
            "viewport_x": vx,
            "viewport_y": vy,
            "viewport_w": vw,
            "viewport_h": vh,
            "anchor_count": len(anchors),
            "observed_at": now,
        }
        if len(anchors) < 2:
            _upsert_georef(
                conn,
                {
                    **base,
                    "status": "unclassified",
                    "method": "unclassified",
                    "confidence": 0.30 if anchors else 0.0,
                    "evidence_json": json.dumps(
                        {**evidence, "reason": "fewer than two measured anchors"}, sort_keys=True
                    ),
                },
            )
            continue
        result = fit_screenshot(anchors, viewport)
        affine = result.get("affine") or (None, None, None, None)
        _upsert_georef(
            conn,
            {
                **base,
                "status": result["status"],
                "method": "multi_anchor_affine",
                "lon0": affine[0],
                "dlon_dx": affine[1],
                "lat0": affine[2],
                "dlat_dy": affine[3],
                "scale_x_m_per_px": result.get("scale_x"),
                "scale_y_m_per_px": result.get("scale_y"),
                "scale_m_per_px": result.get("scale"),
                "scale_axis_disagreement": result.get("disagreement"),
                "fit_residual_m": result.get("residual_m"),
                "confidence": result.get("confidence", 0.0),
                "estimated_error_m": result.get("error_m"),
                "evidence_json": json.dumps(
                    {**evidence, "reason": result["reason"]}, sort_keys=True
                ),
            },
        )
    return anchors_by_sid


def _persist_ladders(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    conn.execute("DELETE FROM zoom_ladder_rungs WHERE georef_version=?", (GEOREF_VERSION,))
    conn.execute(
        "UPDATE screenshot_georeferences SET zoom_rung=NULL, zoom_support=NULL "
        "WHERE georef_version=?",
        (GEOREF_VERSION,),
    )
    rows = conn.execute(
        """SELECT g.screenshot_id, g.viewport_profile, g.scale_m_per_px,
                  g.dlon_dx, g.dlat_dy, s.near_dup_group_id
           FROM screenshot_georeferences g
           JOIN screenshots s USING(screenshot_id)
           WHERE g.georef_version=? AND g.status='located'
             AND g.method='multi_anchor_affine' AND g.scale_m_per_px IS NOT NULL""",
        (GEOREF_VERSION,),
    ).fetchall()
    by_profile: dict[str, list[dict]] = defaultdict(list)
    for screenshot_id, profile, scale, dlon_dx, dlat_dy, near_dup_group_id in rows:
        by_profile[str(profile)].append(
            {
                "screenshot_id": int(screenshot_id),
                "scale": float(scale),
                "dlon_dx": float(dlon_dx),
                "dlat_dy": float(dlat_dy),
                "evidence_group": (
                    f"near_dup:{near_dup_group_id}"
                    if near_dup_group_id is not None
                    else f"screenshot:{int(screenshot_id)}"
                ),
            }
        )

    all_rungs: dict[str, list[dict]] = {}
    now = _iso_now()
    for profile, records in sorted(by_profile.items()):
        rungs, unassigned = derive_zoom_rungs(records)
        all_rungs[profile] = rungs
        for rung in rungs:
            evidence = {
                "relative_not_absolute": True,
                "screenshot_ids": rung["screenshot_ids"],
                "independent_evidence_groups": rung["evidence_groups"],
                "unassigned_scale_screenshot_ids": unassigned,
                "log2_tolerance": ZOOM_LOG2_TOLERANCE,
                "minimum_transfer_support": MIN_RUNG_SUPPORT,
            }
            conn.execute(
                """INSERT INTO zoom_ladder_rungs
                   (georef_version, viewport_profile, zoom_rung, scale_m_per_px,
                    dlon_dx, dlat_dy, support_count, dispersion_log2,
                    eligible_for_transfer, evidence_json, observed_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    GEOREF_VERSION,
                    profile,
                    rung["zoom_rung"],
                    rung["scale_m_per_px"],
                    rung["dlon_dx"],
                    rung["dlat_dy"],
                    rung["support_count"],
                    rung["dispersion_log2"],
                    rung["eligible_for_transfer"],
                    json.dumps(evidence, sort_keys=True),
                    now,
                ),
            )
            if rung["eligible_for_transfer"]:
                for screenshot_id in rung["screenshot_ids"]:
                    conn.execute(
                        """UPDATE screenshot_georeferences
                           SET zoom_rung=?, zoom_support=?
                           WHERE screenshot_id=? AND georef_version=?""",
                        (
                            rung["zoom_rung"],
                            rung["support_count"],
                            screenshot_id,
                            GEOREF_VERSION,
                        ),
                    )
    return all_rungs


def _recover_one_anchor(
    conn: sqlite3.Connection,
    anchors_by_sid: dict[int, list[tuple[float, float, float, float]]],
) -> int:
    recovered = 0
    pending = conn.execute(
        """SELECT g.screenshot_id, g.viewport_profile, g.viewport_x, g.viewport_y,
                  g.viewport_w, g.viewport_h, s.near_dup_group_id
           FROM screenshot_georeferences g
           JOIN screenshots s USING(screenshot_id)
           WHERE g.georef_version=? AND g.status='unclassified'
             AND g.anchor_count=1 AND s.near_dup_group_id IS NOT NULL
           ORDER BY g.screenshot_id""",
        (GEOREF_VERSION,),
    ).fetchall()
    for screenshot_id, profile, _vx, _vy, vw, vh, near_group in pending:
        sources = conn.execute(
            """SELECT g.screenshot_id, g.zoom_rung, g.estimated_error_m,
                      r.dlon_dx, r.dlat_dy, r.scale_m_per_px,
                      r.dispersion_log2, r.support_count
               FROM screenshots s
               JOIN screenshot_georeferences g USING(screenshot_id)
               JOIN zoom_ladder_rungs r
                 ON r.georef_version=g.georef_version
                AND r.viewport_profile=g.viewport_profile
                AND r.zoom_rung=g.zoom_rung
               WHERE s.near_dup_group_id=? AND g.screenshot_id != ?
                 AND g.georef_version=? AND g.viewport_profile=?
                 AND g.status='located' AND g.method='multi_anchor_affine'
                 AND r.eligible_for_transfer=1
               ORDER BY g.confidence DESC, g.estimated_error_m ASC, g.screenshot_id""",
            (near_group, screenshot_id, GEOREF_VERSION, profile),
        ).fetchall()
        if not sources:
            continue
        source_sid, rung, source_error, dlon_dx, dlat_dy, scale, dispersion, support = sources[0]
        anchor = anchors_by_sid[int(screenshot_id)][0]
        px, py, lat, lon = anchor
        lon0 = lon - float(dlon_dx) * px
        lat0 = lat - float(dlat_dy) * py
        scale_x, scale_y, recovered_scale, disagreement = affine_scale_metrics(
            (lon0, float(dlon_dx), lat0, float(dlat_dy)),
            float(lat),
        )
        relative_scale_error = max(0.0, 2 ** float(dispersion) - 1.0)
        ladder_error = math.hypot(float(vw), float(vh)) * float(scale) * relative_scale_error
        error_m = max(100.0, float(source_error or 0.0) + ladder_error)
        if error_m > MAX_LOCATED_ERROR_M:
            continue
        confidence = 0.82 if error_m <= 150.0 else 0.70
        evidence = {
            "anchor": [px, py, lat, lon],
            "independent_zoom_evidence": "near_dup_group",
            "near_dup_group_id": near_group,
            "source_screenshot_id": int(source_sid),
            "zoom_rung": int(rung),
            "zoom_support": int(support),
            "static_projected_anchors_excluded": True,
        }
        conn.execute(
            """UPDATE screenshot_georeferences
               SET status='located', method='one_anchor_zoom_rung', lon0=?, dlon_dx=?,
                   lat0=?, dlat_dy=?, scale_x_m_per_px=?, scale_y_m_per_px=?,
                   scale_m_per_px=?, scale_axis_disagreement=?, zoom_rung=?,
                   zoom_support=?, confidence=?, estimated_error_m=?,
                   evidence_json=?, observed_at=?
               WHERE screenshot_id=? AND georef_version=?""",
            (
                lon0,
                dlon_dx,
                lat0,
                dlat_dy,
                scale_x,
                scale_y,
                recovered_scale,
                disagreement,
                rung,
                support,
                confidence,
                error_m,
                json.dumps(evidence, sort_keys=True),
                _iso_now(),
                screenshot_id,
                GEOREF_VERSION,
            ),
        )
        recovered += 1
    return recovered


def project_aircraft_positions(conn: sqlite3.Connection) -> int:
    """Project selected marker centroids through accepted transforms."""
    conn.execute(
        """UPDATE aircraft_observations
           SET position_lat=NULL, position_lon=NULL, position_method=NULL,
               position_confidence=NULL, position_error_m=NULL,
               position_observed_at=NULL
           WHERE position_method IN ('multi_anchor_affine','one_anchor_zoom_rung')"""
    )
    rows = conn.execute(
        """SELECT a.aircraft_obs_id, a.pixel_x, a.pixel_y, a.marker_confidence,
                  g.lon0, g.dlon_dx, g.lat0, g.dlat_dy, g.method,
                  g.confidence, g.estimated_error_m, g.scale_m_per_px,
                  d.bbox_w, d.bbox_h
           FROM aircraft_observations a
           JOIN screenshot_georeferences g USING(screenshot_id)
           JOIN aircraft_marker_detections d
             ON d.aircraft_obs_id=a.aircraft_obs_id AND d.selected=1
           JOIN aircraft_marker_frames f
             ON f.marker_frame_id=d.marker_frame_id
            AND f.screenshot_id=a.screenshot_id
            AND d.screenshot_id=a.screenshot_id
            AND f.status='selected' AND f.detector_version=a.marker_method
           WHERE a.pixel_x IS NOT NULL AND a.pixel_y IS NOT NULL
             AND g.georef_version=? AND g.status='located'
             AND g.estimated_error_m <= ?""",
        (GEOREF_VERSION, MAX_LOCATED_ERROR_M),
    ).fetchall()
    projected = 0
    now = _iso_now()
    for row in rows:
        (
            obs_id,
            px,
            py,
            marker_conf,
            lon0,
            dlon_dx,
            lat0,
            dlat_dy,
            method,
            georef_conf,
            georef_error,
            scale,
            bbox_w,
            bbox_h,
        ) = row
        affine = (float(lon0), float(dlon_dx), float(lat0), float(dlat_dy))
        lat, lon = apply_affine(affine, float(px), float(py))
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            continue
        extent = max(float(bbox_w or 0), float(bbox_h or 0))
        if extent:
            pixel_uncertainty = 1.0 + (1.0 - float(marker_conf or 0.0)) * min(
                extent / 2.0, 4.0
            )
        else:
            pixel_uncertainty = 2.0
        marker_error = pixel_uncertainty * float(scale or 0.0)
        error_m = math.hypot(float(georef_error or 0.0), marker_error)
        if error_m > MAX_LOCATED_ERROR_M:
            continue
        confidence = min(float(marker_conf or 0.0), float(georef_conf or 0.0))
        conn.execute(
            """UPDATE aircraft_observations
               SET position_lat=?, position_lon=?, position_method=?,
                   position_confidence=?, position_error_m=?, position_observed_at=?
               WHERE aircraft_obs_id=?""",
            (lat, lon, method, confidence, error_m, now, obs_id),
        )
        projected += 1
    return projected


def load_persisted_affines(
    conn: sqlite3.Connection, georef_version: str = GEOREF_VERSION
) -> dict[int, tuple[float, float, float, float]]:
    """Return only accepted, bounded-error transforms for downstream tools."""
    rows = conn.execute(
        """SELECT screenshot_id, lon0, dlon_dx, lat0, dlat_dy
           FROM screenshot_georeferences
           WHERE georef_version=? AND status='located'
             AND estimated_error_m <= ?
             AND lon0 IS NOT NULL AND dlon_dx IS NOT NULL
             AND lat0 IS NOT NULL AND dlat_dy IS NOT NULL""",
        (georef_version, MAX_LOCATED_ERROR_M),
    ).fetchall()
    return {
        int(row[0]): (float(row[1]), float(row[2]), float(row[3]), float(row[4]))
        for row in rows
    }


def run(db_path: Path = DB, places_geojson: Path = PLACES) -> dict:
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 60000")
    ensure_spatial_schema(conn)
    target_count = conn.execute(
        "SELECT COUNT(DISTINCT screenshot_id) FROM aircraft_observations"
    ).fetchone()[0]
    cursor = conn.execute(
        """INSERT INTO processing_runs
           (run_kind, started_at, status, n_inputs, n_processed, n_failed, notes)
           VALUES ('screenshot_georeference', ?, 'in_progress', ?, 0, 0, ?)""",
        (_iso_now(), target_count, json.dumps({"georef_version": GEOREF_VERSION})),
    )
    run_id = int(cursor.lastrowid)
    conn.commit()
    try:
        anchors_by_sid = _initial_georeferences(conn, run_id, places_geojson)
        ladders = _persist_ladders(conn)
        one_anchor_recovered = _recover_one_anchor(conn, anchors_by_sid)
        projected = project_aircraft_positions(conn)
        statuses = {
            status: count
            for status, count in conn.execute(
                """SELECT status, COUNT(*) FROM screenshot_georeferences
                   WHERE georef_version=?
                     AND EXISTS (
                         SELECT 1 FROM aircraft_observations a
                         WHERE a.screenshot_id=screenshot_georeferences.screenshot_id
                     )
                   GROUP BY status""",
                (GEOREF_VERSION,),
            )
        }
        rung_count = sum(len(rungs) for rungs in ladders.values())
        processed = sum(statuses.values())
        if processed != target_count:
            raise RuntimeError(
                f"georeference accounting mismatch: {processed} decisions for "
                f"{target_count} target frames"
            )
        notes = {
            "georef_version": GEOREF_VERSION,
            "statuses": statuses,
            "zoom_rungs": rung_count,
            "one_anchor_recovered": one_anchor_recovered,
            "aircraft_positions_projected": projected,
        }
        conn.execute(
            """UPDATE processing_runs SET ended_at=?, status='completed',
                      n_processed=?, n_failed=0, notes=? WHERE run_id=?""",
            (_iso_now(), processed, json.dumps(notes, sort_keys=True), run_id),
        )
        conn.commit()
        return {"run_id": run_id, "targets": target_count, **notes}
    except Exception:
        conn.rollback()
        conn.execute(
            """UPDATE processing_runs SET ended_at=?, status='failed', n_failed=1
               WHERE run_id=?""",
            (_iso_now(), run_id),
        )
        conn.commit()
        raise
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Persist RLSM screenshot georeferences.")
    parser.add_argument("--db", type=Path, default=DB)
    parser.add_argument("--places-geojson", type=Path, default=PLACES)
    args = parser.parse_args()
    print(json.dumps(run(args.db, args.places_geojson), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
