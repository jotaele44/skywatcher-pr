"""
FR24 TEMPORAL WAVE DASHBOARD DATA EXPORTER

Builds a browser-loadable JSON payload from temporal-wave CSV outputs. This is a
read-only visibility layer for the dashboard: it joins wave rows with physics
validator rows, summarizes counts, and preserves candidate-only policy labels.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List

TEMPORAL_DASHBOARD_DATA_VERSION = "fr24_temporal_wave_dashboard_data_v0.1.0"
POLICY = "candidate_only_no_auto_confirmation"

PROHIBITED_LABELS = {
    "confirmed",
    "confirmed_aircraft_event",
    "confirmed_" + "anomaly",
    "confirmed_route",
    "verified_event",
    "validated_aircraft_event",
}


def read_csv(path: Path) -> List[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def read_json(path: Path) -> dict:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _has_prohibited_label(row: dict) -> bool:
    for value in row.values():
        token = str(value or "").strip().lower()
        if token in PROHIBITED_LABELS:
            return True
    return False


def _as_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _as_float(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _normalize_value(value: object) -> object:
    if value in (None, ""):
        return ""
    text = str(value)
    if text in {"0", "1"}:
        return int(text)
    try:
        if "." not in text:
            return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return value


def _normalize_row(row: dict) -> dict:
    numeric_fields = {
        "wave_obs_count",
        "wave_duration_minutes",
        "wave_avg_field_coverage",
        "wave_avg_confidence",
        "wave_temporal_coherence",
        "physics_check_passed",
        "physics_violation_count",
        "physics_checks_run",
        "physics_obs_with_data",
    }
    out = dict(row)
    for key in numeric_fields:
        if key in out:
            out[key] = _normalize_value(out[key])
    out["confirmation_status"] = "not_confirmed"
    out["dashboard_status"] = "temporal_wave_candidate"
    out["temporal_dashboard_data_version"] = TEMPORAL_DASHBOARD_DATA_VERSION
    return out


def _physics_by_wave(report_rows: Iterable[dict]) -> Dict[str, dict]:
    by_wave: Dict[str, dict] = {}
    for row in report_rows:
        wave_id = (row.get("wave_id") or "").strip()
        if wave_id:
            by_wave[wave_id] = row
    return by_wave


def build_rows(wave_rows: List[dict], physics_rows: List[dict]) -> tuple[List[dict], int]:
    physics_index = _physics_by_wave(physics_rows)
    rows: List[dict] = []
    dropped = 0

    for wave in wave_rows:
        physics = physics_index.get((wave.get("wave_id") or "").strip(), {})
        merged = dict(wave)
        merged.update(physics)
        if _has_prohibited_label(merged):
            dropped += 1
            continue
        normalized = _normalize_row(merged)
        normalized["physics_status"] = (
            "needs_review" if _as_int(normalized.get("physics_violation_count")) > 0 else "passed"
        )
        rows.append(normalized)

    rows.sort(
        key=lambda r: (
            -_as_int(r.get("physics_violation_count")),
            -_as_int(r.get("wave_obs_count")),
            str(r.get("wave_aircraft_identity") or ""),
        )
    )
    return rows, dropped


def _counts(rows: List[dict], review_rows: List[dict]) -> dict:
    return {
        "wave_count": len(rows),
        "multi_obs_wave_count": sum(1 for r in rows if _as_int(r.get("wave_obs_count")) >= 2),
        "physics_violation_wave_count": sum(1 for r in rows if _as_int(r.get("physics_violation_count")) > 0),
        "physics_review_rows": len(review_rows),
        "physics_passed_count": sum(1 for r in rows if str(r.get("physics_status")) == "passed"),
        "temporal_coherent_count": sum(1 for r in rows if _as_int(r.get("wave_temporal_coherence")) == 1),
    }


def run(
    waves_csv: Path,
    physics_report_csv: Path,
    physics_review_csv: Path,
    analysis_summary_json: Path,
    validator_summary_json: Path,
    output_json: Path,
) -> dict:
    wave_rows = read_csv(waves_csv)
    physics_rows = read_csv(physics_report_csv)
    review_rows = read_csv(physics_review_csv)
    rows, dropped = build_rows(wave_rows, physics_rows)
    counts = _counts(rows, review_rows)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "temporal_dashboard_data_version": TEMPORAL_DASHBOARD_DATA_VERSION,
        "policy": POLICY,
        "row_count": len(rows),
        "prohibited_label_dropped": dropped,
        "counts": counts,
        "physics_status_counts": dict(Counter(r.get("physics_status", "") for r in rows)),
        "sources": {
            "waves_csv": str(waves_csv),
            "physics_report_csv": str(physics_report_csv),
            "physics_review_csv": str(physics_review_csv),
            "analysis_summary_json": str(analysis_summary_json),
            "validator_summary_json": str(validator_summary_json),
        },
        "upstream_summaries": {
            "analysis_vector": read_json(analysis_summary_json),
            "wave_validator": read_json(validator_summary_json),
        },
        "rows": rows,
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    return {
        "output_json": str(output_json),
        "row_count": len(rows),
        "prohibited_label_dropped": dropped,
        "counts": counts,
        "temporal_dashboard_data_version": TEMPORAL_DASHBOARD_DATA_VERSION,
        "policy": POLICY,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Export FR24 temporal waves as dashboard JSON")
    parser.add_argument("--waves-csv", default="data/_manifests/fr24_audit/fr24_temporal_waves.csv")
    parser.add_argument("--physics-report-csv", default="data/_manifests/fr24_audit/fr24_wave_physics_report.csv")
    parser.add_argument("--physics-review-csv", default="data/_manifests/fr24_audit/fr24_wave_physics_review_queue.csv")
    parser.add_argument("--analysis-summary-json", default="data/_manifests/fr24_audit/fr24_analysis_vector_summary.json")
    parser.add_argument("--validator-summary-json", default="data/_manifests/fr24_audit/fr24_wave_validator_summary.json")
    parser.add_argument("--output-json", default="fr24_temporal_wave_dashboard.json")
    args = parser.parse_args()
    summary = run(
        waves_csv=Path(args.waves_csv),
        physics_report_csv=Path(args.physics_report_csv),
        physics_review_csv=Path(args.physics_review_csv),
        analysis_summary_json=Path(args.analysis_summary_json),
        validator_summary_json=Path(args.validator_summary_json),
        output_json=Path(args.output_json),
    )
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
