#!/usr/bin/env python3
"""Bind Skywatcher producer records to the federation spatial identity plane.

The adapter consumes explicit aviation identifiers only. Track points,
proximity, route intersection, nearest airfield, imagery correlation, or terrain
relationships remain evidence and cannot create canonical identity.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

CONTRACT_VERSION = "federation-spatial-contract/1.1"
PRODUCER = "skywatcher-pr"
FORBIDDEN_SOLE_BASIS = {
    "NAME_ONLY",
    "NORMALIZED_NAME_ONLY",
    "NEAREST_ONLY",
    "PROXIMITY_ONLY",
    "TRACK_INTERSECTION",
    "ROUTE_INTERSECTION",
    "IMAGERY_CORRELATION_ONLY",
    "TERRAIN_PROXIMITY",
}
STRONG_BASIS = {"FAA_LID", "ICAO_ID", "FAA_SITE_NUMBER", "AUTHORITATIVE_BINDING", "CERTIFIED_CROSSWALK"}


def stable_key(namespace: str, value: Any) -> str:
    text = "" if value is None else str(value).strip().upper()
    if not namespace or not text:
        raise ValueError("stable namespace and value are required")
    return f"{PRODUCER}:{namespace}:{text}"


def bind_record(
    record: Mapping[str, Any],
    *,
    id_field: str,
    id_namespace: str,
    canonical_index: Mapping[str, Sequence[str]],
    evidence_basis: Sequence[str],
) -> dict[str, Any]:
    key = stable_key(id_namespace, record.get(id_field))
    basis = {str(v) for v in evidence_basis}
    if not basis:
        raise ValueError("evidence_basis is required")
    if basis <= FORBIDDEN_SOLE_BASIS:
        raise ValueError("aviation heuristic-only evidence cannot create identity")

    candidates = sorted(set(str(v) for v in canonical_index.get(key, ()) if str(v)))
    if not candidates:
        return {
            "contract_version": CONTRACT_VERSION,
            "producer_repo": PRODUCER,
            "producer_key": key,
            "canonical_ids": [],
            "cardinality": "0:1",
            "identity_state": "UNRESOLVED",
            "identity_semantics": "CANDIDATE_NOT_IDENTITY",
            "evidence_basis": sorted(basis),
        }
    if len(candidates) > 1:
        return {
            "contract_version": CONTRACT_VERSION,
            "producer_repo": PRODUCER,
            "producer_key": key,
            "canonical_ids": candidates,
            "cardinality": "1:N",
            "identity_state": "UNRESOLVED",
            "identity_semantics": "CANDIDATE_NOT_IDENTITY",
            "evidence_basis": sorted(basis),
        }
    if not (basis & STRONG_BASIS):
        raise ValueError("single aviation candidate requires FAA/ICAO/authoritative evidence")

    return {
        "contract_version": CONTRACT_VERSION,
        "producer_repo": PRODUCER,
        "producer_key": key,
        "canonical_ids": candidates,
        "cardinality": "1:1",
        "identity_state": "PROVISIONAL",
        "identity_semantics": "IDENTITY_BINDING",
        "evidence_basis": sorted(basis),
    }
