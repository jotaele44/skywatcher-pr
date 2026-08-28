"""Consume TheHub HTR rows as context only.

Hydro-toponym recurrence may enrich environmental/site context but may never by
itself classify an aircraft mission, bind a facility identity, or create a
hydraulic/electrical connection.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

ALLOWED_STATES = {"CONTEXT_SUPPORTED", "ADJUDICATED"}
FORBIDDEN_RELATIONS = {"SAME_AS", "IDENTICAL_TO", "CANONICAL_IDENTITY"}


class HTRContextError(ValueError):
    pass


def consume_htr_context(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    accepted: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        candidate_id = row.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id:
            raise HTRContextError("missing candidate_id")
        if candidate_id in seen:
            raise HTRContextError(f"duplicate candidate_id: {candidate_id}")
        seen.add(candidate_id)
        if row.get("state") not in ALLOWED_STATES:
            raise HTRContextError("HTR discovery-only row cannot enter Skywatcher context")
        if row.get("identity_state") != "DISTINCT_ENTITIES":
            raise HTRContextError("HTR context must preserve distinct entities")
        if row.get("downstream_semantics") != "CONTEXT_ONLY_NOT_IDENTITY":
            raise HTRContextError("missing HTR context-only contract")
        if row.get("relation_type") in FORBIDDEN_RELATIONS:
            raise HTRContextError("identity relation forbidden at Skywatcher boundary")
        accepted.append({
            "candidate_id": candidate_id,
            "source_observation_id": row.get("source_observation_id"),
            "hydro_entity_id": row.get("hydro_entity_id"),
            "relation_type": row.get("relation_type"),
            "evidence_state": row.get("state"),
            "context_only": True,
            "can_influence_mission_classification": False,
            "can_establish_facility_identity": False,
            "can_establish_connectivity": False,
            "provenance": row.get("evidence") or [],
        })
    return sorted(accepted, key=lambda r: r["candidate_id"])
