from datetime import datetime, timedelta, timezone

import pytest

from server.backend.console.time import UTCValidationError, normalize_utc, parse_utc_datetime


def test_normalize_z_suffix():
    assert normalize_utc("2026-07-20T12:00:00-04:00") == "2026-07-20T16:00:00Z"


def test_datetime_normalizes_to_utc():
    value = datetime(2026, 7, 20, 12, 0, tzinfo=timezone(timedelta(hours=-4)))
    assert parse_utc_datetime(value).tzinfo == timezone.utc


def test_naive_datetime_rejected():
    with pytest.raises(UTCValidationError, match="timezone"):
        normalize_utc("2026-07-20T12:00:00")


def test_invalid_datetime_rejected():
    with pytest.raises(UTCValidationError, match="valid ISO-8601"):
        normalize_utc("not-a-date")
