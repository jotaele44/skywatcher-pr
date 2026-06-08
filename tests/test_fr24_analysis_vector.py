"""Tests for fr24_ocr_analysis_vector — vector computation and temporal wave grouping."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from fr24.ocr_analysis_vector import (
    PROHIBITED_LABELS,
    SELECT_FIELDS,
    build_waves,
    compute_vector,
    run,
)


# ── fixtures ───────────────────────────────────────────────────────────────────

def _full_row(**overrides) -> dict:
    """Return a row with all 14 SELECT_FIELDS populated."""
    base = {
        "image_path": "/data/img001.jpg",
        "image_name": "img001.jpg",
        "callsign_or_label": "UAL123",
        "operator": "United Airlines",
        "aircraft_type": "B737",
        "registration": "N12345",
        "origin_code": "SJU",
        "destination_code": "BQN",
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
    }
    base.update(overrides)
    return base


def _empty_row() -> dict:
    return {
        "image_path": "/data/img002.jpg",
        "image_name": "img002.jpg",
        **{f: "" for f in SELECT_FIELDS},
        "whole_confidence": "0.0",
        "region_confidence": "0.0",
        "conflict_count": "0",
        "selected_field_disagreements": "",
    }


# ── field coverage ─────────────────────────────────────────────────────────────

def test_vector_field_coverage_full():
    row = _full_row(elapsed_arrived="0:10")  # ensure all 14 are set
    vec = compute_vector(row)
    assert vec["vector_field_coverage"] == 1.0


def test_vector_field_coverage_empty():
    vec = compute_vector(_empty_row())
    assert vec["vector_field_coverage"] == 0.0


def test_vector_field_coverage_partial():
    row = _empty_row()
    row["callsign_or_label"] = "UAL"
    row["registration"] = "N99"
    vec = compute_vector(row)
    assert vec["vector_field_coverage"] == pytest.approx(2 / 14, rel=1e-3)


# ── quality tier ───────────────────────────────────────────────────────────────

def test_vector_quality_tier_tier1():
    row = _full_row(elapsed_arrived="0:10")
    vec = compute_vector(row)
    assert vec["vector_quality_tier"] == 1


def test_vector_quality_tier_tier4_empty():
    vec = compute_vector(_empty_row())
    assert vec["vector_quality_tier"] == 4


def test_vector_quality_tier_tier2_medium():
    # 6/14 ≈ 0.43 coverage, 1 conflict → tier 2
    row = _empty_row()
    for field in SELECT_FIELDS[:6]:
        row[field] = "X"
    row["conflict_count"] = "1"
    vec = compute_vector(row)
    assert vec["vector_quality_tier"] == 2


def test_vector_quality_tier_tier3_low():
    # 2/14 ≈ 0.14 < 0.15 → tier 4; 3/14 ≈ 0.21 → tier 3
    row = _empty_row()
    for field in SELECT_FIELDS[:3]:
        row[field] = "X"
    vec = compute_vector(row)
    assert vec["vector_quality_tier"] == 3


# ── conflict normalization ─────────────────────────────────────────────────────

def test_vector_conflict_normalized_cap():
    row = _empty_row()
    row["conflict_count"] = "100"
    vec = compute_vector(row)
    assert vec["vector_conflict_normalized"] == 1.0


def test_vector_conflict_zero():
    row = _full_row()
    vec = compute_vector(row)
    assert vec["vector_conflict_count"] == 0
    assert vec["vector_conflict_normalized"] == 0.0


# ── temporal parsing ───────────────────────────────────────────────────────────

def test_temporal_parsed_valid_date_with_time():
    row = _full_row(playback_date="Mon, May 23, 2026", playback_time="10:30 AM")
    vec = compute_vector(row)
    assert vec["vector_temporal_parsed"] == 1
    assert vec["vector_playback_iso"].startswith("2026-05-23T")


def test_temporal_parsed_valid_date_no_time():
    row = _full_row(playback_time="")
    vec = compute_vector(row)
    assert vec["vector_temporal_parsed"] == 1
    assert vec["vector_playback_iso"].startswith("2026-05-23")


def test_temporal_parsed_invalid_date():
    row = _full_row(playback_date="Flightradar24 garbage text !@#")
    vec = compute_vector(row)
    assert vec["vector_temporal_parsed"] == 0
    assert vec["vector_playback_iso"] == ""


def test_temporal_parsed_empty_date():
    row = _empty_row()
    vec = compute_vector(row)
    assert vec["vector_temporal_parsed"] == 0
    assert vec["vector_playback_iso"] == ""


# ── aircraft identity priority ─────────────────────────────────────────────────

def test_aircraft_identity_registration_wins():
    row = _full_row(registration="N12345", callsign_or_label="UAL123")
    vec = compute_vector(row)
    assert vec["vector_aircraft_identity"] == "N12345"


def test_aircraft_identity_callsign_fallback():
    row = _full_row(registration="", callsign_or_label="UAL123")
    vec = compute_vector(row)
    assert vec["vector_aircraft_identity"] == "UAL123"


def test_aircraft_identity_image_fallback():
    row = _empty_row()
    vec = compute_vector(row)
    assert vec["vector_aircraft_identity"] == "img002.jpg"


# ── wave grouping ──────────────────────────────────────────────────────────────

def _make_vectored(registration: str, playback_date: str, playback_time: str = "", **kw) -> dict:
    row = _full_row(registration=registration, playback_date=playback_date, playback_time=playback_time, **kw)
    merged = dict(row)
    merged.update(compute_vector(row))
    return merged


def test_wave_single_obs():
    rows = [_make_vectored("N11111", "Mon, May 23, 2026", "10:00")]
    waves = build_waves(rows)
    assert len(waves) == 1
    assert waves[0]["wave_obs_count"] == 1


def test_wave_multi_obs_sorted():
    # Three observations for the same aircraft, supplied out of order
    rows = [
        _make_vectored("N22222", "Mon, May 23, 2026", "12:00"),
        _make_vectored("N22222", "Mon, May 23, 2026", "09:00"),
        _make_vectored("N22222", "Mon, May 23, 2026", "10:30"),
    ]
    waves = build_waves(rows)
    assert len(waves) == 1
    wave = waves[0]
    assert wave["wave_obs_count"] == 3
    assert wave["wave_earliest_iso"] < wave["wave_latest_iso"]
    # Earliest should be the 09:00 observation
    assert "T09:00" in wave["wave_earliest_iso"]


def test_wave_duration_minutes():
    rows = [
        _make_vectored("N33333", "Mon, May 23, 2026", "10:00"),
        _make_vectored("N33333", "Mon, May 23, 2026", "11:30"),
    ]
    waves = build_waves(rows)
    assert waves[0]["wave_duration_minutes"] == pytest.approx(90.0)


def test_wave_multiple_aircraft():
    rows = [
        _make_vectored("N44444", "Mon, May 23, 2026", "10:00"),
        _make_vectored("N55555", "Mon, May 23, 2026", "11:00"),
        _make_vectored("N44444", "Mon, May 23, 2026", "10:30"),
    ]
    waves = build_waves(rows)
    assert len(waves) == 2
    obs_counts = sorted(w["wave_obs_count"] for w in waves)
    assert obs_counts == [1, 2]


def test_wave_temporal_coherence_all_parsed():
    rows = [
        _make_vectored("N66666", "Mon, May 23, 2026", "10:00"),
        _make_vectored("N66666", "Mon, May 23, 2026", "10:30"),
    ]
    waves = build_waves(rows)
    assert waves[0]["wave_temporal_coherence"] == 1


def test_wave_temporal_coherence_partial():
    row1 = _make_vectored("N77777", "Mon, May 23, 2026", "10:00")
    row2 = _make_vectored("N77777", "garbage date", "")
    waves = build_waves([row1, row2])
    assert waves[0]["wave_temporal_coherence"] == 0


# ── policy: prohibited labels ──────────────────────────────────────────────────

def test_prohibited_label_absent_in_vectors():
    rows = [_full_row(), _empty_row()]
    vectored = []
    for row in rows:
        merged = dict(row)
        merged.update(compute_vector(row))
        vectored.append(merged)

    for row in vectored:
        for key, value in row.items():
            if isinstance(value, str):
                assert value.lower() not in PROHIBITED_LABELS, (
                    f"Prohibited label '{value}' found in key '{key}'"
                )


def test_prohibited_label_absent_in_waves():
    rows = [_make_vectored("N88888", "Mon, May 23, 2026", "10:00")]
    waves = build_waves(rows)
    for wave in waves:
        for key, value in wave.items():
            if isinstance(value, str):
                assert value.lower() not in PROHIBITED_LABELS, (
                    f"Prohibited label '{value}' found in wave key '{key}'"
                )


# ── empty-input safety ─────────────────────────────────────────────────────────

def test_empty_input_safe(tmp_path):
    empty_csv = tmp_path / "empty.csv"
    empty_csv.write_text("", encoding="utf-8")

    result = run(empty_csv, tmp_path / "out")

    assert result["candidate_count"] == 0
    assert result["wave_count"] == 0
    assert "tier_distribution" in result


def test_empty_input_outputs_exist(tmp_path):
    empty_csv = tmp_path / "empty.csv"
    empty_csv.write_text("", encoding="utf-8")
    out_dir = tmp_path / "out"

    run(empty_csv, out_dir)

    assert (out_dir / "fr24_ocr_analysis_vectors.csv").exists()
    assert (out_dir / "fr24_temporal_waves.csv").exists()
    assert (out_dir / "fr24_analysis_vector_summary.json").exists()


# ── summary JSON structure ─────────────────────────────────────────────────────

def test_summary_json_structure(tmp_path):
    input_csv = tmp_path / "candidates.csv"
    rows = [_full_row(elapsed_arrived="0:05"), _full_row(registration="N99999", image_path="/b.jpg", image_name="b.jpg")]
    fieldnames = list(rows[0].keys())
    with input_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    result = run(input_csv, tmp_path / "out")

    for key in ("input_csv", "candidate_count", "wave_count", "tier_distribution", "vector_version", "policy"):
        assert key in result, f"Missing key '{key}' in summary"

    assert result["candidate_count"] == 2
    assert result["policy"] == "candidate_only_no_auto_confirmation"


def test_summary_json_is_valid_json(tmp_path):
    empty_csv = tmp_path / "empty.csv"
    empty_csv.write_text("", encoding="utf-8")
    out_dir = tmp_path / "out"

    run(empty_csv, out_dir)

    summary_path = out_dir / "fr24_analysis_vector_summary.json"
    parsed = json.loads(summary_path.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
