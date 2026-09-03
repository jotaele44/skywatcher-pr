"""Canonical source taxonomy for console and observation contracts.

The mapper is additive: legacy ``source_type`` values are preserved while the
canonical provenance dimensions are populated. Unknown inputs remain explicit
``unknown`` values and receive QA flags rather than being force-classified.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

SOURCE_TAXONOMY_VERSION = "0.1.0"

SOURCE_FAMILIES = (
    "operational_position",
    "screenshot_evidence",
    "official_record",
    "manual_field",
    "secondary_reference",
    "synthetic_test",
    "unknown",
)
SOURCE_METHODS = (
    "adsb",
    "mlat",
    "satellite_adsb",
    "radar",
    "uat",
    "flarm",
    "screenshot_ocr",
    "manual_entry",
    "registry_match",
    "official_feed",
    "derived_fusion",
    "secondary_report",
    "unknown",
)
DATA_RIGHTS = (
    "owned",
    "licensed",
    "public_official",
    "user_supplied",
    "derived",
    "synthetic",
    "unknown",
)
OPERATIONAL_MODES = ("live", "delayed", "historical", "batch", "evidence_only", "unknown")

LEGACY_SOURCE_MAPPING: dict[str, dict[str, str]] = {
    "screenshot": {
        "source_family": "screenshot_evidence",
        "source_method": "screenshot_ocr",
        "data_rights": "user_supplied",
        "operational_mode": "evidence_only",
    },
    "adsb": {
        "source_family": "operational_position",
        "source_method": "adsb",
        "data_rights": "unknown",
        "operational_mode": "historical",
    },
    "radar": {
        "source_family": "operational_position",
        "source_method": "radar",
        "data_rights": "unknown",
        "operational_mode": "historical",
    },
    "official": {
        "source_family": "official_record",
        "source_method": "official_feed",
        "data_rights": "public_official",
        "operational_mode": "batch",
    },
    "field_note": {
        "source_family": "manual_field",
        "source_method": "manual_entry",
        "data_rights": "user_supplied",
        "operational_mode": "evidence_only",
    },
    "secondary": {
        "source_family": "secondary_reference",
        "source_method": "secondary_report",
        "data_rights": "unknown",
        "operational_mode": "evidence_only",
    },
}

FRONTEND_ALIAS_MAPPING: dict[str, dict[str, str]] = {
    "fr24_screenshot": LEGACY_SOURCE_MAPPING["screenshot"],
    "fr24_track": {
        "source_family": "screenshot_evidence",
        "source_method": "derived_fusion",
        "data_rights": "derived",
        "operational_mode": "evidence_only",
    },
    "manual_entry": LEGACY_SOURCE_MAPPING["field_note"],
    "registry_match": {
        "source_family": "official_record",
        "source_method": "registry_match",
        "data_rights": "public_official",
        "operational_mode": "batch",
    },
}


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _qa_flags(row: Mapping[str, Any]) -> list[str]:
    raw = row.get("qa_flags") or []
    if isinstance(raw, str):
        return [part.strip() for part in raw.split(",") if part.strip()]
    if isinstance(raw, (list, tuple, set)):
        return [str(item).strip() for item in raw if str(item).strip()]
    return []


def build_provenance(row: Mapping[str, Any]) -> tuple[dict[str, str | None], list[str]]:
    """Build canonical provenance and return it with accumulated QA flags."""

    legacy = _text(row.get("source_type")).lower()
    alias = _text(row.get("source_alias")).lower()
    mapping = LEGACY_SOURCE_MAPPING.get(legacy) or FRONTEND_ALIAS_MAPPING.get(alias)
    qa_flags = _qa_flags(row)

    if mapping is None and legacy in FRONTEND_ALIAS_MAPPING:
        mapping = FRONTEND_ALIAS_MAPPING[legacy]
    if mapping is None:
        mapping = {
            "source_family": "unknown",
            "source_method": "unknown",
            "data_rights": "unknown",
            "operational_mode": "unknown",
        }
        if "unknown_source_type" not in qa_flags:
            qa_flags.append("unknown_source_type")

    synthetic = bool(row.get("synthetic") or row.get("synthetic_flag"))
    source_family = _text(row.get("source_family")) or mapping["source_family"]
    source_method = _text(row.get("source_method")) or mapping["source_method"]
    data_rights = _text(row.get("data_rights")) or mapping["data_rights"]
    operational_mode = _text(row.get("operational_mode")) or mapping["operational_mode"]

    if synthetic:
        source_family = "synthetic_test"
        data_rights = "synthetic"
        operational_mode = "batch"

    provider = (
        _text(row.get("source_provider"))
        or _text(row.get("provider"))
        or _text(row.get("source_id"))
        or "unknown"
    )
    source_record_id = (
        _text(row.get("source_record_id"))
        or _text(row.get("source_id"))
        or _text(row.get("observation_id"))
        or _text(row.get("event_id"))
        or "unknown"
    )
    lineage_id = _text(row.get("lineage_id")) or source_record_id

    provenance: dict[str, str | None] = {
        "source_family": source_family if source_family in SOURCE_FAMILIES else "unknown",
        "source_provider": provider,
        "source_method": source_method if source_method in SOURCE_METHODS else "unknown",
        "data_rights": data_rights if data_rights in DATA_RIGHTS else "unknown",
        "operational_mode": operational_mode if operational_mode in OPERATIONAL_MODES else "unknown",
        "source_record_id": source_record_id,
        "lineage_id": lineage_id,
        "retrieved_at_utc": row.get("retrieved_at_utc"),
        "license_or_terms_ref": row.get("license_or_terms_ref"),
        "attribution": row.get("attribution"),
    }
    return provenance, qa_flags


def normalize_observation(row: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy with additive canonical source fields and QA flags."""

    normalized = dict(row)
    provenance, qa_flags = build_provenance(row)
    normalized.update(
        {
            "source_family": provenance["source_family"],
            "source_provider": provenance["source_provider"],
            "source_method": provenance["source_method"],
            "data_rights": provenance["data_rights"],
            "operational_mode": provenance["operational_mode"],
            "source_record_id": provenance["source_record_id"],
            "source_taxonomy_version": SOURCE_TAXONOMY_VERSION,
            "qa_flags": qa_flags,
        }
    )
    return normalized
