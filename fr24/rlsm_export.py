"""
RLSM CSV/JSONL export.

Writes 18 generated deliverables under outputs/. Idempotent and reproducible:
each generated export pulls from SQLite and overwrites the target file. The
additional raw OCR mirror (outputs/ocr_raw_by_zone.jsonl) is written append-only
by the OCR runner; this module reports its size but does not touch it.

CLI:
    python3 -m fr24.rlsm_export
"""
from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

from fr24.rlsm_spatial_schema import ensure_spatial_schema

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
OUTS = REPO / "outputs"


def _write_csv(path: Path, fields: list[str], rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        w.writerow(fields)
        for r in rows:
            w.writerow(["" if v is None else v for v in r])


def _write_jsonl(path: Path, fields: list[str], rows) -> int:
    """Write rows as flat JSON-lines (one object per line). Returns the count."""
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w") as f:
        for r in rows:
            f.write(json.dumps(dict(zip(fields, r, strict=False)), sort_keys=True) + "\n")
            n += 1
    return n


def export_all() -> dict:
    conn = sqlite3.connect(DB)
    ensure_spatial_schema(conn)
    written = {}

    # rlsm_ingest_manifest.csv — handled by rlsm_inventory; re-export here for reproducibility
    fields = ["screenshot_id","sha256","filename","rel_path","month_bucket","filename_ts","ext",
              "size_bytes","width","height","phash","dup_group_id","near_dup_group_id",
              "ingest_status","ingest_error","ocr_status","ingested_at"]
    _write_csv(OUTS / "rlsm_ingest_manifest.csv", fields,
               conn.execute(f"SELECT {', '.join(fields)} FROM screenshots ORDER BY rel_path"))
    written["rlsm_ingest_manifest.csv"] = "ok"

    # rlsm_duplicate_report.csv
    _write_csv(OUTS / "rlsm_duplicate_report.csv",
               ["dup_group_id","group_size","sha256","filename","rel_path"],
               conn.execute("""
                   SELECT s.dup_group_id,
                          (SELECT COUNT(*) FROM screenshots s2 WHERE s2.dup_group_id = s.dup_group_id),
                          s.sha256, s.filename, s.rel_path
                   FROM screenshots s
                   WHERE s.dup_group_id IS NOT NULL
                   ORDER BY s.dup_group_id, s.filename
               """))
    written["rlsm_duplicate_report.csv"] = "ok"

    # rlsm_failed_files.csv
    _write_csv(OUTS / "rlsm_failed_files.csv",
               ["screenshot_id","filename","rel_path","ingest_status","ingest_error"],
               conn.execute("""
                   SELECT screenshot_id, filename, rel_path, ingest_status, COALESCE(ingest_error,'')
                   FROM screenshots WHERE ingest_status != 'ok'
                   ORDER BY ingest_status, filename
               """))
    written["rlsm_failed_files.csv"] = "ok"

    # ocr_raw_by_zone.jsonl — append-only by runner. Just note existence.
    jsonl = OUTS / "ocr_raw_by_zone.jsonl"
    written["ocr_raw_by_zone.jsonl"] = "append-only by runner; lines=" + str(
        sum(1 for _ in jsonl.open()) if jsonl.exists() else 0)

    # ocr_failures.jsonl — flat JSONL of every screenshot with ocr_status='failed'
    # so operators can triage OCR failures without a SQL client (T8-70).
    failure_fields = ["screenshot_id", "sha256", "filename", "rel_path",
                      "month_bucket", "filename_ts", "ext", "size_bytes",
                      "ingest_status", "ocr_status", "ingested_at"]
    n_failures = _write_jsonl(
        OUTS / "ocr_failures.jsonl", failure_fields,
        conn.execute(f"""
            SELECT {', '.join(failure_fields)}
            FROM screenshots WHERE ocr_status='failed'
            ORDER BY screenshot_id
        """))
    written["ocr_failures.jsonl"] = f"ok; lines={n_failures}"

    # ocr_normalized_labels.csv — flattened normalized labels with provenance
    _write_csv(OUTS / "ocr_normalized_labels.csv",
               ["pin_id","screenshot_id","filename","raw_label","normalized_label","pin_type_guess","confidence","review_status","observed_at"],
               conn.execute("""
                   SELECT p.pin_id, p.screenshot_id, s.filename,
                          p.raw_label, p.normalized_label, p.pin_type_guess,
                          p.confidence, p.review_status, p.observed_at
                   FROM labeled_pins p JOIN screenshots s USING(screenshot_id)
                   ORDER BY p.screenshot_id, p.pin_id
               """))
    written["ocr_normalized_labels.csv"] = "ok"

    # labeled_pins.csv (canonical)
    _write_csv(OUTS / "labeled_pins.csv",
               ["pin_id","screenshot_id","filename","raw_label","normalized_label",
                "bbox_x","bbox_y","bbox_w","bbox_h","centroid_x","centroid_y",
                "pin_type_guess","confidence","review_status","observed_at"],
               conn.execute("""
                   SELECT p.pin_id, p.screenshot_id, s.filename,
                          p.raw_label, p.normalized_label,
                          p.bbox_x, p.bbox_y, p.bbox_w, p.bbox_h,
                          p.centroid_x, p.centroid_y,
                          p.pin_type_guess, p.confidence, p.review_status, p.observed_at
                   FROM labeled_pins p JOIN screenshots s USING(screenshot_id)
                   ORDER BY p.screenshot_id, p.pin_id
               """))
    written["labeled_pins.csv"] = "ok"

    # unlabeled_pin_candidates.csv
    _write_csv(OUTS / "unlabeled_pin_candidates.csv",
               ["candidate_id","screenshot_id","filename","candidate_type",
                "bbox_x","bbox_y","bbox_w","bbox_h","centroid_x","centroid_y",
                "evidence_features","confidence","review_status","observed_at"],
               conn.execute("""
                   SELECT u.candidate_id, u.screenshot_id, s.filename, u.candidate_type,
                          u.bbox_x, u.bbox_y, u.bbox_w, u.bbox_h, u.centroid_x, u.centroid_y,
                          u.evidence_features, u.confidence, u.review_status, u.observed_at
                   FROM unlabeled_pin_candidates u JOIN screenshots s USING(screenshot_id)
                   ORDER BY u.screenshot_id, u.candidate_id
               """))
    written["unlabeled_pin_candidates.csv"] = "ok"

    # aircraft_observations.csv
    _write_csv(OUTS / "aircraft_observations.csv",
               ["aircraft_obs_id","screenshot_id","filename","filename_ts",
                "registration","callsign","aircraft_type",
                "altitude_ft","speed_kt","heading_deg","operator_text",
                "identity_status","confidence","source_zone","raw_excerpt",
                "pixel_x","pixel_y","icon_rotation_deg","marker_confidence","marker_method",
                "position_lat","position_lon","position_method","position_confidence",
                "position_error_m","position_observed_at","observed_at"],
               conn.execute("""
                   SELECT a.aircraft_obs_id, a.screenshot_id, s.filename, s.filename_ts,
                          a.registration, a.callsign, a.aircraft_type,
                          a.altitude_ft, a.speed_kt, a.heading_deg, a.operator_text,
                          a.identity_status, a.confidence, a.source_zone, a.raw_excerpt,
                          a.pixel_x, a.pixel_y, a.icon_rotation_deg,
                          a.marker_confidence, a.marker_method,
                          a.position_lat, a.position_lon, a.position_method,
                          a.position_confidence, a.position_error_m,
                          a.position_observed_at, a.observed_at
                   FROM aircraft_observations a JOIN screenshots s USING(screenshot_id)
                   ORDER BY a.screenshot_id, a.aircraft_obs_id
               """))
    written["aircraft_observations.csv"] = "ok"

    _write_csv(
        OUTS / "aircraft_marker_frames.csv",
        ["marker_frame_id","screenshot_id","filename","detector_version","status",
         "candidate_count","selected_candidate_rank","viewport_x","viewport_y",
         "viewport_w","viewport_h","reason","observed_at"],
        conn.execute("""
            SELECT f.marker_frame_id, f.screenshot_id, s.filename, f.detector_version,
                   f.status, f.candidate_count, f.selected_candidate_rank,
                   f.viewport_x, f.viewport_y, f.viewport_w, f.viewport_h,
                   f.reason, f.observed_at
            FROM aircraft_marker_frames f JOIN screenshots s USING(screenshot_id)
            ORDER BY f.screenshot_id, f.detector_version
        """),
    )
    written["aircraft_marker_frames.csv"] = "ok"

    _write_csv(
        OUTS / "aircraft_marker_detections.csv",
        ["marker_detection_id","marker_frame_id","screenshot_id","aircraft_obs_id",
         "candidate_rank","selected","bbox_x","bbox_y","bbox_w","bbox_h",
         "centroid_x","centroid_y","rotation_deg","rotation_status","area_px",
         "hue_deg","saturation","value","fill_ratio","axis_ratio",
         "direction_asymmetry","silhouette_hash","confidence","features_json",
         "observed_at"],
        conn.execute("""
            SELECT marker_detection_id, marker_frame_id, screenshot_id, aircraft_obs_id,
                   candidate_rank, selected, bbox_x, bbox_y, bbox_w, bbox_h,
                   centroid_x, centroid_y, rotation_deg, rotation_status, area_px,
                   hue_deg, saturation, value, fill_ratio, axis_ratio,
                   direction_asymmetry, silhouette_hash, confidence, features_json,
                   observed_at
            FROM aircraft_marker_detections
            ORDER BY screenshot_id, candidate_rank
        """),
    )
    written["aircraft_marker_detections.csv"] = "ok"

    _write_csv(
        OUTS / "screenshot_georeferences.csv",
        ["georef_id","screenshot_id","filename","georef_version","status","method",
         "viewport_profile","viewport_x","viewport_y","viewport_w","viewport_h",
         "anchor_count","lon0","dlon_dx","lat0","dlat_dy","scale_x_m_per_px",
         "scale_y_m_per_px","scale_m_per_px","scale_axis_disagreement",
         "fit_residual_m","zoom_rung","zoom_support","confidence",
         "estimated_error_m","evidence_json","observed_at"],
        conn.execute("""
            SELECT g.georef_id, g.screenshot_id, s.filename, g.georef_version,
                   g.status, g.method, g.viewport_profile, g.viewport_x, g.viewport_y,
                   g.viewport_w, g.viewport_h, g.anchor_count, g.lon0, g.dlon_dx,
                   g.lat0, g.dlat_dy, g.scale_x_m_per_px, g.scale_y_m_per_px,
                   g.scale_m_per_px, g.scale_axis_disagreement, g.fit_residual_m,
                   g.zoom_rung, g.zoom_support, g.confidence, g.estimated_error_m,
                   g.evidence_json, g.observed_at
            FROM screenshot_georeferences g JOIN screenshots s USING(screenshot_id)
            ORDER BY g.screenshot_id, g.georef_version
        """),
    )
    written["screenshot_georeferences.csv"] = "ok"

    _write_csv(
        OUTS / "zoom_ladder_rungs.csv",
        ["georef_version","viewport_profile","zoom_rung","scale_m_per_px",
         "dlon_dx","dlat_dy","support_count","dispersion_log2",
         "eligible_for_transfer","evidence_json","observed_at"],
        conn.execute("""
            SELECT georef_version, viewport_profile, zoom_rung, scale_m_per_px,
                   dlon_dx, dlat_dy, support_count, dispersion_log2,
                   eligible_for_transfer, evidence_json, observed_at
            FROM zoom_ladder_rungs
            ORDER BY viewport_profile, zoom_rung
        """),
    )
    written["zoom_ladder_rungs.csv"] = "ok"

    # flight_track_features.csv
    _write_csv(OUTS / "flight_track_features.csv",
               ["track_feat_id","screenshot_id","filename","path_shape","has_loop","has_orbit",
                "has_hover","has_gap","follows_coast","near_airport","track_length_px",
                "bbox_x","bbox_y","bbox_w","bbox_h","confidence","observed_at"],
               conn.execute("""
                   SELECT t.track_feat_id, t.screenshot_id, s.filename, t.path_shape,
                          t.has_loop, t.has_orbit, t.has_hover, t.has_gap,
                          t.follows_coast, t.near_airport, t.track_length_px,
                          t.bbox_x, t.bbox_y, t.bbox_w, t.bbox_h, t.confidence, t.observed_at
                   FROM flight_track_features t JOIN screenshots s USING(screenshot_id)
                   ORDER BY t.screenshot_id, t.track_feat_id
               """))
    written["flight_track_features.csv"] = "ok"

    # Manual review queue CSVs (one per item_kind for the spec)
    review_kinds = {
        "labeled_pin_low_conf":       "manual_review_labeled_pins.csv",
        "unlabeled_candidate":        "manual_review_unlabeled_candidates.csv",
        "aircraft_identity_conflict": "manual_review_aircraft_identity.csv",
        "time_conflict":              "manual_review_time_conflicts.csv",
        "geo_anchor_fail":            "manual_review_geo_anchor_failures.csv",
    }
    for kind, fname in review_kinds.items():
        _write_csv(OUTS / fname,
                   ["review_id","screenshot_id","filename","item_kind","item_ref_table",
                    "item_ref_id","reason","severity","review_status","created_at"],
                   conn.execute("""
                       SELECT r.review_id, r.screenshot_id, s.filename,
                              r.item_kind, r.item_ref_table, r.item_ref_id,
                              r.reason, r.severity, r.review_status, r.created_at
                       FROM manual_review_queue r LEFT JOIN screenshots s USING(screenshot_id)
                       WHERE r.item_kind = ? ORDER BY r.review_id
                   """, (kind,)))
        written[fname] = "ok"

    conn.close()
    return written


def main():
    out = export_all()
    print(json.dumps({"outputs_dir": str(OUTS), "files": out, "n_files": len(out)}, indent=2))


if __name__ == "__main__":
    main()
