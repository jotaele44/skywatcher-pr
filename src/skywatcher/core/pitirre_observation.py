"""Lossless PITIRRE observation envelope adapters.

The envelope provides a common read/correlation surface without rewriting the
source-domain record. Every adapter retains the complete input row in payload
and records the originating legacy contract. It does not establish entity
identity, causation, or geometry authority.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Any

from .domain_registry import validate_domain_path

OBSERVATION_SCHEMA_VERSION = "pitirre-observation-v0.1"
ADAPTER_VERSION = "pitirre-observation-adapter-v0.1"


class ObservationAdapterError(ValueError):
    """Raised when a source row cannot be losslessly enveloped."""


@dataclass(frozen=True)
class PitirreObservation:
    schema_version: str
    observation_id: str
    domain: str
    subdomain: str | None
    network_type: str | None
    event_time_raw: str
    source_ref: dict[str, Any]
    spatial: dict[str, Any]
    evidence: dict[str, Any]
    payload: dict[str, Any]
    adapter: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _required_text(row: Mapping[str, Any], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value:
        raise ObservationAdapterError(f"{field} must be a non-empty string")
    return value


def _required_number(row: Mapping[str, Any], field: str) -> int | float:
    value = row.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ObservationAdapterError(f"{field} must be numeric")
    return value


def _envelope(
    *,
    row: Mapping[str, Any],
    observation_id: str,
    domain: str,
    subdomain: str,
    event_time_raw: str,
    source_ref: dict[str, Any],
    spatial: dict[str, Any],
    evidence: dict[str, Any],
    legacy_contract: str,
    network_type: str | None = None,
) -> PitirreObservation:
    validate_domain_path(
        domain,
        subdomain=subdomain,
        network_type=network_type,
    )
    return PitirreObservation(
        schema_version=OBSERVATION_SCHEMA_VERSION,
        observation_id=observation_id,
        domain=domain,
        subdomain=subdomain,
        network_type=network_type,
        event_time_raw=event_time_raw,
        source_ref=source_ref,
        spatial=spatial,
        evidence=evidence,
        payload=deepcopy(dict(row)),
        adapter={
            "adapter_version": ADAPTER_VERSION,
            "legacy_contract": legacy_contract,
        },
    )


def adapt_airspace_observation(row: Mapping[str, Any]) -> PitirreObservation:
    """Envelope one canonical legacy airspace observation without rewriting it."""

    observation_id = _required_text(row, "observation_id")
    event_time = _required_text(row, "event_datetime")
    source_id = _required_text(row, "source_id")
    lat = _required_number(row, "lat")
    lon = _required_number(row, "lon")

    return _envelope(
        row=row,
        observation_id=observation_id,
        domain="AIR",
        subdomain="AVIATION",
        event_time_raw=event_time,
        source_ref={
            "source_id": source_id,
            "source_type_raw": row.get("source_type"),
            "source_record_id": row.get("source_record_id"),
            "lineage_id": row.get("lineage_id"),
        },
        spatial={
            "mode": "SOURCE_POINT",
            "lat": lat,
            "lon": lon,
            "geometry_status_raw": row.get("geometry_status"),
        },
        evidence={
            "evidence_tier_raw": row.get("evidence_tier"),
            "confidence_raw": row.get("confidence"),
            "synthetic": row.get("synthetic"),
            "operational_use_allowed": None,
        },
        legacy_contract="airspace_observation",
    )


def adapt_maritime_baseline(row: Mapping[str, Any]) -> PitirreObservation:
    """Envelope one historical/context maritime record as WATER.MARITIME."""

    observation_id = _required_text(row, "record_id")
    event_time = _required_text(row, "observed_at")
    source_id = _required_text(row, "source")
    lat = _required_number(row, "lat")
    lon = _required_number(row, "lon")

    return _envelope(
        row=row,
        observation_id=observation_id,
        domain="WATER",
        subdomain="MARITIME",
        event_time_raw=event_time,
        source_ref={
            "source_id": source_id,
            "source_type_raw": row.get("mode"),
            "source_record_id": row.get("record_id"),
            "lineage_id": None,
        },
        spatial={
            "mode": "SOURCE_POINT",
            "lat": lat,
            "lon": lon,
            "geometry_status_raw": None,
        },
        evidence={
            "evidence_tier_raw": row.get("source_tier"),
            "confidence_raw": row.get("confidence"),
            "synthetic": None,
            "operational_use_allowed": row.get("operational_use_allowed"),
        },
        legacy_contract="maritime_baseline",
    )
