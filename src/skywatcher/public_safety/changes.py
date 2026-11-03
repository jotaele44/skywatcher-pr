"""Deterministic source-receipt change detection without fetching or publishing records."""
from __future__ import annotations

from collections.abc import Mapping

from .records import PublicSafetyError

REQUIRED = frozenset({
    "source_id", "source_url", "retrieved_utc", "raw_sha256",
    "record_count", "canonical_records_sha256",
})


def compare_receipts(previous: Mapping, current: Mapping) -> dict:
    """Classify bounded change. No source identity or record identity inferred."""
    if not isinstance(previous, Mapping) or not isinstance(current, Mapping):
        raise PublicSafetyError("both receipts required")
    if set(previous) != REQUIRED or set(current) != REQUIRED:
        raise PublicSafetyError("receipt keys mismatch")
    if previous["source_id"] != current["source_id"] or previous["source_url"] != current["source_url"]:
        raise PublicSafetyError("source scope changed; manual review required")
    if not all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in (
        previous["record_count"], current["record_count"]
    )):
        raise PublicSafetyError("invalid record count")
    for receipt in (previous, current):
        for name in ("raw_sha256", "canonical_records_sha256"):
            value = receipt[name]
            if not isinstance(value, str) or len(value) != 64 or any(
                char not in "0123456789abcdef" for char in value
            ):
                raise PublicSafetyError("invalid receipt digest")
    if previous["retrieved_utc"] == current["retrieved_utc"] and previous != current:
        raise PublicSafetyError("same-time source snapshot conflict")
    byte_changed = previous["raw_sha256"] != current["raw_sha256"]
    logical_changed = previous["canonical_records_sha256"] != current["canonical_records_sha256"]
    return {
        "source_id": previous["source_id"],
        "byte_changed": byte_changed,
        "logical_changed": logical_changed,
        "count_delta": current["record_count"] - previous["record_count"],
        "classification": (
            "UNCHANGED" if not byte_changed and not logical_changed
            else "BYTE_ONLY_CHANGE" if byte_changed and not logical_changed
            else "LOGICAL_CHANGE"
        ),
        "certification": "AUDIT_ONLY",
    }
