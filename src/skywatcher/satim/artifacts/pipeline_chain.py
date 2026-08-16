"""Chain SATIM pipeline layer signals into artifact-assessment payloads.

This module is pure (stdlib + sibling artifact modules only, no ``fr24``
imports) so it stays inside the ``satim`` module bucket without pulling the
pipeline into the artifacts package. The engine feeds it already-scored L5
candidate rows (from ``fr24.calibration.l5_tile_seam_shadow_calibration``)
and it returns a schema-valid assessment payload, or ``None`` when no L5
decision denotes an actual imagery artifact.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from .crosswalk import auto_derivable
from .engine import ENGINE_VERSION, RULESET_VERSION
from .models import confidence_level

# These four tables are now views over artifact_crosswalk_v1.json, which holds one
# `auto_derive` record per class covering decision, likelihood field, origin layer,
# requested restriction, and the rationale for that restriction. They were four parallel
# dicts that had to be edited in lockstep to add a single detector.
#
# Only decisions that denote an *artifact* appear. Other L5 decisions -- terrain shadow,
# ground feature, explainable infrastructure, indeterminate -- describe real or
# unresolved content and correctly produce no assessment.
#
# The restrictions are *requests* layered on the gate's mandatory minima; the gate only
# rejects weaker-than-minimum requests. Each request's justification lives with it in the
# crosswalk instead of in a comment that could drift from the value.
_AUTO_DERIVE = auto_derivable()

L5_DECISION_TO_CLASS = {
    decision: record["artifact_class"] for decision, record in _AUTO_DERIVE.items()
}
L5_DECISION_TO_LIKELIHOOD = {
    decision: record["likelihood_field"] for decision, record in _AUTO_DERIVE.items()
}
L5_CLASS_ORIGIN_LAYER = {
    record["artifact_class"]: record["origin_layer"] for record in _AUTO_DERIVE.values()
}
L5_CLASS_RESTRICTION = {
    record["artifact_class"]: record["requested_restriction"]
    for record in _AUTO_DERIVE.values()
}

# Numeric fields copied from a scored L5 candidate into measurements.
_MEASUREMENT_KEYS = (
    "tile_seam_likelihood",
    "cloud_shadow_likelihood",
    "terrain_shadow_likelihood",
    "persistent_ground_feature_likelihood",
    "orthogonal_artifact_score",
    "rectangular_patch_score",
    "context_suppression_score",
    "tile_corroborating_signal_count",
)


def _row_score(row: Mapping[str, Any], decision: str) -> float:
    key = L5_DECISION_TO_LIKELIHOOD[decision]
    try:
        return float(row.get(key, 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def build_assessment_from_l5(
    scored_rows: Sequence[Mapping[str, Any]],
    *,
    source_type: str = "screenshot",
    provenance_status: str = "partial",
) -> dict[str, Any] | None:
    """Derive a schema-valid assessment payload from scored L5 candidates.

    Picks the highest-likelihood candidate whose decision maps to a SATIM
    artifact class. Returns ``None`` when no candidate denotes an artifact.
    """
    best_index: int | None = None
    best_score = -1.0
    for index, row in enumerate(scored_rows):
        decision = str(row.get("decision", ""))
        if decision not in L5_DECISION_TO_CLASS:
            continue
        score = _row_score(row, decision)
        if score > best_score:
            best_score, best_index = score, index

    if best_index is None:
        return None

    row = scored_rows[best_index]
    decision = str(row["decision"])
    artifact_class = L5_DECISION_TO_CLASS[decision]
    score = max(0.0, min(1.0, best_score))

    measurements: dict[str, Any] = {}
    for key in _MEASUREMENT_KEYS:
        if key in row:
            try:
                measurements[key] = float(row[key])
            except (TypeError, ValueError):
                continue

    return {
        "assessment_id": f"auto-l5-{best_index:04d}-{artifact_class}",
        "source": {"source_type": source_type, "provenance_status": provenance_status},
        "roi": {"target": {"description": f"Auto-derived L5 candidate: {decision}"}},
        "candidate_artifacts": [artifact_class],
        "final_classification": artifact_class,
        "confidence": {"score": score, "level": confidence_level(score)},
        "origin_layer": L5_CLASS_ORIGIN_LAYER[artifact_class],
        "interpretation_restriction": L5_CLASS_RESTRICTION[artifact_class],
        "measurements": measurements,
        "analyst_notes": "Auto-derived from L5 tile-seam/shadow candidate classification.",
        "raw_source_compared": False,
    }


def build_ledger_entry(payload: Mapping[str, Any], result: Mapping[str, Any]) -> dict[str, Any]:
    """Shape an assessment result into a satim_confidence_ledger_entry_v1 record.

    ``ConfidenceLedger.append`` supplies ``previous_entry_hash`` and
    ``entry_hash``; every other required field is populated here.
    """
    canonical_input = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return {
        "ledger_id": str(uuid.uuid4()),
        "assessment_id": payload["assessment_id"],
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "engine_version": ENGINE_VERSION,
        "ruleset_version": RULESET_VERSION,
        "input_sha256": hashlib.sha256(canonical_input).hexdigest(),
        "support": [],
        "contradictions": [{"detail": c} for c in result["contradictions"]],
        "caps": list(result["rules_triggered"]),
        "class_score": result["classification_confidence"],
        "origin_score": result["origin_confidence"],
        "decision": {
            "primary_class": result["primary_class"],
            "contributing_classes": result["contributing_classes"],
            "confidence_level": result["confidence_level"],
            "interpretation_restriction": result["interpretation_restriction"],
            "origin_layer": result["origin_layer"],
        },
    }
