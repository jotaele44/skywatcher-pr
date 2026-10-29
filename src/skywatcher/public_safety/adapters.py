"""Admit pinned public source snapshots without network fetch or identity inference.

The caller must supply original bytes and an expected immutable SHA-256.
This adapter does not ingest live identities or infer links between events.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from .records import PublicSafetyError
from .snapshots import validate_snapshot


def admit_public_snapshot(manifest: Mapping, raw_bytes: bytes) -> dict:
    """Validate an offline, source-frozen JSON record export and its receipt."""
    if not isinstance(manifest, Mapping):
        raise PublicSafetyError("manifest must be mapping")
    required = {"source_id", "source_url", "retrieved_utc", "raw_sha256"}
    if set(manifest) != required:
        raise PublicSafetyError("manifest keys mismatch")
    if not isinstance(raw_bytes, bytes):
        raise PublicSafetyError("original source bytes required")
    if hashlib.sha256(raw_bytes).hexdigest() != manifest["raw_sha256"]:
        raise PublicSafetyError("source byte hash mismatch")
    try:
        parsed = json.loads(raw_bytes.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise PublicSafetyError("source not a valid UTF-8 JSON payload") from exc
    if not isinstance(parsed, list):
        raise PublicSafetyError("record payload must be a list")
    snap = dict(manifest, records=parsed)
    return validate_snapshot(snap, source_bytes=raw_bytes)
