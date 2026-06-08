"""Tests for fr24_temporal_wave_pipeline — end-to-end pipeline runner."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from fr24.temporal_wave_pipeline import (
    PIPELINE_VERSION,
    POLICY,
    _scan_rows_for_prohibited_labels,
    run,
)


# ── helpers ────────────────────────────────────────────────────────────────────

def _write_csv(path: Path, rows: list) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _candidate_row(**overrides) -> dict:
    """Minimal fused candidate row (matches fr24_field_select expected input)."""
    base = {
        "image_name": "img001.jpg",
        "image_path": "/data/img001.jpg",
        "callsign_or_label": "UAL123",
        "operator": "United Airlines",
        "aircraft_type": "B737",
        "registration": "N12345",
        "origin_code": "SJU",
        "destination_code": "EWR",
        "barometric_altitude_ft": "5000",
        "ground_speed_mph": "150",
        "flight_status": "En Route",
        "elapsed_departed": "0:25",
        "elapsed_arrived": "",
        "playback_date": "Mon, May 23, 2026",
        "playback_time": "10:30 AM",
        "playback_timezone": "-04:00",
        "whole_confidence": "0.80",
        "region_confidence": "0.75",
        "conflict_count": "0",
        "selected_field_disagreements": "",
        "field_selection_status": "selected",
    }
    base.update(overrides)
    return base


# ── empty input safety ─────────────────────────────────────────────────────────

def test_empty_input_produces_all_outputs(tmp_path):
    empty = tmp_path / "empty.csv"
    empty.write_text("", encoding="utf-8")

    result = run(empty, tmp_path / "out")

    out = tmp_path / "out"
    expected_files = [
        "fr24_event_candidates_selected.csv",
        "fr24_field_selection_review_queue.csv",
        "fr24_field_selection_summary.json",
        "fr24_ocr_analysis_vectors.csv",
        "fr24_temporal_waves.csv",
        "fr24_analysis_vector_summary.json",
        "fr24_wave_physics_report.csv",
        "fr24_wave_physics_review_queue.csv",
        "fr24_wave_validator_summary.json",
        "fr24_temporal_wave_pipeline_summary.json",
    ]
    for fname in expected_files:
        assert (out / fname).exists(), f"Missing output: {fname}"


def test_empty_input_summary_zero_rows(tmp_path):
    empty = tmp_path / "empty.csv"
    empty.write_text("", encoding="utf-8")

    result = run(empty, tmp_path / "out")

    for key in ("input_rows", "selected_rows", "vector_rows", "wave_rows",
                "physics_report_rows", "physics_review_rows"):
        assert result[key] == 0, f"Expected 0 for '{key}', got {result[key]}"


# ── summary structure ──────────────────────────────────────────────────────────

def test_summary_json_structure(tmp_path):
    empty = tmp_path / "empty.csv"
    empty.write_text("", encoding="utf-8")

    result = run(empty, tmp_path / "out")

    for key in ("pipeline_version", "policy", "stage_summaries", "outputs", "policy_check"):
        assert key in result, f"Missing key '{key}' in summary"

    assert result["pipeline_version"] == PIPELINE_VERSION
    assert result["policy"] == POLICY
    assert result["policy"] == "candidate_only_no_auto_confirmation"

    for stage in ("field_select", "analysis_vector", "wave_validator"):
        assert stage in result["stage_summaries"], f"Missing stage summary '{stage}'"


def test_summary_json_file_is_valid(tmp_path):
    empty = tmp_path / "empty.csv"
    empty.write_text("", encoding="utf-8")
    out = tmp_path / "out"

    run(empty, out)

    parsed = json.loads((out / "fr24_temporal_wave_pipeline_summary.json").read_text())
    assert isinstance(parsed, dict)


# ── policy / prohibited labels ─────────────────────────────────────────────────

def test_policy_check_passed_on_clean_run(tmp_path):
    empty = tmp_path / "empty.csv"
    empty.write_text("", encoding="utf-8")

    result = run(empty, tmp_path / "out")

    assert result["policy_check"]["policy_check_passed"] is True
    assert result["policy_check"]["prohibited_label_count"] == 0


def test_policy_scan_catches_mixed_case_labels():
    findings = _scan_rows_for_prohibited_labels([
        {"status": "Confirmed"},
        {"status": "VERIFIED_EVENT"},
        {"status": "not_confirmed"},
    ])

    assert findings == ["row1:status=Confirmed", "row2:status=VERIFIED_EVENT"]


# ── real data wiring ───────────────────────────────────────────────────────────

def test_pipeline_wires_stages_with_data(tmp_path):
    """Two candidates for the same aircraft → one wave, one physics-checked wave."""
    rows = [
        _candidate_row(
            image_name="img001.jpg",
            registration="N12345",
            playback_date="Mon, May 23, 2026",
            playback_time="10:00 AM",
            barometric_altitude_ft="3000",
            ground_speed_mph="120",
        ),
        _candidate_row(
            image_name="img002.jpg",
            registration="N12345",
            playback_date="Mon, May 23, 2026",
            playback_time="10:30 AM",
            barometric_altitude_ft="3500",
            ground_speed_mph="130",
        ),
    ]
    input_csv = tmp_path / "candidates.csv"
    _write_csv(input_csv, rows)

    result = run(input_csv, tmp_path / "out")

    assert result["input_rows"] == 2
    assert result["selected_rows"] >= 1   # at least one passes field selection
    assert result["wave_rows"] >= 1        # grouped into at least one wave
    assert result["physics_review_rows"] == 0  # clean data → no violations
    assert result["policy_check"]["policy_check_passed"] is True
