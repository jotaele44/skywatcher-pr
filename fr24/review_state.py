"""FR24 dashboard local review-state JSON helpers.

The canonical review queue remains read-only. This module validates optional
sibling/local-state JSON overlays used for analyst workflow state.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from fr24.dashboard_data import ALLOWED_QUEUE_STATUSES, LOCAL_STATE_POLICY, LOCAL_STATE_SCHEMA_VERSION


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_local_state_payload(entries: Mapping[str, str], *, generated_at: str | None = None) -> dict:
    """Build a versioned local-state sibling JSON payload.

    ``entries`` maps stable queue row identity -> allowed queue status. Open rows
    may be omitted by callers; if included, they remain valid.
    """
    for identity in entries.keys():
        if not isinstance(identity, str) or not identity:
            raise ValueError("Local-state entry identity must be a non-empty string")
    invalid = sorted({status for status in entries.values() if status not in ALLOWED_QUEUE_STATUSES})
    if invalid:
        raise ValueError(f"Unsupported FR24 review queue statuses: {invalid}")
    return {
        "schema_version": LOCAL_STATE_SCHEMA_VERSION,
        "policy": LOCAL_STATE_POLICY,
        "generated_at": generated_at or utc_now_iso(),
        "allowed_queue_statuses": list(ALLOWED_QUEUE_STATUSES),
        "entries": dict(entries),
    }


def validate_local_state_payload(payload: object) -> dict:
    """Validate and normalize a local-state sibling JSON payload."""
    if not isinstance(payload, dict):
        raise ValueError("Local-state payload must be a JSON object")
    if payload.get("schema_version") != LOCAL_STATE_SCHEMA_VERSION:
        raise ValueError("Unsupported FR24 local-state schema_version")
    if payload.get("policy") != LOCAL_STATE_POLICY:
        raise ValueError("Unsupported FR24 local-state policy")
    entries = payload.get("entries")
    if not isinstance(entries, dict):
        raise ValueError("Local-state payload entries must be an object")
    normalized: dict[str, str] = {}
    for identity, status in entries.items():
        if not isinstance(identity, str) or not identity:
            raise ValueError("Local-state entry identity must be a non-empty string")
        if status not in ALLOWED_QUEUE_STATUSES:
            raise ValueError(f"Unsupported FR24 review queue status: {status}")
        normalized[identity] = status
    return build_local_state_payload(normalized, generated_at=payload.get("generated_at") or utc_now_iso())


def read_local_state_json(path: Path) -> dict:
    return validate_local_state_payload(json.loads(path.read_text(encoding="utf-8")))


def write_local_state_json(path: Path, entries: Mapping[str, str]) -> dict:
    payload = build_local_state_payload(entries)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload
