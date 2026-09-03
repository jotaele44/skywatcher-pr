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
        if not isinstance(row, dict):
            raise HTRContextError("HTR row must be an object")
        candidate_id = row.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id:
            raise HTRContextError("missing candidate_id")
        if candidate_id in seen:
            raise HTRContextError(f"duplicate candidate_id: {candidate_id}")
        seen.add(candidate_id)
        state = row.get("state")
        if state not in ALLOWED_STATES:
            raise HTRContextError(
                f"unsupported HTR state {state!r}; allowed: {sorted(ALLOWED_STATES)}"
            )
        if row.get("identity_state") != "DISTINCT_ENTITIES":
            raise HTRContextError("HTR context must preserve distinct entities")
        if row.get("downstream_semantics") != "CONTEXT_ONLY_NOT_IDENTITY":
            raise HTRContextError("missing HTR context-only contract")
        relation = row.get("relation_type")
        if not isinstance(relation, str) or not relation:
            raise HTRContextError("relation_type must be a non-empty string")
        if relation in FORBIDDEN_RELATIONS:
            raise HTRContextError("identity relation forbidden at Skywatcher boundary")
        source_id = row.get("source_observation_id")
        hydro_id = row.get("hydro_entity_id")
        if not isinstance(source_id, str) or not source_id:
            raise HTRContextError("source_observation_id must be a non-empty string")
        if not isinstance(hydro_id, str) or not hydro_id:
            raise HTRContextError("hydro_entity_id must be a non-empty string")
        if source_id == hydro_id:
            raise HTRContextError("HTR endpoints must remain distinct")
        evidence = row.get("evidence")
        if not isinstance(evidence, list) or not all(isinstance(item, dict) for item in evidence):
            raise HTRContextError("evidence must be a list of objects")
        accepted.append(
            {
                "candidate_id": candidate_id,
                "source_observation_id": source_id,
                "hydro_entity_id": hydro_id,
                "relation_type": relation,
                "evidence_state": state,
                "context_only": True,
                "can_influence_mission_classification": False,
                "can_establish_facility_identity": False,
                "can_establish_connectivity": False,
                "provenance": evidence,
            }
        )
    return sorted(accepted, key=lambda r: r["candidate_id"])
