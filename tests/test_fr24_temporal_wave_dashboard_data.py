"""Tests for fr24_temporal_wave_dashboard_data."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from fr24.temporal_wave_dashboard_data import TEMPORAL_DASHBOARD_DATA_VERSION, build_rows, run


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _wave(**overrides) -> dict:
    row = {
        "wave_id": "wave_000001",
        "wave_aircraft_identity": "N12345",
        "wave_obs_count": "2",
        "wave_earliest_iso": "2026-05-23T10:00:00",
        "wave_latest_iso": "2026-05-23T10:30:00",
        "wave_duration_minutes": "30.0",
        "wave_avg_field_coverage": "0.8",
        "wave_avg_confidence": "0.9",
        "wave_temporal_coherence": "1",
        "wave_confirmation_status": "not_confirmed",
    }
    row.update(overrides)
    return row


def _physics(**overrides) -> dict:
    row = {
        "wave_id": "wave_000001",
        "physics_check_passed": "1",
        "physics_violation_count": "0",
        "physics_violation_details": "",
        "physics_checks_run": "3",
        "physics_obs_with_data": "2",
        "validator_confirmation_status": "not_confirmed",
    }
    row.update(overrides)
    return row


def test_build_rows_joins_wave_and_physics_rows():
    rows, dropped = build_rows([_wave()], [_physics()])

    assert dropped == 0
    assert len(rows) == 1
    row = rows[0]
    assert row["wave_id"] == "wave_000001"
    assert row["wave_obs_count"] == 2
    assert row["physics_check_passed"] == 1
    assert row["physics_status"] == "passed"
    assert row["confirmation_status"] == "not_confirmed"
    assert row["dashboard_status"] == "temporal_wave_candidate"


def test_build_rows_flags_review_status_for_violations():
    rows, dropped = build_rows(
        [_wave()],
        [_physics(physics_check_passed="0", physics_violation_count="2")],
    )

    assert dropped == 0
    assert rows[0]["physics_status"] == "needs_review"
    assert rows[0]["physics_violation_count"] == 2


def test_build_rows_drops_prohibited_labels_case_insensitive():
    rows, dropped = build_rows(
        [_wave(wave_confirmation_status="Confirmed")],
        [_physics()],
    )

    assert rows == []
    assert dropped == 1


def test_run_writes_dashboard_json_payload(tmp_path):
    waves_csv = tmp_path / "waves.csv"
    physics_report_csv = tmp_path / "physics.csv"
    physics_review_csv = tmp_path / "physics_review.csv"
    analysis_summary_json = tmp_path / "analysis_summary.json"
    validator_summary_json = tmp_path / "validator_summary.json"
    output_json = tmp_path / "fr24_temporal_wave_dashboard.json"

    _write_csv(waves_csv, [_wave(), _wave(wave_id="wave_000002", wave_aircraft_identity="N99999", wave_obs_count="1")])
    _write_csv(physics_report_csv, [_physics(), _physics(wave_id="wave_000002", physics_check_passed="0", physics_violation_count="1")])
    _write_csv(physics_review_csv, [_physics(wave_id="wave_000002", physics_check_passed="0", physics_violation_count="1")])
    _write_json(analysis_summary_json, {"wave_count": 2})
    _write_json(validator_summary_json, {"violation_count": 1})

    summary = run(
        waves_csv=waves_csv,
        physics_report_csv=physics_report_csv,
        physics_review_csv=physics_review_csv,
        analysis_summary_json=analysis_summary_json,
        validator_summary_json=validator_summary_json,
        output_json=output_json,
    )

    payload = json.loads(output_json.read_text())
    assert summary["row_count"] == 2
    assert payload["temporal_dashboard_data_version"] == TEMPORAL_DASHBOARD_DATA_VERSION
    assert payload["policy"] == "candidate_only_no_auto_confirmation"
    assert payload["counts"]["wave_count"] == 2
    assert payload["counts"]["physics_violation_wave_count"] == 1
    assert payload["counts"]["physics_review_rows"] == 1
    assert len(payload["rows"]) == 2


def test_empty_inputs_are_safe(tmp_path):
    waves_csv = tmp_path / "waves.csv"
    physics_report_csv = tmp_path / "physics.csv"
    physics_review_csv = tmp_path / "physics_review.csv"
    analysis_summary_json = tmp_path / "analysis_summary.json"
    validator_summary_json = tmp_path / "validator_summary.json"
    output_json = tmp_path / "out.json"
    for path in (waves_csv, physics_report_csv, physics_review_csv):
        path.write_text("", encoding="utf-8")
    _write_json(analysis_summary_json, {})
    _write_json(validator_summary_json, {})

    summary = run(
        waves_csv=waves_csv,
        physics_report_csv=physics_report_csv,
        physics_review_csv=physics_review_csv,
        analysis_summary_json=analysis_summary_json,
        validator_summary_json=validator_summary_json,
        output_json=output_json,
    )

    payload = json.loads(output_json.read_text())
    assert summary["row_count"] == 0
    assert payload["rows"] == []
    assert payload["counts"]["wave_count"] == 0
