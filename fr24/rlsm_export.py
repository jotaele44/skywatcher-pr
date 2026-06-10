"""
RLSM CSV/JSONL export.

Writes the 14 deliverable artefacts under outputs/. Idempotent and reproducible:
each export pulls from the SQLite DB and overwrites the target file. The JSONL
mirror of raw OCR (outputs/ocr_raw_by_zone.jsonl) is written append-only by the
OCR runner; this module does not touch it.

CLI:
    python3 -m fr24.rlsm_export
"""
from __future__ import annotations

import csv
import json
import sqlite3
import sys
from pathlib import Path

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
            f.write(json.dumps(dict(zip(fields, r)), sort_keys=True) + "\n")
            n += 1
    return n


def export_all() -> dict:
    conn = sqlite3.connect(DB)
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
               ["poi_id","screenshot_id","filename","raw_label","normalized_label","poi_type_guess","confidence","review_status","observed_at"],
               conn.execute("""
                   SELECT p.poi_id, p.screenshot_id, s.filename,
                          p.raw_label, p.normalized_label, p.poi_type_guess,
                          p.confidence, p.review_status, p.observed_at
                   FROM labeled_pois p JOIN screenshots s USING(screenshot_id)
                   ORDER BY p.screenshot_id, p.poi_id
               """))
    written["ocr_normalized_labels.csv"] = "ok"

    # labeled_pois.csv (canonical)
    _write_csv(OUTS / "labeled_pois.csv",
               ["poi_id","screenshot_id","filename","raw_label","normalized_label",
                "bbox_x","bbox_y","bbox_w","bbox_h","centroid_x","centroid_y",
                "poi_type_guess","confidence","review_status","observed_at"],
               conn.execute("""
                   SELECT p.poi_id, p.screenshot_id, s.filename,
                          p.raw_label, p.normalized_label,
                          p.bbox_x, p.bbox_y, p.bbox_w, p.bbox_h,
                          p.centroid_x, p.centroid_y,
                          p.poi_type_guess, p.confidence, p.review_status, p.observed_at
                   FROM labeled_pois p JOIN screenshots s USING(screenshot_id)
                   ORDER BY p.screenshot_id, p.poi_id
               """))
    written["labeled_pois.csv"] = "ok"

    # unlabeled_poi_candidates.csv
    _write_csv(OUTS / "unlabeled_poi_candidates.csv",
               ["candidate_id","screenshot_id","filename","candidate_type",
                "bbox_x","bbox_y","bbox_w","bbox_h","centroid_x","centroid_y",
                "evidence_features","confidence","review_status","observed_at"],
               conn.execute("""
                   SELECT u.candidate_id, u.screenshot_id, s.filename, u.candidate_type,
                          u.bbox_x, u.bbox_y, u.bbox_w, u.bbox_h, u.centroid_x, u.centroid_y,
                          u.evidence_features, u.confidence, u.review_status, u.observed_at
                   FROM unlabeled_poi_candidates u JOIN screenshots s USING(screenshot_id)
                   ORDER BY u.screenshot_id, u.candidate_id
               """))
    written["unlabeled_poi_candidates.csv"] = "ok"

    # aircraft_observations.csv
    _write_csv(OUTS / "aircraft_observations.csv",
               ["aircraft_obs_id","screenshot_id","filename","filename_ts",
                "registration","callsign","aircraft_type",
                "altitude_ft","speed_kt","heading_deg","operator_text",
                "identity_status","confidence","source_zone","raw_excerpt","observed_at"],
               conn.execute("""
                   SELECT a.aircraft_obs_id, a.screenshot_id, s.filename, s.filename_ts,
                          a.registration, a.callsign, a.aircraft_type,
                          a.altitude_ft, a.speed_kt, a.heading_deg, a.operator_text,
                          a.identity_status, a.confidence, a.source_zone, a.raw_excerpt, a.observed_at
                   FROM aircraft_observations a JOIN screenshots s USING(screenshot_id)
                   ORDER BY a.screenshot_id, a.aircraft_obs_id
               """))
    written["aircraft_observations.csv"] = "ok"

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
        "labeled_poi_low_conf":       "manual_review_labeled_pois.csv",
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
