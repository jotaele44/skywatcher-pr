"""Atomic, privacy-preserving source snapshot admission and rollback verification."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime

from .records import PublicSafetyError, reconcile_events

FIELDS = frozenset({"source_id", "retrieved_utc", "source_url", "raw_sha256", "records"})
HEX = frozenset("0123456789abcdef")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_bytes(records: list[dict]) -> bytes:
    """Canonical snapshot bytes; preserve original strings without normalization."""
    return json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def validate_snapshot(snapshot: Mapping, *, source_bytes: bytes) -> dict:
    """Validate immutable source receipt, record identities, and publication safety."""
    if not isinstance(snapshot, Mapping) or set(snapshot) != FIELDS:
        raise PublicSafetyError("snapshot schema mismatch")
    if not isinstance(snapshot["source_id"], str) or not snapshot["source_id"].strip():
        raise PublicSafetyError("source_id required")
    if not isinstance(snapshot["source_url"], str) or not snapshot["source_url"].startswith("https://"):
        raise PublicSafetyError("HTTPS source_url required")
    if not isinstance(source_bytes, bytes):
        raise PublicSafetyError("raw source bytes required")
    digest = snapshot["raw_sha256"]
    if not isinstance(digest, str) or len(digest) != 64 or set(digest) - HEX:
        raise PublicSafetyError("invalid source digest")
    if _sha256(source_bytes) != digest:
        raise PublicSafetyError("source digest mismatch")
    try:
        dt = datetime.fromisoformat(snapshot["retrieved_utc"].replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError) as exc:
        raise PublicSafetyError("invalid retrieved_utc") from exc
    if dt.tzinfo is None or dt.utcoffset().total_seconds() != 0:
        raise PublicSafetyError("retrieval must use UTC")
    if not isinstance(snapshot["records"], list):
        raise PublicSafetyError("records must be list")
    validated = reconcile_events(snapshot["records"])
    if len(validated) != len(snapshot["records"]):
        raise PublicSafetyError("duplicate source rows not allowed in frozen snapshots")
    for record in validated:
        if record["source_id"] != snapshot["source_id"] or record["source_url"] != snapshot["source_url"]:
            raise PublicSafetyError("snapshot source lineage mismatch")
    return {"source_id": snapshot["source_id"], "retrieved_utc": snapshot["retrieved_utc"],
            "source_url": snapshot["source_url"], "raw_sha256": digest,
            "record_count": len(validated), "canonical_records_sha256": _sha256(canonical_bytes(validated))}


def certify_rollback(previous_receipt: Mapping, restored_receipt: Mapping) -> bool:
    """Proof only for exact receipt restoration, not operational service recovery."""
    required = {"source_id", "retrieved_utc", "source_url", "raw_sha256", "record_count", "canonical_records_sha256"}
    if not isinstance(previous_receipt, Mapping) or not isinstance(restored_receipt, Mapping):
        raise PublicSafetyError("rollback receipts required")
    if set(previous_receipt) != required or set(restored_receipt) != required:
        raise PublicSafetyError("rollback receipt schema mismatch")
    if dict(previous_receipt) != dict(restored_receipt):
        raise PublicSafetyError("rollback receipt differs")
    return True
