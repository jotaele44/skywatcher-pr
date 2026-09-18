#!/usr/bin/env python3
"""Bind Skywatcher producer records to the federation spatial identity plane.

The adapter consumes explicit aviation identifiers only. Track points,
proximity, route intersection, nearest airfield, imagery correlation, or terrain
relationships remain evidence and cannot create canonical identity.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

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
STRONG_BASIS = {
    "FAA_LID",
    "ICAO_ID",
    "FAA_SITE_NUMBER",
    "AUTHORITATIVE_BINDING",
    "CERTIFIED_CROSSWALK",
}


def stable_key(namespace: str, value: Any) -> str:
    if not isinstance(namespace, str) or not namespace.strip():
        raise ValueError("stable namespace and value are required")
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("stable namespace and value are required")
    text = str(value).strip().upper()
    if not text:
        raise ValueError("stable namespace and value are required")
    return f"{PRODUCER}:{namespace.strip()}:{text}"


def normalized_basis(evidence_basis: Sequence[str]) -> tuple[list[str], set[str]]:
    if isinstance(evidence_basis, (str, bytes)) or not isinstance(evidence_basis, Sequence):
        raise ValueError("evidence_basis must be an array of non-empty strings")
    raw_basis = list(evidence_basis)
    if not raw_basis or any(not isinstance(value, str) or not value.strip() for value in raw_basis):
        raise ValueError("evidence_basis must be an array of non-empty strings")
    return raw_basis, {value.strip().upper() for value in raw_basis}


def candidate_ids(canonical_index: Mapping[str, Sequence[str]], key: str) -> list[str]:
    if not isinstance(canonical_index, Mapping):
        raise ValueError("canonical_index must be an object")
    values = canonical_index.get(key, ())
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ValueError(f"canonical_index[{key!r}] must be an array")
    candidates: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"canonical_index[{key!r}] contains an invalid canonical ID")
        candidates.append(value.strip())
    if len(candidates) != len(set(candidates)):
        raise ValueError(f"canonical_index[{key!r}] contains duplicate canonical IDs")
    return sorted(candidates)


def bind_record(
    record: Mapping[str, Any],
    *,
    id_field: str,
    id_namespace: str,
    canonical_index: Mapping[str, Sequence[str]],
    evidence_basis: Sequence[str],
) -> dict[str, Any]:
    key = stable_key(id_namespace, record.get(id_field))
    raw_basis, basis = normalized_basis(evidence_basis)
    if basis <= FORBIDDEN_SOLE_BASIS:
        raise ValueError("aviation heuristic-only evidence cannot create identity")

    candidates = candidate_ids(canonical_index, key)
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
            "evidence_basis_raw": raw_basis,
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
            "evidence_basis_raw": raw_basis,
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
        "evidence_basis_raw": raw_basis,
    }
