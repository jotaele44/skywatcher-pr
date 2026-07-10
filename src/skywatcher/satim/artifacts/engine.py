from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .compound_artifacts import select_primary
from .models import AssessmentResult, confidence_level
from .restriction_gate import InterpretationRestrictionGate

ENGINE_VERSION = "1.0.0"
RULESET_VERSION = "satim-artifact-protocol-v1"
SCREENSHOT_TYPES = {"screenshot", "pdf_frame"}


class ArtifactAssessmentEngine:
    def __init__(self, taxonomy_path: str | Path | None = None):
        taxonomy_path = (
            Path(taxonomy_path)
            if taxonomy_path
            else Path(__file__).with_name("artifact_taxonomy_v1.json")
        )
        self.taxonomy = json.loads(taxonomy_path.read_text(encoding="utf-8"))
        self.valid_classes = {x["id"] for x in self.taxonomy["classes"]}
        self.gate = InterpretationRestrictionGate()

    def assess(self, payload: Mapping[str, Any]) -> AssessmentResult:
        candidates = list(payload.get("candidate_artifacts") or [])
        unknown = [x for x in candidates if x not in self.valid_classes]
        if unknown:
            raise ValueError(f"unknown artifact class(es): {unknown}")
        primary, contributing = select_primary(candidates)
        source = dict(payload.get("source") or {})
        raw_score = float(
            payload.get("classification_score", payload.get("confidence", {}).get("score", 0.5))
        )
        contradictions = tuple(str(x) for x in payload.get("contradictions", []))
        classification = max(0.0, min(1.0, raw_score - min(0.35, 0.08 * len(contradictions))))
        origin = float(payload.get("origin_confidence", classification))
        rules = []
        if source.get("source_type") in SCREENSHOT_TYPES and not payload.get(
            "raw_source_compared", False
        ):
            if origin > 0.74:
                rules.append("SCREENSHOT_ORIGIN_CAP_0_74")
            origin = min(origin, 0.74)
        restriction = self.gate.enforce(
            (primary, *contributing), payload.get("interpretation_restriction")
        ).restriction
        origin_layer = str(payload.get("origin_layer") or "unresolved")
        return AssessmentResult(
            primary,
            contributing,
            origin_layer,
            round(classification, 4),
            round(origin, 4),
            confidence_level(classification),
            restriction,
            contradictions,
            tuple(rules),
            payload.get("measurements", {}),
        )
