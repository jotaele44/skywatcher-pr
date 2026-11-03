"""Governed source catalog: metadata only, with explicit denial of personal-case ingestion."""
from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlsplit

from .records import PublicSafetyError

CATEGORIES = frozenset({
    "MISSING_PERSON", "HUMAN_TRAFFICKING", "MIGRANT_SMUGGLING",
    "MARITIME_RESCUE", "DRUG_INTERDICTION",
})
ADMISSIONS = frozenset({"BLOCKED_PERSON_LEVEL", "MANUAL_PUBLICATION_REVIEW"})
CATALOG_KEYS = frozenset({"schema_version", "certification", "as_of", "sources"})
SOURCE_KEYS = frozenset({"id", "url", "publisher", "scope", "admission", "notes"})


def validate_source_catalog(catalog: Mapping) -> dict:
    """Reject drift, implicit person ingestion, and unreviewed source claims."""
    if not isinstance(catalog, Mapping) or set(catalog) != CATALOG_KEYS:
        raise PublicSafetyError("source catalog schema mismatch")
    if catalog["schema_version"] != "pitirre-source-catalog-v0.1":
        raise PublicSafetyError("unsupported catalog version")
    if catalog["certification"] != "DISCOVERY_ONLY":
        raise PublicSafetyError("catalog may not claim certification")
    if not isinstance(catalog["as_of"], str) or len(catalog["as_of"]) != 10:
        raise PublicSafetyError("catalog snapshot date required")
    from datetime import date

    try:
        date.fromisoformat(catalog["as_of"])
    except ValueError as exc:
        raise PublicSafetyError("invalid catalog date") from exc
    sources = catalog["sources"]
    if not isinstance(sources, list) or not sources:
        raise PublicSafetyError("sources must be nonempty list")
    seen = set()
    for row in sources:
        if not isinstance(row, Mapping) or set(row) != SOURCE_KEYS:
            raise PublicSafetyError("source row schema mismatch")
        if any(not isinstance(row[k], str) or not row[k].strip() for k in SOURCE_KEYS):
            raise PublicSafetyError("source fields must be nonempty strings")
        if row["id"] in seen:
            raise PublicSafetyError("duplicate source identifier")
        seen.add(row["id"])
        url = urlsplit(row["url"])
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise PublicSafetyError("invalid source URL")
        if set(row["scope"].split("|")) - CATEGORIES:
            raise PublicSafetyError("unknown public-safety classification")
        if row["admission"] not in ADMISSIONS:
            raise PublicSafetyError("unreviewed ingestion authorization")
        if "MISSING_PERSON" in row["scope"].split("|") and row["admission"] != "BLOCKED_PERSON_LEVEL":
            raise PublicSafetyError("missing-person feed must remain non-admissible")
    return {
        "source_count": len(sources),
        "source_ids": sorted(seen),
        "certification": "DISCOVERY_ONLY",
        "live_ingestion_enabled": False,
    }
