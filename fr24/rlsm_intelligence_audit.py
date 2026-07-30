"""Certify the RLSM screenshot-intelligence pipeline against corpus and gold data."""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
import unicodedata
from pathlib import Path
from typing import Any, Iterable

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
CORPUS = REPO / "data" / "FR24_baseline"
GOLD = REPO / "data" / "rlsm" / "gold_sample_300.jsonl"
OUT_JSON = REPO / "outputs" / "screenshot_intelligence_audit.json"
OUT_MD = REPO / "outputs" / "screenshot_intelligence_audit.md"
OUT_CAPABILITIES = REPO / "outputs" / "screenshot_intelligence_capability_matrix.json"
OUT_ERRORS = REPO / "outputs" / "screenshot_intelligence_errors.jsonl"
OUT_SAMPLE = REPO / "outputs" / "screenshot_intelligence_structured_sample.jsonl"

IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".heic", ".heif", ".webp",
    ".tif", ".tiff", ".bmp",
}

REQUIRED_GATES = (
    "screenshot_accounting_100",
    "no_silent_failures",
    "frame_accounting_100",
    "icon_capture_complete",
    "no_unsupported_geolocation",
    "field_level_provenance_100",
    "location_label_recall_gte_0_98",
)


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _count(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> int:
    return int(conn.execute(sql, params).fetchone()[0])


def _pct(numerator: int, denominator: int) -> float:
    return round(100.0 * numerator / denominator, 3) if denominator else 100.0


def normalize_label(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(
        "".join(char if char.isalnum() else " " for char in value.casefold()).split()
    )


def bbox_iou(a: Iterable[float] | None, b: Iterable[float] | None) -> float | None:
    if a is None or b is None:
        return None
    av, bv = list(a), list(b)
    if len(av) != 4 or len(bv) != 4:
        return None
    ax, ay, aw, ah = map(float, av)
    bx, by, bw, bh = map(float, bv)
    if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
        return None
    ix0, iy0 = max(ax, bx), max(ay, by)
    ix1, iy1 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    intersection = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    union = aw * ah + bw * bh - intersection
    return intersection / union if union > 0 else 0.0


def _disk_manifest(corpus_root: Path) -> dict[str, Path]:
    if not corpus_root.exists():
        return {}
    manifest: dict[str, Path] = {}
    for path in sorted(corpus_root.rglob("*")):
        if not path.is_file() or path.suffix.casefold() not in IMAGE_EXTENSIONS:
            continue
        try:
            rel = path.resolve().relative_to(REPO.resolve()).as_posix()
        except ValueError:
            rel = path.relative_to(corpus_root).as_posix()
        manifest[rel] = path
    return manifest


def _db_screenshots(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    fields = (
        "screenshot_id", "sha256", "filename", "rel_path", "ingest_status",
        "ingest_error", "ocr_status", "width", "height",
    )
    return [
        dict(zip(fields, row, strict=True))
        for row in conn.execute(
            """SELECT screenshot_id, sha256, filename, rel_path, ingest_status,
                      ingest_error, ocr_status, width, height
               FROM screenshots ORDER BY screenshot_id"""
        )
    ]


def audit_accounting(conn: sqlite3.Connection, corpus_root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    disk = _disk_manifest(corpus_root)
    rows = _db_screenshots(conn)
    db_paths = {str(row["rel_path"]): row for row in rows}
    unregistered = sorted(set(disk) - set(db_paths))
    missing_on_disk = sorted(
        rel_path for rel_path in db_paths
        if rel_path not in disk and "_missing/" not in rel_path
    )
    explicit_missing = sorted(
        str(row["rel_path"]) for row in rows
        if row["ingest_status"] != "ok" or "_missing/" in str(row["rel_path"])
    )
    duplicate_paths = _count(
        conn,
        """SELECT COUNT(*) FROM (
               SELECT rel_path FROM screenshots GROUP BY rel_path HAVING COUNT(*) > 1
           )""",
    )
    duplicate_sha_rows = _count(
        conn,
        """SELECT COALESCE(SUM(n - 1), 0) FROM (
               SELECT COUNT(*) n FROM screenshots GROUP BY sha256 HAVING COUNT(*) > 1
           )""",
    )
    complete = not unregistered and not missing_on_disk and duplicate_paths == 0
    errors = [
        {"kind": "disk_file_absent_from_database", "severity": "high", "rel_path": path}
        for path in unregistered
    ]
    errors.extend(
        {"kind": "database_file_absent_from_disk", "severity": "high", "rel_path": path}
        for path in missing_on_disk
    )
    return ({
        "corpus_root": corpus_root.as_posix(),
        "disk_images": len(disk),
        "database_rows": len(rows),
        "registered_disk_images": len(disk) - len(unregistered),
        "disk_files_absent_from_database": len(unregistered),
        "database_files_absent_from_disk": len(missing_on_disk),
        "explicit_missing_or_failed_rows": len(explicit_missing),
        "duplicate_rel_paths": duplicate_paths,
        "duplicate_sha_rows": duplicate_sha_rows,
        "coverage_percent": _pct(len(disk) - len(unregistered), len(disk)),
        "complete": complete,
        "unregistered_sample": unregistered[:25],
        "missing_on_disk_sample": missing_on_disk[:25],
        "explicit_missing_sample": explicit_missing[:25],
    }, errors)


def audit_ocr_integrity(conn: sqlite3.Connection) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    ingest_ok = _count(conn, "SELECT COUNT(*) FROM screenshots WHERE ingest_status='ok'")
    with_receipts = _count(
        conn,
        """SELECT COUNT(DISTINCT s.screenshot_id)
           FROM screenshots s JOIN ocr_observations o USING(screenshot_id)
           WHERE s.ingest_status='ok'""",
    )
    missing_receipts = conn.execute(
        """SELECT s.screenshot_id, s.rel_path, s.ocr_status
           FROM screenshots s
           WHERE s.ingest_status='ok'
             AND NOT EXISTS (SELECT 1 FROM ocr_observations o WHERE o.screenshot_id=s.screenshot_id)
           ORDER BY s.screenshot_id"""
    ).fetchall()
    failed_without_error = conn.execute(
        """SELECT obs_id, screenshot_id, zone FROM ocr_observations
           WHERE ocr_status='failed' AND COALESCE(TRIM(ocr_error), '')=''
           ORDER BY obs_id"""
    ).fetchall()
    ok_with_latest_failure = conn.execute(
        """WITH latest AS (
               SELECT o.* FROM ocr_observations o
               WHERE o.obs_id IN (SELECT MAX(obs_id) FROM ocr_observations GROUP BY screenshot_id, zone)
           )
           SELECT s.screenshot_id, s.rel_path, COUNT(*) failed_zones
           FROM screenshots s JOIN latest o USING(screenshot_id)
           WHERE s.ocr_status='ok' AND o.ocr_status='failed'
           GROUP BY s.screenshot_id, s.rel_path ORDER BY s.screenshot_id"""
    ).fetchall()
    partial_without_failure = conn.execute(
        """WITH latest AS (
               SELECT o.* FROM ocr_observations o
               WHERE o.obs_id IN (SELECT MAX(obs_id) FROM ocr_observations GROUP BY screenshot_id, zone)
           )
           SELECT s.screenshot_id, s.rel_path FROM screenshots s
           WHERE s.ocr_status='partial'
             AND NOT EXISTS (SELECT 1 FROM latest o WHERE o.screenshot_id=s.screenshot_id AND o.ocr_status='failed')
           ORDER BY s.screenshot_id"""
    ).fetchall()
    incomplete_completed_runs = conn.execute(
        """SELECT run_id, run_kind, n_inputs, n_processed, n_failed
           FROM processing_runs
           WHERE status='completed'
             AND COALESCE(n_inputs,0) > COALESCE(n_processed,0)+COALESCE(n_failed,0)
           ORDER BY run_id"""
    ).fetchall()
    in_progress_runs = conn.execute(
        "SELECT run_id, run_kind, started_at FROM processing_runs WHERE status='in_progress' ORDER BY run_id"
    ).fetchall()
    strict_runs = _count(conn, "SELECT COUNT(*) FROM processing_runs WHERE run_kind='ocr_strict_parallel'")
    errors: list[dict[str, Any]] = []
    errors.extend({"kind": "missing_ocr_receipt", "severity": "high", "screenshot_id": r[0], "rel_path": r[1], "ocr_status": r[2]} for r in missing_receipts)
    errors.extend({"kind": "failed_ocr_without_error", "severity": "high", "obs_id": r[0], "screenshot_id": r[1], "zone": r[2]} for r in failed_without_error)
    errors.extend({"kind": "screenshot_marked_ok_with_failed_zone", "severity": "high", "screenshot_id": r[0], "rel_path": r[1], "failed_zones": r[2]} for r in ok_with_latest_failure)
    errors.extend({"kind": "partial_status_without_failed_zone", "severity": "medium", "screenshot_id": r[0], "rel_path": r[1]} for r in partial_without_failure)
    errors.extend({"kind": "completed_run_with_unaccounted_inputs", "severity": "high", "run_id": r[0], "run_kind": r[1], "n_inputs": r[2], "n_processed": r[3], "n_failed": r[4]} for r in incomplete_completed_runs)
    errors.extend({"kind": "processing_run_left_in_progress", "severity": "medium", "run_id": r[0], "run_kind": r[1], "started_at": r[2]} for r in in_progress_runs)
    silent_failure_count = len(missing_receipts)+len(failed_without_error)+len(ok_with_latest_failure)+len(partial_without_failure)+len(incomplete_completed_runs)
    status_counts = dict(conn.execute("SELECT ocr_status, COUNT(*) FROM screenshots GROUP BY ocr_status").fetchall())
    return ({
        "ingest_ok_screenshots": ingest_ok,
        "screenshots_with_ocr_receipts": with_receipts,
        "receipt_coverage_percent": _pct(with_receipts, ingest_ok),
        "screenshot_status_counts": status_counts,
        "strict_runner_runs": strict_runs,
        "missing_receipts": len(missing_receipts),
        "failed_observations_without_error": len(failed_without_error),
        "ok_screenshots_with_failed_latest_zone": len(ok_with_latest_failure),
        "partial_screenshots_without_failed_latest_zone": len(partial_without_failure),
        "completed_runs_with_unaccounted_inputs": len(incomplete_completed_runs),
        "runs_left_in_progress": len(in_progress_runs),
        "silent_failure_count": silent_failure_count,
        "complete": silent_failure_count == 0,
    }, errors)


def _optional_count(conn: sqlite3.Connection, table: str, where: str = "") -> int:
    return _count(conn, f"SELECT COUNT(*) FROM {table} {where}") if _table_exists(conn, table) else 0


def audit_capabilities(conn: sqlite3.Connection) -> dict[str, Any]:
    ingest_ok = _count(conn, "SELECT COUNT(*) FROM screenshots WHERE ingest_status='ok'")
    frame_rows = _optional_count(conn, "frame_observations")
    map_rows = _optional_count(conn, "map_state_observations")
    gui_rows = _optional_count(conn, "gui_artifact_observations")
    icons = _optional_count(conn, "icon_observations")
    icon_artifacts = _optional_count(conn, "icon_artifacts")
    icon_failures = _optional_count(conn, "icon_artifacts", "WHERE capture_status!='ok'")
    tracks = _optional_count(conn, "flight_track_features")
    cv_tracks = _optional_count(conn, "flight_track_features", "WHERE bbox_x IS NOT NULL AND confidence>=0.6")
    labels = _optional_count(conn, "labeled_pins")
    aircraft = _optional_count(conn, "aircraft_observations")
    unlabeled = _optional_count(conn, "unlabeled_pin_candidates")
    geo_anchors = _optional_count(conn, "geo_anchors")
    provenance_fields = _optional_count(conn, "extraction_field_provenance")
    return {
        "ingestion": {"status": "implemented", "screenshots": ingest_ok},
        "ocr_text_labels": {"status": "implemented_unverified" if labels else "implemented_no_output", "labeled_pins": labels},
        "unlabeled_visual_candidates": {"status": "optional_operator_run" if unlabeled == 0 else "implemented", "candidates": unlabeled},
        "aircraft_metadata": {"status": "implemented_unverified" if aircraft else "implemented_no_output", "observations": aircraft},
        "flight_path": {"status": "implemented_unverified" if tracks else "implemented_no_output", "observations": tracks, "pixel_derived": cv_tracks, "heuristic_or_absent": max(0, tracks-cv_tracks)},
        "frame_classification": {"status": "implemented" if frame_rows else "operator_run_required", "rows": frame_rows, "coverage_percent": _pct(frame_rows, ingest_ok)},
        "map_state": {"status": "layout_only_no_geolocation" if map_rows else "operator_run_required", "rows": map_rows},
        "gui_artifacts": {"status": "implemented" if gui_rows else "operator_run_required", "rows": gui_rows},
        "icons": {"status": "captured_with_failures" if icon_failures else "captured" if icons and icon_artifacts == icons else "detection_only" if icons else "implemented_no_output", "detected": icons, "artifacts": icon_artifacts, "artifact_failures": icon_failures},
        "georeferencing": {"status": "anchors_only_unverified" if geo_anchors else "unsupported", "anchors": geo_anchors},
        "field_provenance": {"status": "implemented" if provenance_fields else "operator_run_required", "fields": provenance_fields},
    }


CORE_PROVENANCE_FIELDS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "labeled_pin": ("labeled_pins", "pin_id", ("raw_label","normalized_label","bbox_x","bbox_y","bbox_w","bbox_h","confidence")),
    "aircraft_observation": ("aircraft_observations", "aircraft_obs_id", ("registration","callsign","aircraft_type","altitude_ft","speed_kt","heading_deg","operator_text","identity_status","confidence")),
    "flight_track_feature": ("flight_track_features", "track_feat_id", ("path_shape","has_loop","has_orbit","has_hover","has_gap","track_length_px","bbox_x","bbox_y","bbox_w","bbox_h","confidence")),
    "icon_observation": ("icon_observations", "icon_id", ("bbox_x","bbox_y","bbox_w","bbox_h","ahash","cluster_id","icon_class","confidence")),
    "frame_observation": ("frame_observations", "frame_obs_id", ("frame_type","provider","orientation","confidence")),
    "map_state": ("map_state_observations", "map_state_id", ("viewport_x","viewport_y","viewport_w","viewport_h","center_lat","center_lon","zoom","bearing_deg","extent_geojson","geolocation_status","confidence")),
    "gui_artifact": ("gui_artifact_observations", "gui_artifact_id", ("artifact_type","bbox_x","bbox_y","bbox_w","bbox_h","raw_text","extraction_status","confidence")),
    "icon_artifact": ("icon_artifacts", "icon_artifact_id", ("source_sha256","crop_rel_path","crop_sha256","capture_status","capture_error")),
}


def audit_provenance(conn: sqlite3.Connection) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not _table_exists(conn, "extraction_field_provenance"):
        return ({"expected_non_null_core_fields": 0, "provenanced_core_fields": 0, "missing_core_fields": 0, "coverage_percent": 0.0, "complete": False, "status": "table_missing"}, [{"kind": "field_provenance_table_missing", "severity": "high"}])
    expected = missing = 0
    by_object: dict[str, dict[str, int]] = {}
    errors: list[dict[str, Any]] = []
    for object_type, (table, primary_key, fields) in CORE_PROVENANCE_FIELDS.items():
        if not _table_exists(conn, table):
            continue
        columns = {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}
        object_expected = object_missing = 0
        for field in fields:
            if field not in columns:
                continue
            field_expected = _count(conn, f"SELECT COUNT(*) FROM {table} WHERE {field} IS NOT NULL")
            field_missing = _count(conn, f"""SELECT COUNT(*) FROM {table} t
                WHERE t.{field} IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM extraction_field_provenance p
                    WHERE p.object_type=? AND p.object_id=t.{primary_key} AND p.field_name=?
                )""", (object_type, field))
            object_expected += field_expected
            object_missing += field_missing
            if field_missing:
                errors.append({"kind": "missing_field_provenance", "severity": "high", "object_type": object_type, "field_name": field, "missing_count": field_missing})
        expected += object_expected
        missing += object_missing
        by_object[object_type] = {"expected": object_expected, "missing": object_missing, "provenanced": object_expected-object_missing}
    return ({"expected_non_null_core_fields": expected, "provenanced_core_fields": expected-missing, "missing_core_fields": missing, "coverage_percent": _pct(expected-missing, expected) if expected else 0.0, "complete": expected > 0 and missing == 0, "by_object_type": by_object}, errors)


def audit_geolocation(conn: sqlite3.Connection) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not _table_exists(conn, "map_state_observations"):
        return ({"map_state_rows": 0, "unsupported_rows_with_coordinates": 0, "complete": False, "status": "table_missing"}, [{"kind": "map_state_table_missing", "severity": "high"}])
    rows = conn.execute(
        """SELECT map_state_id, screenshot_id, center_lat, center_lon, extent_geojson
           FROM map_state_observations
           WHERE geolocation_status='unsupported'
             AND (center_lat IS NOT NULL OR center_lon IS NOT NULL OR extent_geojson IS NOT NULL)
           ORDER BY map_state_id"""
    ).fetchall()
    errors = [{"kind": "unsupported_geolocation_has_coordinates", "severity": "critical", "map_state_id": r[0], "screenshot_id": r[1], "center_lat": r[2], "center_lon": r[3], "extent_geojson": r[4]} for r in rows]
    return ({"map_state_rows": _count(conn, "SELECT COUNT(*) FROM map_state_observations"), "unsupported_rows_with_coordinates": len(rows), "complete": len(rows) == 0}, errors)


def _load_gold(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if path.suffix.casefold() == ".jsonl":
        rows: list[dict[str, Any]] = []
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL line {line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"gold line {line_number} is not an object")
            rows.append(value)
        return rows
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError("gold JSON must be an array of objects")
    return list(value)


def _resolve_gold_screenshot(conn: sqlite3.Connection, row: dict[str, Any]) -> tuple[int, str] | None:
    if row.get("screenshot_id") is not None:
        found = conn.execute("SELECT screenshot_id, sha256 FROM screenshots WHERE screenshot_id=?", (row["screenshot_id"],)).fetchone()
    elif row.get("screenshot_sha256"):
        found = conn.execute("SELECT screenshot_id, sha256 FROM screenshots WHERE sha256=?", (row["screenshot_sha256"],)).fetchone()
    elif row.get("filename"):
        found = conn.execute("SELECT screenshot_id, sha256 FROM screenshots WHERE filename=? ORDER BY screenshot_id LIMIT 1", (row["filename"],)).fetchone()
    else:
        return None
    return (int(found[0]), str(found[1])) if found else None


def _label_values(items: Any) -> set[str]:
    if not isinstance(items, list):
        return set()
    values = set()
    for item in items:
        text = item if isinstance(item, str) else str(item.get("text") or item.get("label") or "") if isinstance(item, dict) else ""
        normalized = normalize_label(text)
        if normalized:
            values.add(normalized)
    return values


def _safe_ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def evaluate_gold(conn: sqlite3.Connection, gold_path: Path, expected_size: int = 300) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = []
    try:
        rows = _load_gold(gold_path)
    except ValueError as exc:
        return ({"path": gold_path.as_posix(), "status": "invalid", "records": 0, "expected_records": expected_size, "error": str(exc)}, [{"kind": "gold_sample_invalid", "severity": "high", "error": str(exc)}])
    if not rows:
        return ({"path": gold_path.as_posix(), "status": "missing", "records": 0, "expected_records": expected_size, "label_metrics": None}, [{"kind": "gold_sample_missing", "severity": "high", "path": gold_path.as_posix()}])
    tp = fp = fn = resolved = unresolved = 0
    frame_correct = frame_total = track_correct = track_total = 0
    aircraft_correct = aircraft_total = 0
    label_iou_values: list[float] = []
    for index, gold_row in enumerate(rows):
        resolved_row = _resolve_gold_screenshot(conn, gold_row)
        if resolved_row is None:
            unresolved += 1
            errors.append({"kind": "gold_screenshot_unresolved", "severity": "high", "gold_index": index, "identity": {k: gold_row.get(k) for k in ("screenshot_id","screenshot_sha256","filename") if gold_row.get(k) is not None}})
            continue
        resolved += 1
        sid, _sha = resolved_row
        expected_labels = _label_values(gold_row.get("labels"))
        predicted_rows = conn.execute("SELECT normalized_label, bbox_x, bbox_y, bbox_w, bbox_h FROM labeled_pins WHERE screenshot_id=?", (sid,)).fetchall()
        predicted_labels = {normalize_label(str(row[0] or "")) for row in predicted_rows if normalize_label(str(row[0] or ""))}
        tp += len(expected_labels & predicted_labels)
        fp += len(predicted_labels - expected_labels)
        fn += len(expected_labels - predicted_labels)
        expected_by_text = {normalize_label(str(item.get("text") or item.get("label") or "")): item for item in gold_row.get("labels", []) if isinstance(item, dict)}
        for predicted in predicted_rows:
            expected_item = expected_by_text.get(normalize_label(str(predicted[0] or "")))
            if expected_item and expected_item.get("bbox") is not None:
                iou = bbox_iou(expected_item["bbox"], predicted[1:5])
                if iou is not None:
                    label_iou_values.append(iou)
        expected_frame = gold_row.get("frame_type")
        if expected_frame is not None and _table_exists(conn, "frame_observations"):
            predicted = conn.execute("SELECT frame_type FROM frame_observations WHERE screenshot_id=? ORDER BY frame_obs_id DESC LIMIT 1", (sid,)).fetchone()
            frame_total += 1
            frame_correct += int(bool(predicted and predicted[0] == expected_frame))
        expected_track = gold_row.get("track")
        if isinstance(expected_track, dict) and expected_track.get("path_shape") is not None:
            predicted = conn.execute("SELECT path_shape FROM flight_track_features WHERE screenshot_id=? ORDER BY track_feat_id DESC LIMIT 1", (sid,)).fetchone()
            track_total += 1
            track_correct += int(bool(predicted and predicted[0] == expected_track["path_shape"]))
        expected_aircraft = gold_row.get("aircraft")
        if isinstance(expected_aircraft, dict):
            predicted = conn.execute("SELECT registration, callsign, aircraft_type, altitude_ft, speed_kt, heading_deg, operator_text FROM aircraft_observations WHERE screenshot_id=? ORDER BY aircraft_obs_id DESC LIMIT 1", (sid,)).fetchone()
            for field_index, field in enumerate(("registration","callsign","aircraft_type","altitude_ft","speed_kt","heading_deg","operator")):
                if field not in expected_aircraft:
                    continue
                aircraft_total += 1
                predicted_value = predicted[field_index] if predicted else None
                aircraft_correct += int(str(predicted_value or "").casefold() == str(expected_aircraft[field] or "").casefold())
    precision, recall = _safe_ratio(tp, tp+fp), _safe_ratio(tp, tp+fn)
    f1 = 2*precision*recall/(precision+recall) if precision is not None and recall is not None and precision+recall else None
    status = "ready" if len(rows) == expected_size and unresolved == 0 else "incomplete"
    metrics = {
        "path": gold_path.as_posix(), "status": status, "records": len(rows),
        "expected_records": expected_size, "resolved_records": resolved,
        "unresolved_records": unresolved,
        "label_metrics": {"true_positive": tp, "false_positive": fp, "false_negative": fn, "precision": round(precision,6) if precision is not None else None, "recall": round(recall,6) if recall is not None else None, "f1": round(f1,6) if f1 is not None else None, "mean_bbox_iou": round(sum(label_iou_values)/len(label_iou_values),6) if label_iou_values else None},
        "frame_accuracy": round(frame_correct/frame_total,6) if frame_total else None,
        "track_shape_accuracy": round(track_correct/track_total,6) if track_total else None,
        "aircraft_field_accuracy": round(aircraft_correct/aircraft_total,6) if aircraft_total else None,
    }
    if len(rows) != expected_size:
        errors.append({"kind": "gold_sample_wrong_size", "severity": "high", "records": len(rows), "expected": expected_size})
    return metrics, errors


def build_structured_sample(conn: sqlite3.Connection, path: Path, limit: int = 25) -> int:
    rows = conn.execute("SELECT screenshot_id, sha256, filename, rel_path, filename_ts, width, height, ingest_status, ocr_status FROM screenshots ORDER BY screenshot_id LIMIT ?", (max(0, limit),)).fetchall()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            sid = int(row[0])
            record: dict[str, Any] = {"screenshot_id": sid, "sha256": row[1], "filename": row[2], "rel_path": row[3], "filename_ts": row[4], "width": row[5], "height": row[6], "ingest_status": row[7], "ocr_status": row[8]}
            record["labels"] = [{"pin_id": i[0], "raw_label": i[1], "normalized_label": i[2], "bbox": list(i[3:7]), "centroid": list(i[7:9]), "pin_type": i[9], "confidence": i[10]} for i in conn.execute("SELECT pin_id, raw_label, normalized_label, bbox_x, bbox_y, bbox_w, bbox_h, centroid_x, centroid_y, pin_type_guess, confidence FROM labeled_pins WHERE screenshot_id=? ORDER BY pin_id", (sid,))]
            record["aircraft"] = [{"aircraft_obs_id": i[0], "registration": i[1], "callsign": i[2], "aircraft_type": i[3], "altitude_ft": i[4], "speed_kt": i[5], "heading_deg": i[6], "operator": i[7], "identity_status": i[8], "confidence": i[9]} for i in conn.execute("SELECT aircraft_obs_id, registration, callsign, aircraft_type, altitude_ft, speed_kt, heading_deg, operator_text, identity_status, confidence FROM aircraft_observations WHERE screenshot_id=? ORDER BY aircraft_obs_id", (sid,))]
            record["tracks"] = [{"track_feat_id": i[0], "path_shape": i[1], "has_loop": i[2], "has_orbit": i[3], "has_hover": i[4], "has_gap": i[5], "track_length_px": i[6], "bbox": list(i[7:11]), "confidence": i[11]} for i in conn.execute("SELECT track_feat_id, path_shape, has_loop, has_orbit, has_hover, has_gap, track_length_px, bbox_x, bbox_y, bbox_w, bbox_h, confidence FROM flight_track_features WHERE screenshot_id=? ORDER BY track_feat_id", (sid,))]
            if _table_exists(conn, "frame_observations"):
                value = conn.execute("SELECT frame_type, provider, orientation, confidence, review_status FROM frame_observations WHERE screenshot_id=? ORDER BY frame_obs_id DESC LIMIT 1", (sid,)).fetchone()
                record["frame"] = list(value) if value else None
            if _table_exists(conn, "map_state_observations"):
                value = conn.execute("SELECT viewport_x, viewport_y, viewport_w, viewport_h, center_lat, center_lon, zoom, bearing_deg, geolocation_status, confidence FROM map_state_observations WHERE screenshot_id=? ORDER BY map_state_id DESC LIMIT 1", (sid,)).fetchone()
                record["map_state"] = list(value) if value else None
            if _table_exists(conn, "icon_observations"):
                record["icons"] = [{"icon_id": i[0], "pin_id": i[1], "bbox": list(i[2:6]), "cluster_id": i[6], "icon_class": i[7], "confidence": i[8]} for i in conn.execute("SELECT icon_id, pin_id, bbox_x, bbox_y, bbox_w, bbox_h, cluster_id, icon_class, confidence FROM icon_observations WHERE screenshot_id=? ORDER BY icon_id", (sid,))]
            if _table_exists(conn, "gui_artifact_observations"):
                record["gui_artifacts"] = [{"gui_artifact_id": i[0], "artifact_type": i[1], "bbox": list(i[2:6]), "raw_text": i[6], "confidence": i[7], "extraction_status": i[8]} for i in conn.execute("SELECT gui_artifact_id, artifact_type, bbox_x, bbox_y, bbox_w, bbox_h, raw_text, confidence, extraction_status FROM gui_artifact_observations WHERE screenshot_id=? ORDER BY gui_artifact_id", (sid,))]
            handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False)+"\n")
    return len(rows)


def _gate(status: str, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"status": status, "evidence": evidence}


def build_gates(accounting: dict[str, Any], ocr: dict[str, Any], capabilities: dict[str, Any], geolocation: dict[str, Any], provenance: dict[str, Any], gold: dict[str, Any]) -> dict[str, dict[str, Any]]:
    frame_complete = capabilities["frame_classification"]["rows"] == capabilities["ingestion"]["screenshots"]
    icons = capabilities["icons"]
    icon_complete = icons["detected"] > 0 and icons["detected"] == icons["artifacts"] and icons["artifact_failures"] == 0
    label_recall = (gold.get("label_metrics") or {}).get("recall")
    label_gate = "PASS" if gold.get("status") == "ready" and label_recall is not None and label_recall >= 0.98 else "FAIL" if gold.get("status") == "ready" else "BLOCKED"
    return {
        "screenshot_accounting_100": _gate("PASS" if accounting["complete"] else "FAIL", {"coverage_percent": accounting["coverage_percent"], "unregistered": accounting["disk_files_absent_from_database"], "missing_on_disk": accounting["database_files_absent_from_disk"]}),
        "no_silent_failures": _gate("PASS" if ocr["complete"] else "FAIL", {"silent_failure_count": ocr["silent_failure_count"]}),
        "frame_accounting_100": _gate("PASS" if frame_complete else "FAIL", {"frame_rows": capabilities["frame_classification"]["rows"], "ingest_ok": capabilities["ingestion"]["screenshots"]}),
        "icon_capture_complete": _gate("PASS" if icon_complete else "FAIL", {"detected": icons["detected"], "artifacts": icons["artifacts"], "failures": icons["artifact_failures"]}),
        "no_unsupported_geolocation": _gate("PASS" if geolocation["complete"] else "FAIL", {"violations": geolocation["unsupported_rows_with_coordinates"]}),
        "field_level_provenance_100": _gate("PASS" if provenance["complete"] else "FAIL", {"coverage_percent": provenance["coverage_percent"], "missing_core_fields": provenance["missing_core_fields"]}),
        "location_label_recall_gte_0_98": _gate(label_gate, {"gold_status": gold.get("status"), "records": gold.get("records"), "recall": label_recall}),
    }


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False)+"\n", encoding="utf-8")


def _write_errors(path: Path, errors: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for error in errors:
            handle.write(json.dumps(error, sort_keys=True, ensure_ascii=False)+"\n")


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Skywatcher Screenshot Intelligence Audit", "",
        f"- Generated: `{report['generated_at']}`",
        f"- Certification: **{report['certification_status']}**",
        f"- Database: `{report['inputs']['database']}`",
        f"- Corpus: `{report['inputs']['corpus_root']}`",
        f"- Gold sample: `{report['inputs']['gold_sample']}`", "",
        "## Required gates", "", "| Gate | Status | Evidence |", "|---|---:|---|",
    ]
    for name in REQUIRED_GATES:
        gate = report["gates"][name]
        lines.append(f"| `{name}` | **{gate['status']}** | `{json.dumps(gate['evidence'], sort_keys=True)}` |")
    lines.extend(["", "## Coverage", "",
        f"- Disk images: **{report['accounting']['disk_images']:,}**",
        f"- Database screenshot rows: **{report['accounting']['database_rows']:,}**",
        f"- OCR receipt coverage: **{report['ocr_integrity']['receipt_coverage_percent']:.3f}%**",
        f"- Labeled pins: **{report['capabilities']['ocr_text_labels']['labeled_pins']:,}**",
        f"- Aircraft observations: **{report['capabilities']['aircraft_metadata']['observations']:,}**",
        f"- Flight-track observations: **{report['capabilities']['flight_path']['observations']:,}**",
        f"- Pixel-derived tracks: **{report['capabilities']['flight_path']['pixel_derived']:,}**",
        f"- Detected icons: **{report['capabilities']['icons']['detected']:,}**",
        f"- Captured icon artifacts: **{report['capabilities']['icons']['artifacts']:,}**",
        f"- Frame observations: **{report['capabilities']['frame_classification']['rows']:,}**",
        f"- GUI artifacts: **{report['capabilities']['gui_artifacts']['rows']:,}**",
        f"- Provenanced core fields: **{report['provenance']['provenanced_core_fields']:,} / {report['provenance']['expected_non_null_core_fields']:,}**",
        "", "## Gold sample", "",
        f"- Status: **{report['gold_sample']['status']}**",
        f"- Records: **{report['gold_sample']['records']} / {report['gold_sample']['expected_records']}**",
    ])
    label_metrics = report["gold_sample"].get("label_metrics")
    if label_metrics:
        lines.extend([f"- Label precision: `{label_metrics.get('precision')}`", f"- Label recall: `{label_metrics.get('recall')}`", f"- Label F1: `{label_metrics.get('f1')}`"])
    lines.extend(["", "## Error ledger", "", f"- Total findings: **{report['error_count']:,}**", f"- Machine-readable ledger: `{report['outputs']['errors']}`", "", "A blocked gate is not a pass. The ≥98% label-recall requirement cannot be certified until the 300-frame annotated gold sample is present and fully resolvable.", ""])
    return "\n".join(lines)


def run(*, db_path: Path = DB, corpus_root: Path = CORPUS, gold_path: Path = GOLD, outputs_dir: Path | None = None, sample_limit: int = 25) -> dict[str, Any]:
    if not db_path.exists():
        raise FileNotFoundError(f"RLSM DB not found: {db_path}")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.execute("PRAGMA foreign_keys = ON")
    accounting, accounting_errors = audit_accounting(conn, corpus_root)
    ocr, ocr_errors = audit_ocr_integrity(conn)
    capabilities = audit_capabilities(conn)
    provenance, provenance_errors = audit_provenance(conn)
    geolocation, geolocation_errors = audit_geolocation(conn)
    gold, gold_errors = evaluate_gold(conn, gold_path)
    gates = build_gates(accounting, ocr, capabilities, geolocation, provenance, gold)
    certification = "PASS" if all(gates[name]["status"] == "PASS" for name in REQUIRED_GATES) else "BLOCKED" if any(gates[name]["status"] == "BLOCKED" for name in REQUIRED_GATES) else "FAIL"
    errors = accounting_errors + ocr_errors + provenance_errors + geolocation_errors + gold_errors
    output_base = outputs_dir or (REPO / "outputs")
    paths = {"json": output_base/OUT_JSON.name, "markdown": output_base/OUT_MD.name, "capabilities": output_base/OUT_CAPABILITIES.name, "errors": output_base/OUT_ERRORS.name, "structured_sample": output_base/OUT_SAMPLE.name}
    sample_rows = build_structured_sample(conn, paths["structured_sample"], sample_limit)
    conn.close()
    report = {
        "schema_version": "skywatcher_screenshot_intelligence_audit.v1",
        "generated_at": _iso_now(), "certification_status": certification,
        "inputs": {"database": db_path.as_posix(), "corpus_root": corpus_root.as_posix(), "gold_sample": gold_path.as_posix()},
        "accounting": accounting, "ocr_integrity": ocr, "capabilities": capabilities,
        "provenance": provenance, "geolocation": geolocation, "gold_sample": gold,
        "gates": gates, "error_count": len(errors),
        "outputs": {key: value.as_posix() for key, value in paths.items()},
        "structured_sample_rows": sample_rows,
    }
    _write_json(paths["json"], report)
    _write_json(paths["capabilities"], capabilities)
    _write_errors(paths["errors"], errors)
    paths["markdown"].write_text(_markdown(report), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DB)
    parser.add_argument("--corpus-root", type=Path, default=CORPUS)
    parser.add_argument("--gold", type=Path, default=GOLD)
    parser.add_argument("--outputs-dir", type=Path, default=None)
    parser.add_argument("--sample-limit", type=int, default=25)
    parser.add_argument("--enforce", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = run(db_path=args.db, corpus_root=args.corpus_root, gold_path=args.gold, outputs_dir=args.outputs_dir, sample_limit=args.sample_limit)
    except (FileNotFoundError, sqlite3.DatabaseError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps({"certification_status": report["certification_status"], "gates": report["gates"], "error_count": report["error_count"], "outputs": report["outputs"]}, indent=2, sort_keys=True))
    return 2 if args.enforce and report["certification_status"] != "PASS" else 0


if __name__ == "__main__":
    raise SystemExit(main())
