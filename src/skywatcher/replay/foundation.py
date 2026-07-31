"""Read-only primitives for the bounded Open MCT replay integration."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

_TRUE_VALUES = {"1", "true", "yes", "on"}


class ReplayDisabledError(RuntimeError):
    """Raised when replay is used while the feature flag is disabled."""


class ReplayQueryError(ValueError):
    """Raised when a replay query violates bounded-query policy."""


def replay_enabled(env: Mapping[str, str] | None = None) -> bool:
    """Return whether replay is explicitly enabled; default is fail-closed."""
    source = os.environ if env is None else env
    return source.get("SKYWATCHER_OPENMCT_REPLAY_ENABLED", "false").strip().lower() in _TRUE_VALUES


def require_replay_enabled(env: Mapping[str, str] | None = None) -> None:
    if not replay_enabled(env):
        raise ReplayDisabledError("Open MCT replay is disabled")


def stable_object_id(object_type: str, canonical_id: str) -> str:
    """Create a stable Open MCT-facing identifier without storing a second model."""
    clean_type = object_type.strip().lower().replace(" ", "-")
    clean_id = canonical_id.strip()
    if not clean_type or not clean_id or ":" in clean_type:
        raise ValueError("object_type and canonical_id must be non-empty; type cannot contain ':'")
    return f"skywatcher:{clean_type}:{clean_id}"


@dataclass(frozen=True)
class QueryBounds:
    """Validated historical query bounds."""

    start_utc: datetime
    end_utc: datetime
    limit: int = 5_000

    MAX_LIMIT = 100_000
    MAX_INTERVAL_SECONDS = 7 * 24 * 60 * 60

    def validate(self) -> "QueryBounds":
        for value in (self.start_utc, self.end_utc):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ReplayQueryError("query timestamps must be timezone-aware")
        start = self.start_utc.astimezone(timezone.utc)
        end = self.end_utc.astimezone(timezone.utc)
        if end <= start:
            raise ReplayQueryError("end_utc must be after start_utc")
        if (end - start).total_seconds() > self.MAX_INTERVAL_SECONDS:
            raise ReplayQueryError("query interval exceeds seven-day foundation limit")
        if not 1 <= self.limit <= self.MAX_LIMIT:
            raise ReplayQueryError(f"limit must be between 1 and {self.MAX_LIMIT}")
        return QueryBounds(start, end, self.limit)


def open_read_only_sqlite(path: str | Path) -> sqlite3.Connection:
    """Open an existing SQLite database with immutable read-only semantics."""
    resolved = Path(path).expanduser().resolve(strict=True)
    uri = f"file:{resolved.as_posix()}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.execute("PRAGMA query_only = ON")
    return connection


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def canonical_json_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def build_replay_receipt(
    *,
    session_id: str,
    created_at_utc: datetime,
    skywatcher_git_sha: str,
    bounds: QueryBounds,
    selected_streams: Sequence[str],
    accounting_complete: bool,
    openmct_version: str = "v4.1.0",
    openmct_artifact_sha256: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic receipt; the digest excludes its own field."""
    validated = bounds.validate()
    if not session_id.startswith("replay:"):
        raise ValueError("session_id must start with 'replay:'")
    if len(skywatcher_git_sha) != 40:
        raise ValueError("skywatcher_git_sha must be a 40-character commit SHA")
    payload: dict[str, Any] = {
        "schema": "skywatcher.replay-session.v1",
        "session_id": session_id,
        "created_at_utc": created_at_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "skywatcher_git_sha": skywatcher_git_sha,
        "openmct_version": openmct_version,
        "openmct_artifact_sha256": openmct_artifact_sha256,
        "bounds": {
            "start_utc": validated.start_utc.isoformat().replace("+00:00", "Z"),
            "end_utc": validated.end_utc.isoformat().replace("+00:00", "Z"),
        },
        "speed": 1.0,
        "selected_streams": sorted(set(selected_streams)),
        "source_offsets": [],
        "accounting_complete": accounting_complete,
    }
    payload["receipt_sha256"] = canonical_json_sha256(payload)
    return payload
