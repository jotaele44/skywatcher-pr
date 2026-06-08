"""Tests for fr24_wave_validator — wave physics coherence checks."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from fr24.wave_validator import (
    PROHIBITED_LABELS,
    MAX_CLIMB_FT_PER_MIN,
    MAX_SPEED_MPH,
    _check_pair,
    run,
    validate_wave,
)


# ── helpers ────────────────────────────────────────────────────────────────────

def _obs(
    identity: str = "N12345",
    playback_iso: str = "2026-05-23T10:00:00",
    altitude_ft: str = "3000",
    speed_mph: str = "120",
) -> dict:
    return {
        "vector_aircraft_identity": identity,
        "vector_playback_iso": playback_iso,
        "barometric_altitude_ft": altitude_ft,
        "ground_speed_mph": speed_mph,
        "image_name": f"img_{playback_iso}.jpg",
    }


def _wave(identity: str = "N12345", obs_count: int = 2) -> dict:
    return {
        "wave_id": "wave_000001",
        "wave_aircraft_identity": identity,
        "wave_obs_count": str(obs_count),
        "wave_earliest_iso": "",
        "wave_latest_iso": "",
    }


def _write_csv(path: Path, rows: list) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


# ── physics checks ─────────────────────────────────────────────────────────────

def test_clean_wave_passes():
    obs = [
        _obs(playback_iso="2026-05-23T10:00:00", altitude_ft="3000", speed_mph="120"),
        _obs(playback_iso="2026-05-23T10:30:00", altitude_ft="3500", speed_mph="130"),
    ]
    result = validate_wave(_wave(), obs)
    assert result["physics_check_passed"] == 1
    assert result["physics_violation_count"] == 0


def test_altitude_violation():
    # 10000 ft in 1 minute → 10000 ft/min >> 1500
    obs = [
        _obs(playback_iso="2026-05-23T10:00:00", altitude_ft="1000"),
        _obs(playback_iso="2026-05-23T10:01:00", altitude_ft="11000"),
    ]
    result = validate_wave(_wave(), obs)
    assert result["physics_check_passed"] == 0
    assert result["physics_violation_count"] >= 1
    assert "climb_rate_exceeded" in result["physics_violation_details"]


def test_altitude_safe_climb():
    # 750 ft in 1 minute → 750 ft/min < 1500 — should pass
    obs = [
        _obs(playback_iso="2026-05-23T10:00:00", altitude_ft="1000"),
        _obs(playback_iso="2026-05-23T10:01:00", altitude_ft="1750"),
    ]
    result = validate_wave(_wave(), obs)
    assert result["physics_check_passed"] == 1


def test_speed_out_of_range_high():
    obs = [
        _obs(playback_iso="2026-05-23T10:00:00", speed_mph="200"),  # > 180
        _obs(playback_iso="2026-05-23T10:30:00", speed_mph="120"),
    ]
    result = validate_wave(_wave(), obs)
    assert result["physics_check_passed"] == 0
    assert "speed_out_of_range" in result["physics_violation_details"]


def test_speed_at_max_boundary():
    obs = [
        _obs(playback_iso="2026-05-23T10:00:00", speed_mph=str(MAX_SPEED_MPH)),
        _obs(playback_iso="2026-05-23T10:30:00", speed_mph="100"),
    ]
    result = validate_wave(_wave(), obs)
    assert result["physics_check_passed"] == 1


def test_speed_out_of_range_low():
    obs = [
        _obs(playback_iso="2026-05-23T10:00:00", speed_mph="-5"),
        _obs(playback_iso="2026-05-23T10:30:00", speed_mph="100"),
    ]
    result = validate_wave(_wave(), obs)
    assert result["physics_check_passed"] == 0
    assert "speed_out_of_range" in result["physics_violation_details"]


def test_timestamp_non_monotonic_check_pair():
    # validate_wave sorts observations before checking, so non-monotonic inputs
    # become monotonic at the wave level. Test _check_pair directly to verify
    # the check logic itself fires on a backward pair.
    prev = _obs(playback_iso="2026-05-23T10:30:00")
    curr = _obs(playback_iso="2026-05-23T10:00:00")  # 30 min earlier
    violations, _ = _check_pair(prev, curr, 1)
    assert any("non_monotonic_timestamp" in v for v in violations)


def test_obs_sorted_by_iso_before_validation():
    # Supply obs out-of-order; the validator should sort them so that
    # the pair (10:00→10:30) is used — a safe 30-minute delta with no violation.
    obs = [
        _obs(playback_iso="2026-05-23T10:30:00", altitude_ft="3500"),
        _obs(playback_iso="2026-05-23T10:00:00", altitude_ft="3000"),  # out of order
    ]
    result = validate_wave(_wave(), obs)
    # After sort: 3000ft @ 10:00, 3500ft @ 10:30 → 500ft / 30min = 17ft/min — clean
    assert result["physics_check_passed"] == 1


# ── single / empty obs edge cases ──────────────────────────────────────────────

def test_single_obs_wave_no_checks():
    obs = [_obs()]
    result = validate_wave(_wave(obs_count=1), obs)
    assert result["physics_check_passed"] == 1
    assert result["physics_checks_run"] == 0
    assert result["physics_violation_count"] == 0


def test_empty_obs_list_no_checks():
    result = validate_wave(_wave(obs_count=0), [])
    assert result["physics_check_passed"] == 1
    assert result["physics_checks_run"] == 0


def test_missing_altitude_skips_climb_check():
    obs = [
        _obs(playback_iso="2026-05-23T10:00:00", altitude_ft=""),
        _obs(playback_iso="2026-05-23T10:30:00", altitude_ft=""),
    ]
    result = validate_wave(_wave(), obs)
    # No altitude → climb check skipped → no false violation
    assert result["physics_check_passed"] == 1


def test_missing_speed_skips_speed_check():
    obs = [
        _obs(playback_iso="2026-05-23T10:00:00", speed_mph=""),
        _obs(playback_iso="2026-05-23T10:30:00", speed_mph=""),
    ]
    result = validate_wave(_wave(), obs)
    assert result["physics_check_passed"] == 1


def test_unparsed_timestamps_skip_time_checks():
    obs = [
        _obs(playback_iso="", altitude_ft="", speed_mph=""),
        _obs(playback_iso="", altitude_ft="", speed_mph=""),
    ]
    result = validate_wave(_wave(), obs)
    assert result["physics_check_passed"] == 1
    assert result["physics_checks_run"] == 0


# ── review queue ───────────────────────────────────────────────────────────────

def test_review_queue_contains_violations_only(tmp_path):
    vectors = [
        _obs("N_CLEAN", "2026-05-23T10:00:00", "3000", "120"),
        _obs("N_CLEAN", "2026-05-23T10:30:00", "3500", "130"),
        _obs("N_DIRTY", "2026-05-23T10:00:00", "1000", "250"),  # bad speed
        _obs("N_DIRTY", "2026-05-23T10:30:00", "3000", "130"),
    ]
    waves = [
        {"wave_id": "wave_000001", "wave_aircraft_identity": "N_CLEAN", "wave_obs_count": "2"},
        {"wave_id": "wave_000002", "wave_aircraft_identity": "N_DIRTY", "wave_obs_count": "2"},
    ]
    vec_csv = tmp_path / "vectors.csv"
    wav_csv = tmp_path / "waves.csv"
    _write_csv(vec_csv, vectors)
    _write_csv(wav_csv, waves)

    run(vec_csv, wav_csv, tmp_path / "out")

    review_path = tmp_path / "out" / "fr24_wave_physics_review_queue.csv"
    review_rows = list(csv.DictReader(review_path.open()))
    assert len(review_rows) == 1
    assert review_rows[0]["wave_aircraft_identity"] == "N_DIRTY"


# ── empty input safety ─────────────────────────────────────────────────────────

def test_empty_waves_safe(tmp_path):
    empty = tmp_path / "empty.csv"
    empty.write_text("", encoding="utf-8")

    result = run(empty, empty, tmp_path / "out")

    assert result["wave_count"] == 0
    assert result["violation_count"] == 0
    assert (tmp_path / "out" / "fr24_wave_physics_report.csv").exists()
    assert (tmp_path / "out" / "fr24_wave_physics_review_queue.csv").exists()
    assert (tmp_path / "out" / "fr24_wave_validator_summary.json").exists()


# ── summary JSON structure ─────────────────────────────────────────────────────

def test_summary_json_structure(tmp_path):
    vectors = [_obs("N11111", "2026-05-23T10:00:00"), _obs("N11111", "2026-05-23T10:30:00")]
    waves = [{"wave_id": "wave_000001", "wave_aircraft_identity": "N11111", "wave_obs_count": "2"}]
    vec_csv = tmp_path / "v.csv"
    wav_csv = tmp_path / "w.csv"
    _write_csv(vec_csv, vectors)
    _write_csv(wav_csv, waves)

    result = run(vec_csv, wav_csv, tmp_path / "out")

    for key in ("wave_count", "violation_count", "passed_count", "check_breakdown", "policy", "validator_version"):
        assert key in result, f"Missing key '{key}' in summary"

    assert result["policy"] == "candidate_only_no_auto_confirmation"

    summary_path = tmp_path / "out" / "fr24_wave_validator_summary.json"
    parsed = json.loads(summary_path.read_text())
    assert isinstance(parsed, dict)


# ── prohibited labels ──────────────────────────────────────────────────────────

def test_prohibited_label_absent(tmp_path):
    vectors = [_obs("N22222", "2026-05-23T10:00:00"), _obs("N22222", "2026-05-23T10:30:00")]
    waves = [{"wave_id": "wave_000001", "wave_aircraft_identity": "N22222", "wave_obs_count": "2"}]
    vec_csv = tmp_path / "v.csv"
    wav_csv = tmp_path / "w.csv"
    _write_csv(vec_csv, vectors)
    _write_csv(wav_csv, waves)

    run(vec_csv, wav_csv, tmp_path / "out")

    report_path = tmp_path / "out" / "fr24_wave_physics_report.csv"
    for row in csv.DictReader(report_path.open()):
        for key, value in row.items():
            if isinstance(value, str):
                assert value.lower() not in PROHIBITED_LABELS, (
                    f"Prohibited label '{value}' in key '{key}'"
                )
