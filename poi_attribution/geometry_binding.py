"""Geometry-binding gate for POI identity candidates.

Discovery is deliberately separated from identity. Search rank, proximity,
category agreement, and nearest-neighbour results can generate candidates but
cannot bind a candidate name to the selected target geometry.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DiscoverySignal(str, Enum):
    NEAREST_ONLY = "NEAREST_ONLY"
    PROXIMITY_ONLY = "PROXIMITY_ONLY"
    SEARCH_RANK = "SEARCH_RANK"
    SAME_CATEGORY = "SAME_CATEGORY"
    UNBOUND_MAP_LABEL = "UNBOUND_MAP_LABEL"


class BindingEvidence(str, Enum):
    PARCEL_JOIN = "PARCEL_JOIN"
    POINT_IN_POLYGON = "POINT_IN_POLYGON"
    AUTHORITATIVE_COORDINATE = "AUTHORITATIVE_COORDINATE"
    AUTHORITATIVE_ADDRESS = "AUTHORITATIVE_ADDRESS"
    DISTINCT_PROPERTY = "DISTINCT_PROPERTY"
    NONE = "NONE"


class BindingDecision(str, Enum):
    BOUND = "BOUND"
    REJECTED = "REJECTED"
    UNRESOLVED = "UNRESOLVED"


_AFFIRMATIVE_BINDINGS = {
    BindingEvidence.PARCEL_JOIN,
    BindingEvidence.POINT_IN_POLYGON,
    BindingEvidence.AUTHORITATIVE_COORDINATE,
    BindingEvidence.AUTHORITATIVE_ADDRESS,
}


@dataclass(frozen=True)
class GeometryBindingResult:
    candidate_name: str
    target_geometry_id: str
    decision: BindingDecision
    reason: str


def evaluate_geometry_binding(
    *,
    candidate_name: str,
    target_geometry_id: str,
    candidate_geometry_id: str | None,
    binding_evidence: BindingEvidence,
    discovery_signals: frozenset[DiscoverySignal] = frozenset(),
) -> GeometryBindingResult:
    """Adjudicate whether a discovered name is bound to the frozen target.

    ``target_geometry_id`` is mandatory and represents the geometry lock captured
    before candidate discovery. ``facility_class`` is intentionally absent from
    this API so Engine A morphology cannot influence an identity decision.
    """
    if not target_geometry_id.strip():
        raise ValueError("target geometry must be locked before candidate discovery")
    if not candidate_name.strip():
        raise ValueError("candidate_name must be non-empty")

    if binding_evidence is BindingEvidence.DISTINCT_PROPERTY:
        return GeometryBindingResult(
            candidate_name,
            target_geometry_id,
            BindingDecision.REJECTED,
            "distinct-property evidence falsifies identity",
        )

    if candidate_geometry_id and candidate_geometry_id != target_geometry_id:
        return GeometryBindingResult(
            candidate_name,
            target_geometry_id,
            BindingDecision.REJECTED,
            "candidate geometry differs from frozen target geometry",
        )

    if binding_evidence in _AFFIRMATIVE_BINDINGS:
        return GeometryBindingResult(
            candidate_name,
            target_geometry_id,
            BindingDecision.BOUND,
            f"affirmative geometry binding: {binding_evidence.value}",
        )

    if discovery_signals:
        signals = ",".join(sorted(signal.value for signal in discovery_signals))
        return GeometryBindingResult(
            candidate_name,
            target_geometry_id,
            BindingDecision.UNRESOLVED,
            f"discovery-only signals are insufficient for identity: {signals}",
        )

    return GeometryBindingResult(
        candidate_name,
        target_geometry_id,
        BindingDecision.UNRESOLVED,
        "no affirmative geometry binding evidence",
    )
