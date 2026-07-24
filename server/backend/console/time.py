"""UTC-only datetime parsing and normalization for console contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class UTCValidationError(ValueError):
    """Raised when a datetime is missing, malformed, or timezone-naive."""


def parse_utc_datetime(value: Any, *, field_name: str = "datetime") -> datetime:
    """Parse a timezone-aware datetime and normalize it to UTC.

    Naive datetimes are rejected. Strings may use the RFC 3339 ``Z`` suffix or
    an explicit numeric offset. The returned object always has ``timezone.utc``.
    """

    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise UTCValidationError(f"{field_name} must not be empty")
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise UTCValidationError(f"{field_name} is not a valid ISO-8601 datetime") from exc
    else:
        raise UTCValidationError(f"{field_name} must be an ISO-8601 string or datetime")

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise UTCValidationError(f"{field_name} must include a timezone offset")
    return parsed.astimezone(timezone.utc)


def normalize_utc(value: Any, *, field_name: str = "datetime") -> str:
    """Return canonical RFC 3339 UTC text with a ``Z`` suffix."""

    parsed = parse_utc_datetime(value, field_name=field_name)
    return parsed.isoformat(timespec="seconds").replace("+00:00", "Z")
