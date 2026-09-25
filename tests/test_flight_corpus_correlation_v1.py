from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from skywatcher.flight_corpus_correlation_v1 import (
    DetectorParameters,
    Track,
    TrackPoint,
    analyze_track_pair,
    classify_samples,
    synchronize_tracks,
)

ROOT = Path(__file__).parents[1]
CFG = ROOT / "config" / "correlation_detector_v1.json"
V4_CFG = ROOT / "config" / "flight_corpus_v4.json"


def point(
    second: int,
    *,
    lat: float = 18.3,
    lon: float = -66.2,
    altitude: float = 1000,
    speed: float = 100,
    heading: float = 90,
) -> TrackPoint:
    return TrackPoint(
        observed_at=datetime(2025, 9, 12, tzinfo=timezone.utc) + timedelta(seconds=second),
        lat=lat,
        lon=lon,
        altitude_ft=altitude,
        speed_kt=speed,
        heading_deg=heading,
    )


def track(registration: str, flight_id: str, points: list[TrackPoint]) -> Track:
    return Track(
        flight_id=flight_id,
        registration=registration,
        points=tuple(points),
        source_path=f"{registration}/{flight_id}.csv",
    )


def paired_samples(
    *,
    seconds: range,
    lon_offset: float = 0.005,
    left_altitude: float = 1000,
    right_altitude: float = 1100,
    left_heading: float = 90,
    right_heading: float = 95,
    left_speed: float = 100,
    right_speed: float = 105,
):
    left = track(
        "NLEFT",
        "11111111",
        [
            point(
                second,
                altitude=left_altitude,
                heading=left_heading,
                speed=left_speed,
            )
            for second in seconds
        ],
    )
    right = track(
        "NRIGHT",
        "22222222",
        [
            point(
                second + 1,
                lon=-66.2 + lon_offset,
                altitude=right_altitude,
                heading=right_heading,
                speed=right_speed,
            )
            for second in seconds
        ],
    )
    return synchronize_tracks(left, right)


def load_registry():
    return json.loads(CFG.read_text(encoding="utf-8"))


def test_sustained_airborne_parallel_geometry_is_descriptive_co_route():
    samples = paired_samples(seconds=range(0, 161, 10))
    metrics = classify_samples(samples)
    assert metrics.classification == "AIRBORNE_CO_ROUTE"
    assert metrics.time_within_5km_seconds >= 120
    assert metrics.mission == "UNKNOWN"
    assert metrics.coordination == "UNKNOWN"
    assert metrics.targeting == "UNKNOWN"
    assert metrics.intent == "UNKNOWN"


def test_crossing_heading_prevents_co_route_promotion():
    samples = paired_samples(
        seconds=range(0, 161, 10),
        left_heading=10,
        right_heading=120,
    )
    metrics = classify_samples(samples)
    assert metrics.classification == "CROSSING_TRAJECTORIES"
    assert metrics.median_heading_difference_deg is not None
    assert metrics.median_heading_difference_deg >= 60


def test_ground_pattern_precedes_airborne_co_route():
    samples = paired_samples(
        seconds=range(0, 101, 10),
        left_altitude=200,
        right_altitude=300,
    )
    metrics = classify_samples(samples)
    assert metrics.classification == "SHARED_AIRPORT_OR_GROUND_PATTERN"
    assert metrics.groundlike_close_fraction == 1.0


def test_large_synchronized_separation_is_out_of_area_not_artifact():
    samples = paired_samples(seconds=range(0, 101, 10), lon_offset=1.0)
    metrics = classify_samples(samples)
    assert metrics.classification == "OUT_OF_AREA_CONCURRENT"
    assert metrics.min_distance_km is not None
    assert metrics.min_distance_km > 50


def test_short_close_encounter_stays_brief():
    samples = paired_samples(seconds=range(0, 51, 10))
    metrics = classify_samples(samples)
    assert metrics.classification == "BRIEF_PROXIMITY"
    assert metrics.time_within_5km_seconds < 60


def test_two_synchronized_samples_fail_closed_as_sparse():
    samples = paired_samples(seconds=range(0, 20, 10))
    metrics = classify_samples(samples)
    assert len(samples) == 2
    assert metrics.classification == "UNRESOLVED_SYNC_SPARSE"


def test_long_observation_gap_is_not_counted_as_proximity_duration():
    left = track(
        "NLEFT",
        "33333333",
        [
            point(0),
            point(10),
            point(20),
            point(600),
            point(610),
            point(620),
        ],
    )
    right = track(
        "NRIGHT",
        "44444444",
        [
            point(1, lon=-66.195),
            point(11, lon=-66.195),
            point(21, lon=-66.195),
            point(601, lon=-66.195),
            point(611, lon=-66.195),
            point(621, lon=-66.195),
        ],
    )
    samples = synchronize_tracks(left, right)
    metrics = classify_samples(samples)
    assert metrics.time_within_5km_seconds == 40
    assert metrics.classification == "BRIEF_PROXIMITY"


def test_missing_track_geometry_is_blocked_not_negative_evidence():
    left = track("N540DB", "55555555", [point(0), point(10), point(20)])
    right = track("N936DM", "66666666", [])
    result = analyze_track_pair(left, right)
    assert result["classification"] == "BLOCKED_GEOMETRY"
    assert result["mission"] == "UNKNOWN"
    assert result["coordination"] == "UNKNOWN"


def test_v1_registry_closes_25_pair_regression_denominator():
    registry = load_registry()
    pairs = registry["regression_pairs"]
    assert len(pairs) == 25
    assert len({tuple(row["aircraft"]) for row in pairs}) == 25


def test_v1_registry_has_one_airborne_co_route_pair_and_preserves_v4_candidate():
    registry = load_registry()
    promoted = [
        row
        for row in registry["regression_pairs"]
        if row["representative_state"] == "AIRBORNE_CO_ROUTE"
    ]
    assert len(promoted) == 1
    assert promoted[0]["aircraft"] == ["N196DM", "N407PR"]
    assert promoted[0]["date"] == "2025-09-12"
    candidate = registry["promoted_descriptive_candidate"]
    assert candidate["classification"] == "REPEATED_AIRBORNE_CO_ROUTE_CANDIDATE"
    assert candidate["mission"] == "UNKNOWN"
    assert candidate["coordination"] == "UNKNOWN"


def test_v1_promoted_candidate_matches_v4_without_semantic_expansion():
    v1 = load_registry()["promoted_descriptive_candidate"]
    v4 = json.loads(V4_CFG.read_text(encoding="utf-8"))["promoted_candidates"][0]
    assert v1["aircraft"] == v4["aircraft"]
    assert v1["date"] == v4["date"]
    assert v1["classification"] == v4["classification"]
    assert v1["mission"] == v4["mission"] == "UNKNOWN"
    assert v1["coordination"] == v4["coordination"] == "UNKNOWN"


def test_geometry_recovery_denominators_close_without_zero_filling():
    recovery = load_registry()["geometry_recovery"]
    n5854z = recovery["N5854Z"]
    assert n5854z["geometry_recovered"] + n5854z["snapshot_only_unresolved"] == 111
    assert n5854z["snapshot_only_unresolved"] == 25
    n936dm = recovery["N936DM"]
    assert n936dm["geometry_recovered"] == 0
    assert n936dm["unresolved"] == n936dm["master_flights"] == 25
    assert n936dm["certification_state"] == "BLOCKED"


def test_noninference_gates_are_all_false():
    gates = load_registry()["interpretation_gates"]
    assert gates
    assert all(value is False for value in gates.values())


def test_detector_parameters_match_frozen_registry():
    registry = load_registry()["parameters"]
    params = DetectorParameters()
    assert registry["max_match_delta_seconds"] == params.max_match_delta_seconds
    assert registry["max_duration_gap_seconds"] == params.max_duration_gap_seconds
    assert registry["co_route_min_seconds"] == params.co_route_min_seconds
    assert (
        registry["co_route_heading_difference_deg"]
        == params.co_route_heading_difference_deg
    )
    assert (
        registry["co_route_speed_difference_kt"]
        == params.co_route_speed_difference_kt
    )
