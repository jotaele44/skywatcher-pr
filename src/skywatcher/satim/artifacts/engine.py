from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from skywatcher.core.lenses import (
    LensRegistry,
    ObjectiveProfile,
    ThresholdRegistry,
    evaluate_coverage,
)

from .compound_artifacts import select_primary
from .models import AssessmentResult, confidence_level
from .restriction_gate import InterpretationRestrictionGate

ENGINE_VERSION = "1.1.0"
RULESET_VERSION = "satim-artifact-protocol-v1"
SCREENSHOT_TYPES = {"screenshot", "pdf_frame"}

# Which lens each taxonomy class belongs to. The engine arbitrates over candidates it
# is handed rather than running detectors itself, so this is how a class is traced back
# to the lens that should have produced it.
CLASS_LENS = dict.fromkeys(
    (
        "SATIM-A01", "SATIM-A02", "SATIM-A03", "SATIM-A04", "SATIM-A05", "SATIM-A06",
        "SATIM-A07", "SATIM-A08", "SATIM-A09", "SATIM-A10", "SATIM-A11", "SATIM-A12",
    ),
    "satim.image_artifacts",
)


class ArtifactAssessmentEngine:
    """Arbitrates candidate artifact classes into a single assessment.

    Note this engine does not run detectors; it scores and reconciles evidence a caller
    supplies. Lens coverage therefore reports what the *run* covered, not what this
    call computed.

    All lens arguments are optional. Omit them and the result matches v1 exactly, which
    is what keeps the existing callers and the v1 schema working.
    """

    def __init__(
        self,
        taxonomy_path: str | Path | None = None,
        lens_registry: LensRegistry | None = None,
        objective_profile: ObjectiveProfile | None = None,
        threshold_registry: ThresholdRegistry | None = None,
    ):
        taxonomy_path = (
            Path(taxonomy_path)
            if taxonomy_path
            else Path(__file__).with_name("artifact_taxonomy_v1.json")
        )
        self.taxonomy = json.loads(taxonomy_path.read_text(encoding="utf-8"))
        self.valid_classes = {x["id"] for x in self.taxonomy["classes"]}
        self.gate = InterpretationRestrictionGate()
        self.lens_registry = lens_registry
        self.objective_profile = objective_profile
        self.threshold_registry = threshold_registry

    def _coverage(
        self, payload: Mapping[str, Any], candidates: list[str]
    ) -> tuple[tuple[str, ...], tuple[Mapping[str, Any], ...], tuple[str, ...]]:
        """Lens ids, per-lens coverage, and unmet requirements for this assessment."""
        if self.lens_registry is None or self.objective_profile is None:
            return (), (), ()

        supplied = dict(payload.get("lens_parameters") or {})
        available = {
            lens_id: list(inputs)
            for lens_id, inputs in (payload.get("lens_inputs") or {}).items()
        }
        # A lens whose classes appear among the candidates demonstrably ran, even if the
        # caller did not say so explicitly.
        produced = dict(payload.get("lens_produced") or {})
        for class_id in candidates:
            lens_id = CLASS_LENS.get(class_id)
            if lens_id:
                produced.setdefault(lens_id, True)

        report = evaluate_coverage(
            self.objective_profile,
            self.lens_registry,
            run_id=str(payload.get("assessment_id") or "unspecified"),
            supplied_parameters=supplied,
            available_inputs=available,
            produced=produced,
            applicable=dict(payload.get("lens_applicable") or {}),
            generated_by=f"ArtifactAssessmentEngine/{ENGINE_VERSION}",
        )
        # "Applied" means ran, not merely named by the objective profile. report.entries
        # covers every lens the profile lists — including ones that were MISSING or
        # NOT_APPLICABLE and so never executed — so it is the wrong source for this.
        # `produced` is exactly the set of lenses this call has positive evidence for
        # (explicit lens_produced entries plus candidate-derived ones); a lens present
        # there with produced=False still ran, it just found nothing.
        applied = tuple(lens_id for lens_id in produced if lens_id in self.lens_registry)
        coverage = tuple(entry.to_dict() for entry in report.entries)
        return applied, coverage, report.blocking_reasons

    def _thresholds(self, class_ids: tuple[str, ...]) -> tuple[Mapping[str, Any], ...]:
        """Provenance stamps for thresholds the lenses behind these classes execute."""
        if self.threshold_registry is None or self.lens_registry is None:
            return ()
        lens_ids = {CLASS_LENS[c] for c in class_ids if c in CLASS_LENS}
        stamps: list[Mapping[str, Any]] = []
        seen: set[str] = set()
        for lens_id in sorted(lens_ids):
            if lens_id not in self.lens_registry:
                continue
            for threshold_id in self.lens_registry.get(lens_id).threshold_ids:
                if threshold_id in seen:
                    continue
                seen.add(threshold_id)
                stamps.append(self.threshold_registry.get(threshold_id).stamp())
        return tuple(stamps)

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

        # Keep the whole decision, not just the restriction. A weakening request that
        # the gate refuses used to vanish silently.
        decision = self.gate.enforce(
            (primary, *contributing), payload.get("interpretation_restriction")
        )
        if not decision.allowed:
            rules.append("RESTRICTION_REQUEST_REJECTED")

        applied, coverage, unmet = self._coverage(payload, candidates)
        thresholds = self._thresholds((primary, *contributing))

        origin_layer = str(payload.get("origin_layer") or "unresolved")
        return AssessmentResult(
            primary,
            contributing,
            origin_layer,
            round(classification, 4),
            round(origin, 4),
            confidence_level(classification),
            decision.restriction,
            contradictions,
            tuple(rules),
            payload.get("measurements", {}),
            lenses_applied=applied,
            lens_coverage=coverage,
            unsatisfied_requirements=unmet,
            thresholds_applied=thresholds,
            restriction_allowed=decision.allowed,
            restriction_reason=decision.reason,
        )
