"""Data model for analysis lenses, objective profiles, and run coverage.

A *lens* is one declarative analytical objective — "look for tile seams", "look for
surface hydrology" — bound to exactly one owning domain, with its required inputs,
parameters, measurements, and emitted classes stated up front. An *objective profile*
names the set of lenses a run must satisfy. *Coverage* is the per-run record of which
lenses actually ran, which degraded, and which could not run at all.

The point of stating this as data rather than code: adding a parameter or a rule
becomes a config edit, not a Python edit across several modules that then drift.

Owner and stage are validated against the frozen ontology (ADR v2.0 section 3): a lens
belongs to one domain, and CORRIM is the only owner permitted to combine SATIM and
FPIM outputs. Nothing here enforces the import boundary — tests/test_module_boundaries.py
does that — but a lens declaring the wrong owner is rejected at load time.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

# The two halves of the pipeline. A lens belongs to exactly one; cross-domain work is
# a CORRIM lens that consumes both halves' frozen outputs, never a lens spanning them.
STAGE_FLIGHT = "flight_data_collection"
STAGE_SATELLITE = "satellite_image_processing"
STAGE_CROSS_DOMAIN = "cross_domain"
STAGES = (STAGE_FLIGHT, STAGE_SATELLITE, STAGE_CROSS_DOMAIN)

# Canonical owners from the term ownership matrix. RLSM is a pipeline under Core
# governance rather than a peer analytical domain (ADR v2.0 section 1), but it owns
# extraction lenses, so it appears here.
OWNERS = ("Core", "RLSM", "SATIM", "FPIM", "CORRIM")

LENS_STATUSES = ("experimental", "active", "deprecated")

# Mirrors satim.artifacts.restriction_gate.ORDER. Duplicated as a tuple rather than
# imported because core must not import satim (ADR v2.0 section 3.1); the registry
# test asserts the two stay in agreement.
RESTRICTIONS = (
    "NONE",
    "SPECTRAL_ONLY_DEGRADED",
    "GEOMETRY_DEGRADED",
    "OBJECT_LEVEL_PROHIBITED",
    "ALL_INFERENCE_SUSPENDED",
)

# The ten orthogonal evidence axes (ADR v2.0 section 5). A lens declares which it must
# populate; collapsing any two of them is the failure mode the axes exist to prevent.
EVIDENCE_AXES = (
    "evidence_tier",
    "visibility_class",
    "provenance_status",
    "source_availability",
    "geometry_status",
    "temporal_status",
    "review_status",
    "hypothesis_status",
    "confidence_score",
    "review_priority",
)

SATISFIED = "SATISFIED"
DEGRADED = "DEGRADED"
MISSING = "MISSING"
NOT_APPLICABLE = "NOT_APPLICABLE"
COVERAGE_STATES = (SATISFIED, DEGRADED, MISSING, NOT_APPLICABLE)

PARAMETER_KINDS = ("number", "integer", "string", "boolean", "enum", "array", "path")


def _tuple(values: Sequence[str] | None) -> tuple[str, ...]:
    return tuple(str(v) for v in (values or ()))


@dataclass(frozen=True)
class ParameterSpec:
    """One input knob a lens needs, and what happens when it is absent.

    ``degraded_behavior`` is mandatory for optional parameters and is the whole point
    of the type: a missing optional parameter must produce an explicit recorded
    degradation, never a silent fallback.
    """

    parameter_id: str
    name: str
    kind: str
    required: bool = True
    unit: str | None = None
    default: Any = None
    allowed_values: tuple[str, ...] = ()
    threshold_id: str | None = None
    description: str = ""
    degraded_behavior: str = ""

    def __post_init__(self) -> None:
        if not self.parameter_id:
            raise ValueError("parameter_id is required")
        if self.kind not in PARAMETER_KINDS:
            raise ValueError(f"{self.parameter_id}: unknown parameter kind {self.kind!r}")
        if self.kind == "enum" and not self.allowed_values:
            raise ValueError(f"{self.parameter_id}: enum parameter needs allowed_values")
        if not self.required and not self.degraded_behavior:
            raise ValueError(
                f"{self.parameter_id}: optional parameters must declare degraded_behavior "
                "so an absent value produces a recorded degradation, not a silent default"
            )

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> ParameterSpec:
        return cls(
            parameter_id=str(data.get("parameter_id") or data.get("id") or ""),
            name=str(data.get("name") or data.get("parameter_id") or ""),
            kind=str(data.get("kind") or "string"),
            required=bool(data.get("required", True)),
            unit=(str(data["unit"]) if data.get("unit") is not None else None),
            default=data.get("default"),
            allowed_values=_tuple(data.get("allowed_values")),
            threshold_id=(
                str(data["threshold_id"]) if data.get("threshold_id") is not None else None
            ),
            description=str(data.get("description") or ""),
            degraded_behavior=str(data.get("degraded_behavior") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "parameter_id": self.parameter_id,
            "name": self.name,
            "kind": self.kind,
            "required": self.required,
            "unit": self.unit,
            "default": self.default,
            "allowed_values": list(self.allowed_values),
            "threshold_id": self.threshold_id,
            "description": self.description,
            "degraded_behavior": self.degraded_behavior,
        }


@dataclass(frozen=True)
class LensSpec:
    """One analytical objective, owned by exactly one domain."""

    lens_id: str
    name: str
    owner: str
    stage: str
    objective: str
    status: str = "experimental"
    version: str = "1.0.0"
    required_parameters: tuple[ParameterSpec, ...] = ()
    optional_parameters: tuple[ParameterSpec, ...] = ()
    required_inputs: tuple[str, ...] = ()
    measurements: tuple[str, ...] = ()
    emits: tuple[str, ...] = ()
    interpretation_restriction_minimum: str = "NONE"
    prohibited_claims: tuple[str, ...] = ()
    evidence_axes_required: tuple[str, ...] = ()
    threshold_ids: tuple[str, ...] = ()
    contradiction_tests: tuple[str, ...] = ()
    checksum_sha256: str | None = None

    def __post_init__(self) -> None:
        if not self.lens_id:
            raise ValueError("lens_id is required")
        if self.owner not in OWNERS:
            raise ValueError(f"{self.lens_id}: unknown owner {self.owner!r}")
        if self.stage not in STAGES:
            raise ValueError(f"{self.lens_id}: unknown stage {self.stage!r}")
        if self.status not in LENS_STATUSES:
            raise ValueError(f"{self.lens_id}: unknown status {self.status!r}")
        if self.interpretation_restriction_minimum not in RESTRICTIONS:
            raise ValueError(
                f"{self.lens_id}: unknown interpretation restriction "
                f"{self.interpretation_restriction_minimum!r}"
            )
        unknown_axes = set(self.evidence_axes_required) - set(EVIDENCE_AXES)
        if unknown_axes:
            raise ValueError(f"{self.lens_id}: unknown evidence axes {sorted(unknown_axes)}")
        if not self.objective:
            raise ValueError(f"{self.lens_id}: objective is required")
        # Only CORRIM may declare a cross-domain lens (ADR v2.0 section 3).
        if self.stage == STAGE_CROSS_DOMAIN and self.owner != "CORRIM":
            raise ValueError(
                f"{self.lens_id}: only CORRIM may own a cross_domain lens, not {self.owner}"
            )
        ids = [p.parameter_id for p in self.all_parameters()]
        if len(ids) != len(set(ids)):
            raise ValueError(f"{self.lens_id}: duplicate parameter_id")

    def all_parameters(self) -> tuple[ParameterSpec, ...]:
        return tuple(self.required_parameters) + tuple(self.optional_parameters)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> LensSpec:
        def params(key: str, required: bool) -> tuple[ParameterSpec, ...]:
            raw = data.get(key) or ()
            out = []
            for item in raw:
                merged = dict(item)
                merged.setdefault("required", required)
                out.append(ParameterSpec.from_mapping(merged))
            return tuple(out)

        return cls(
            lens_id=str(data.get("lens_id") or ""),
            name=str(data.get("name") or data.get("lens_id") or ""),
            owner=str(data.get("owner") or ""),
            stage=str(data.get("stage") or ""),
            objective=str(data.get("objective") or ""),
            status=str(data.get("status") or "experimental"),
            version=str(data.get("version") or "1.0.0"),
            required_parameters=params("required_parameters", True),
            optional_parameters=params("optional_parameters", False),
            required_inputs=_tuple(data.get("required_inputs")),
            measurements=_tuple(data.get("measurements")),
            emits=_tuple(data.get("emits")),
            interpretation_restriction_minimum=str(
                data.get("interpretation_restriction_minimum") or "NONE"
            ),
            prohibited_claims=_tuple(data.get("prohibited_claims")),
            evidence_axes_required=_tuple(data.get("evidence_axes_required")),
            threshold_ids=_tuple(data.get("threshold_ids")),
            contradiction_tests=_tuple(data.get("contradiction_tests")),
            checksum_sha256=(
                str(data["checksum_sha256"]) if data.get("checksum_sha256") else None
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "lens_id": self.lens_id,
            "name": self.name,
            "owner": self.owner,
            "stage": self.stage,
            "objective": self.objective,
            "status": self.status,
            "version": self.version,
            "required_parameters": [p.to_dict() for p in self.required_parameters],
            "optional_parameters": [p.to_dict() for p in self.optional_parameters],
            "required_inputs": list(self.required_inputs),
            "measurements": list(self.measurements),
            "emits": list(self.emits),
            "interpretation_restriction_minimum": self.interpretation_restriction_minimum,
            "prohibited_claims": list(self.prohibited_claims),
            "evidence_axes_required": list(self.evidence_axes_required),
            "threshold_ids": list(self.threshold_ids),
            "contradiction_tests": list(self.contradiction_tests),
            "checksum_sha256": self.checksum_sha256,
        }


@dataclass(frozen=True)
class ObjectiveProfile:
    """The set of lenses a run must satisfy before it may be reported complete."""

    profile_id: str
    name: str
    version: str = "1.0.0"
    status: str = "experimental"
    stages: tuple[str, ...] = ()
    required_lenses: tuple[str, ...] = ()
    optional_lenses: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.profile_id:
            raise ValueError("profile_id is required")
        unknown = set(self.stages) - set(STAGES)
        if unknown:
            raise ValueError(f"{self.profile_id}: unknown stage(s) {sorted(unknown)}")
        overlap = set(self.required_lenses) & set(self.optional_lenses)
        if overlap:
            raise ValueError(
                f"{self.profile_id}: lens(es) both required and optional: {sorted(overlap)}"
            )
        if not self.required_lenses:
            raise ValueError(
                f"{self.profile_id}: a profile with no required lenses cannot gate anything"
            )

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> ObjectiveProfile:
        return cls(
            profile_id=str(data.get("profile_id") or ""),
            name=str(data.get("name") or data.get("profile_id") or ""),
            version=str(data.get("version") or "1.0.0"),
            status=str(data.get("status") or "experimental"),
            stages=_tuple(data.get("stages")),
            required_lenses=_tuple(data.get("required_lenses")),
            optional_lenses=_tuple(data.get("optional_lenses")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "name": self.name,
            "version": self.version,
            "status": self.status,
            "stages": list(self.stages),
            "required_lenses": list(self.required_lenses),
            "optional_lenses": list(self.optional_lenses),
        }


@dataclass(frozen=True)
class LensCoverage:
    """What one lens actually did on one run.

    ``reason`` is mandatory for every non-satisfied state. "It didn't run" without a
    stated cause is the outcome this record exists to make impossible.
    """

    lens_id: str
    state: str
    unmet_parameters: tuple[str, ...] = ()
    reason: str = ""
    method_version: str = ""
    thresholds_applied: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if self.state not in COVERAGE_STATES:
            raise ValueError(f"{self.lens_id}: unknown coverage state {self.state!r}")
        if self.state != SATISFIED and not self.reason:
            raise ValueError(f"{self.lens_id}: state {self.state} requires a reason")

    def to_dict(self) -> dict[str, Any]:
        return {
            "lens_id": self.lens_id,
            "state": self.state,
            "unmet_parameters": list(self.unmet_parameters),
            "reason": self.reason,
            "method_version": self.method_version,
            "thresholds_applied": [dict(t) for t in self.thresholds_applied],
        }


@dataclass(frozen=True)
class CoverageReport:
    """Whether a run met its objective, and precisely what is missing if not."""

    profile_id: str
    run_id: str
    entries: tuple[LensCoverage, ...] = ()
    complete: bool = False
    blocking_reasons: tuple[str, ...] = ()
    generated_by: str = ""
    extras: Mapping[str, Any] = field(default_factory=dict)

    def entry(self, lens_id: str) -> LensCoverage | None:
        return next((e for e in self.entries if e.lens_id == lens_id), None)

    def states(self) -> dict[str, str]:
        return {e.lens_id: e.state for e in self.entries}

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "run_id": self.run_id,
            "entries": [e.to_dict() for e in self.entries],
            "complete": self.complete,
            "blocking_reasons": list(self.blocking_reasons),
            "generated_by": self.generated_by,
            **dict(self.extras),
        }
