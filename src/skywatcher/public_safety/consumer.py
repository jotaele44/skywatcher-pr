"""Fail-closed, aggregate-only consumer exports for federation staging."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping

from .records import PublicSafetyError, reconcile_events

SCHEMA = "pitirre-public-safety-aggregate-v0.1"


def build_consumer_package(records, *, source_receipt: Mapping) -> dict:
    """Produce non-geocoded aggregate counts; never expose source rows to consumers."""
    if not isinstance(source_receipt, Mapping):
        raise PublicSafetyError("source receipt required")
    required = {"source_id", "retrieved_utc", "source_url", "raw_sha256", "record_count", "canonical_records_sha256"}
    if set(source_receipt) != required:
        raise PublicSafetyError("invalid receipt contract")
    if not isinstance(records, list):
        raise PublicSafetyError("records must be list")
    validated = reconcile_events(records)
    if len(validated) != len(records):
        raise PublicSafetyError("duplicate rows in consumer batch")
    if any(r["source_id"] != source_receipt["source_id"] or r["source_url"] != source_receipt["source_url"] for r in validated):
        raise PublicSafetyError("source mismatch")
    from .snapshots import canonical_bytes

    digest = hashlib.sha256(canonical_bytes(validated)).hexdigest()
    if digest != source_receipt["canonical_records_sha256"] or len(validated) != source_receipt["record_count"]:
        raise PublicSafetyError("source receipt does not bind exact records")
    counts = Counter((r["category"], r["status"], r["event_date"][:4]) for r in validated)
    rows = [{"category": category, "status": status, "year": year, "count": n}
            for (category, status, year), n in sorted(counts.items()) if n >= 5]
    return {"schema_version": SCHEMA, "publication": "PUBLIC_AGGREGATE",
            "source_receipt_sha256": hashlib.sha256(json.dumps(dict(source_receipt), sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            "groups": rows, "certification": "AUDIT_ONLY"}
