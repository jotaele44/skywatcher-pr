"""Regression tests for the auto-updating FR24 daily-batch status function.

Guards against the stale-status bug: the prior todays_batch.csv had a frozen
status column that never recomputed, so flights silently crossed the FR24
365-day retention cliff while still labelled 'grab-now'.
"""
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fr24"))
from todays_batch import compute_status, days_to_expiry, RETENTION_DAYS  # noqa: E402


def test_fresh_flight_is_available():
    today = dt.date(2026, 6, 8)
    assert compute_status(dt.date(2026, 5, 1), today) == "AVAILABLE"


def test_flight_just_inside_cliff_is_expiring():
    today = dt.date(2026, 6, 8)
    # exactly RETENTION_DAYS old -> still downloadable today, but expiring
    edge = today - dt.timedelta(days=RETENTION_DAYS)
    assert compute_status(edge, today) == "EXPIRING"


def test_flight_past_cliff_is_expired():
    today = dt.date(2026, 6, 8)
    gone = today - dt.timedelta(days=RETENTION_DAYS + 1)
    assert compute_status(gone, today) == "EXPIRED"


def test_status_auto_updates_with_today():
    """Same flight, advancing 'today', must flip EXPIRING -> EXPIRED on the cliff."""
    flight = dt.date(2025, 6, 6)
    assert compute_status(flight, dt.date(2026, 6, 6)) == "EXPIRING"
    # two days later the track has aged past 365 days and must be reclassified
    assert compute_status(flight, dt.date(2026, 6, 8)) == "EXPIRED"


def test_days_to_expiry_sign():
    today = dt.date(2026, 6, 8)
    assert days_to_expiry(dt.date(2026, 6, 1), today) == RETENTION_DAYS - 7
    assert days_to_expiry(today - dt.timedelta(days=RETENTION_DAYS + 5), today) == -5
