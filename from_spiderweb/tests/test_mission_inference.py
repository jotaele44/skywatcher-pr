"""Tests for MultiFactorMissionScorer probabilities."""

import sqlite3

import pytest

from pipeline.mission_inference import MultiFactorMissionScorer


def test_scorer_initializes(populated_db):
    scorer = MultiFactorMissionScorer(populated_db)
    assert scorer is not None


def test_score_flight_returns_list(populated_db):
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    flight = dict(conn.execute(
        "SELECT * FROM flights WHERE flight_id = 'FLT_N5854Z_001'"
    ).fetchone())
    track = [dict(r) for r in conn.execute(
        "SELECT * FROM track_points WHERE flight_id = 'FLT_N5854Z_001'"
    )]
    conn.close()

    scorer = MultiFactorMissionScorer(populated_db)
    results = scorer.score_flight(flight, track, [], [])
    assert isinstance(results, list)


def test_score_values_in_range(populated_db):
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    flight = dict(conn.execute(
        "SELECT * FROM flights WHERE flight_id = 'FLT_C6062_001'"
    ).fetchone())
    track = [dict(r) for r in conn.execute(
        "SELECT * FROM track_points WHERE flight_id = 'FLT_C6062_001'"
    )]
    conn.close()

    scorer = MultiFactorMissionScorer(populated_db)
    results = scorer.score_flight(flight, track, [], [])
    for ms in results:
        score = ms.total_score if hasattr(ms, "total_score") else ms.get("total_score", 0)
        assert 0.0 <= float(score) <= 1.0, f"Score {score} out of range"


def test_score_flight_no_track(populated_db):
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    flight = dict(conn.execute(
        "SELECT * FROM flights WHERE flight_id = 'FLT_N767PD_001'"
    ).fetchone())
    conn.close()

    scorer = MultiFactorMissionScorer(populated_db)
    results = scorer.score_flight(flight, [], [], [])
    assert isinstance(results, list)


def test_score_boundary_zero_and_one(populated_db):
    import sqlite3
    conn = sqlite3.connect(populated_db)
    conn.row_factory = sqlite3.Row
    flight = dict(conn.execute(
        "SELECT * FROM flights WHERE flight_id = 'FLT_N5854Z_001'"
    ).fetchone())
    conn.close()

    scorer = MultiFactorMissionScorer(populated_db)
    results = scorer.score_flight(flight, [], [], [])
    for ms in results:
        score = ms.total_score if hasattr(ms, "total_score") else ms.get("total_score", 0)
        assert 0.0 <= float(score) <= 1.0, f"Score {score} outside [0, 1]"
