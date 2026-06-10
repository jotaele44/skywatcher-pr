"""
FR24 TEMPORAL WAVE PIPELINE

Chains the mainline FR24 candidate stages from field selection through OCR
analysis vectors, temporal wave grouping, and wave physics validation.

Scope:
  fused/deduped OCR candidates -> selected candidates -> vectors/waves -> physics report

All records remain candidate records; this runner does not promote event status.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Dict, Iterable, List

from fr24.field_select import run as field_select_run
from fr24.ocr_analysis_vector import run as analysis_vector_run
from fr24.wave_validator import run as wave_validator_run

PIPELINE_VERSION = "fr24_temporal_wave_pipeline_v0.1.0"
POLICY = "candidate_only_no_auto_confirmation"

PROHIBITED_LABELS = {
    "confirmed",
    "confirmed_aircraft_event",
    "confirmed_" + "anomaly",
    "confirmed_route",
    "verified_event",
    "validated_aircraft_event",
}


def _read_csv(path: Path) -> List[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _scan_rows_for_prohibited_labels(rows: Iterable[dict]) -> List[str]:
    findings: List[str] = []
    for row_idx, row in enumerate(rows, 1):
        for key, value in row.items():
            token = str(value or "").strip()
            if token.lower() in PROHIBITED_LABELS:
                findings.append(f"row{row_idx}:{key}={token}")
    return findings


def _csv_row_count(path: Path) -> int:
    return len(_read_csv(path))


def _validate_policy(output_paths: Dict[str, Path]) -> dict:
    csv_outputs = {
        key: path for key, path in output_paths.items()
        if path.suffix.lower() == ".csv"
    }
    findings: Dict[str, List[str]] = {}
    for key, path in csv_outputs.items():
        bad = _scan_rows_for_prohibited_labels(_read_csv(path))
        if bad:
            findings[key] = bad

    return {
        "policy": POLICY,
        "prohibited_label_findings": findings,
        "prohibited_label_count": sum(len(v) for v in findings.values()),
        "policy_check_passed": not findings,
    }


def run(input_csv: Path, output_dir: Path) -> dict:
    """Run field selection -> vector/waves -> wave validator."""
    output_dir.mkdir(parents=True, exist_ok=True)

    selected_csv = output_dir / "fr24_event_candidates_selected.csv"
    field_review_csv = output_dir / "fr24_field_selection_review_queue.csv"
    field_summary_json = output_dir / "fr24_field_selection_summary.json"

    field_summary = field_select_run(
        input_csv=input_csv,
        output_csv=selected_csv,
        review_csv=field_review_csv,
        summary_json=field_summary_json,
    )

    vector_summary = analysis_vector_run(
        input_csv=selected_csv,
        output_dir=output_dir,
    )

    vectors_csv = output_dir / "fr24_ocr_analysis_vectors.csv"
    waves_csv = output_dir / "fr24_temporal_waves.csv"

    validator_summary = wave_validator_run(
        vectors_csv=vectors_csv,
        waves_csv=waves_csv,
        output_dir=output_dir,
    )

    output_paths = {
        "selected_csv": selected_csv,
        "field_review_csv": field_review_csv,
        "field_summary_json": field_summary_json,
        "vectors_csv": vectors_csv,
        "waves_csv": waves_csv,
        "analysis_summary_json": output_dir / "fr24_analysis_vector_summary.json",
        "physics_report_csv": output_dir / "fr24_wave_physics_report.csv",
        "physics_review_csv": output_dir / "fr24_wave_physics_review_queue.csv",
        "validator_summary_json": output_dir / "fr24_wave_validator_summary.json",
    }
    policy_check = _validate_policy(output_paths)

    summary = {
        "input_csv": str(input_csv),
        "output_dir": str(output_dir),
        "input_rows": _csv_row_count(input_csv),
        "selected_rows": _csv_row_count(selected_csv),
        "vector_rows": _csv_row_count(vectors_csv),
        "wave_rows": _csv_row_count(waves_csv),
        "physics_report_rows": _csv_row_count(output_paths["physics_report_csv"]),
        "physics_review_rows": _csv_row_count(output_paths["physics_review_csv"]),
        "stage_summaries": {
            "field_select": field_summary,
            "analysis_vector": vector_summary,
            "wave_validator": validator_summary,
        },
        "outputs": {key: str(path) for key, path in output_paths.items()},
        "policy_check": policy_check,
        "pipeline_version": PIPELINE_VERSION,
        "policy": POLICY,
    }

    summary_json = output_dir / "fr24_temporal_wave_pipeline_summary.json"
    summary["outputs"]["pipeline_summary_json"] = str(summary_json)
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run FR24 field selection, OCR analysis vectors, temporal waves, and wave validation"
    )
    parser.add_argument(
        "--input-csv",
        default="data/_manifests/fr24_audit/fr24_fused_event_candidates_deduped.csv",
        help="Input fused/deduped FR24 OCR candidate CSV",
    )
    parser.add_argument(
        "--output-dir",
        default="data/_manifests/fr24_audit",
        help="Directory for selected, vector, wave, validator, and summary outputs",
    )
    args = parser.parse_args()
    print(json.dumps(run(Path(args.input_csv), Path(args.output_dir)), indent=2))


if __name__ == "__main__":
    main()
