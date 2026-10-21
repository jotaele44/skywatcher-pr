"""Fail-closed validation for published, historical public-safety case records.

No person-level correlation, suspicion scoring, coordinates for vulnerable people,
or automated operational tasking. This layer stores source references and status.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
from collections.abc import Mapping

CATEGORIES = frozenset({"MISSING_PERSON", "HUMAN_TRAFFICKING", "MIGRANT_SMUGGLING", "MARITIME_RESCUE", "DRUG_INTERDICTION"})
STATUSES = frozenset({"REPORTED", "ACTIVE", "RECOVERED", "CLOSED", "CHARGED", "CONVICTED", "ACQUITTED", "DISMISSED", "UNRESOLVED"})
PUBLICATION = frozenset({"PUBLIC_AGGREGATE", "RESTRICTED", "WITHHELD"})
PROHIBITED = frozenset({"person_name", "date_of_birth", "phone", "home_address", "shelter_address", "live_location", "immigration_status", "suspect_score", "predicted_location", "latitude", "longitude", "lat", "lon"})

class PublicSafetyError(ValueError):
    pass

def _required(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PublicSafetyError(f"{field} required")
    return value

def validate_event(row: Mapping[str, object]) -> dict:
    """Validate a non-identifying source-backed event; never assert an inferred link."""
    if not isinstance(row, Mapping):
        raise PublicSafetyError("mapping required")
    forbidden = PROHIBITED.intersection(row)
    if forbidden:
        raise PublicSafetyError(f"prohibited fields: {sorted(forbidden)}")
    required = {"source_id", "source_record_id", "source_url", "event_id", "category", "status", "event_date", "publication", "record_sha256"}
    if set(row) - required:
        raise PublicSafetyError("unknown fields are not authorized")
    for key in required:
        _required(row.get(key), key)
    if row["category"] not in CATEGORIES or row["status"] not in STATUSES or row["publication"] not in PUBLICATION:
        raise PublicSafetyError("unknown category/status/publication")
    if row["publication"] != "PUBLIC_AGGREGATE":
        raise PublicSafetyError("restricted data must not enter this public export")
    try:
        date.fromisoformat(row["event_date"])
    except (TypeError, ValueError):
        raise PublicSafetyError("event_date must be ISO calendar date") from None
    sha = row["record_sha256"]
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise PublicSafetyError("record_sha256 must be lowercase SHA-256")
    url = row["source_url"]
    if not url.startswith("https://"):
        raise PublicSafetyError("source_url must use https")
    return deepcopy(dict(row))

def reconcile_events(rows):
    """Deduplicate identical sourced records; fail on conflicts and unsupported identity joins."""
    indexed = {}
    for raw in rows:
        record = validate_event(raw)
        identity = (record["source_id"], record["source_record_id"])
        if identity in indexed and indexed[identity] != record:
            raise PublicSafetyError("source identity collision; manual adjudication required")
        indexed[identity] = record
    return [indexed[key] for key in sorted(indexed)]
