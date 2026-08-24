"""Fail-closed coverage evaluation for an analysis run.

The rule this module exists to enforce: a run may not be reported complete while a
required lens has an unmet required parameter, a missing input, or no result. Before
this, a check that never ran and a check that ran and found nothing were
indistinguishable in the output.

Three existing repo patterns are combined here rather than reinvented:

  * satim.artifacts.restriction_gate.RestrictionDecision — a typed decision carrying
    its own reason, instead of a bare bool;
  * fr24_image_skill.adapters.AdapterCapability — available/error degradation, so an
    unavailable capability is recorded rather than silently skipped;
  * fr24.satim_engine.missing_layer / degraded_layer — the "explicit degraded-state
    record rather than fabricated output" convention the SATIM skill already requires.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from skywatcher.core.lenses.models import (
    DEGRADED,
    MISSING,
    NOT_APPLICABLE,
    SATISFIED,
    CoverageReport,
    LensCoverage,
    LensSpec,
    ObjectiveProfile,
)
from skywatcher.core.lenses.registry import LensRegistry, resolve_profile_lenses


def _missing_parameters(
    lens: LensSpec, supplied: Mapping[str, Any]
) -> tuple[list[str], list[str]]:
    """Required and optional parameter ids absent from ``supplied``.

    A parameter with a declared default counts as supplied — the default *is* the
    value. A parameter present but None counts as absent, since that is what an
    upstream stage emits when it could not determine one.
    """
    missing_required: list[str] = []
    missing_optional: list[str] = []
    for spec in lens.all_parameters():
        if spec.parameter_id not in supplied:
            # Genuinely absent: the declared default, if any, is the value.
            if spec.default is not None:
                continue
        elif supplied[spec.parameter_id] is not None:
            continue
        # Either genuinely absent with no default, or present-but-None — the latter
        # is what an upstream stage emits when it looked and found nothing, so it
        # counts as missing even when a default exists. A default only fills in for
        # silence, not for an explicit "I don't have one".
        (missing_required if spec.required else missing_optional).append(spec.parameter_id)
    return missing_required, missing_optional


def _missing_inputs(lens: LensSpec, available_inputs: Iterable[str]) -> list[str]:
    have = set(available_inputs)
    return [name for name in lens.required_inputs if name not in have]


def evaluate_lens(
    lens: LensSpec,
    *,
    supplied_parameters: Mapping[str, Any] | None = None,
    available_inputs: Iterable[str] = (),
    produced: bool = True,
    applicable: bool = True,
    thresholds_applied: Sequence[Mapping[str, Any]] = (),
    method_version: str = "",
) -> LensCoverage:
    """Coverage for one lens. Every non-satisfied outcome carries its cause."""
    supplied = dict(supplied_parameters or {})

    if not applicable:
        return LensCoverage(
            lens_id=lens.lens_id,
            state=NOT_APPLICABLE,
            reason="lens declared not applicable to this run's inputs",
            method_version=method_version,
        )

    missing_inputs = _missing_inputs(lens, available_inputs)
    if missing_inputs:
        return LensCoverage(
            lens_id=lens.lens_id,
            state=MISSING,
            reason=f"required input(s) unavailable: {', '.join(sorted(missing_inputs))}",
            method_version=method_version,
        )

    missing_required, missing_optional = _missing_parameters(lens, supplied)
    if missing_required:
        return LensCoverage(
            lens_id=lens.lens_id,
            state=MISSING,
            unmet_parameters=tuple(sorted(missing_required)),
            reason=(
                "required parameter(s) not supplied: "
                f"{', '.join(sorted(missing_required))}"
            ),
            method_version=method_version,
        )

    if not produced:
        return LensCoverage(
            lens_id=lens.lens_id,
            state=DEGRADED,
            reason="lens ran but produced no result",
            method_version=method_version,
            thresholds_applied=tuple(thresholds_applied),
        )

    if missing_optional:
        # Degraded rather than satisfied: each optional parameter declares what is lost
        # when it is absent, and that loss belongs in the record.
        detail = "; ".join(
            f"{spec.parameter_id}: {spec.degraded_behavior}"
            for spec in lens.optional_parameters
            if spec.parameter_id in set(missing_optional)
        )
        return LensCoverage(
            lens_id=lens.lens_id,
            state=DEGRADED,
            unmet_parameters=tuple(sorted(missing_optional)),
            reason=f"optional parameter(s) absent — {detail}",
            method_version=method_version,
            thresholds_applied=tuple(thresholds_applied),
        )

    return LensCoverage(
        lens_id=lens.lens_id,
        state=SATISFIED,
        method_version=method_version,
        thresholds_applied=tuple(thresholds_applied),
    )


def evaluate_coverage(
    profile: ObjectiveProfile,
    registry: LensRegistry,
    *,
    run_id: str,
    supplied_parameters: Mapping[str, Mapping[str, Any]] | None = None,
    available_inputs: Mapping[str, Iterable[str]] | None = None,
    produced: Mapping[str, bool] | None = None,
    applicable: Mapping[str, bool] | None = None,
    thresholds_applied: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    method_versions: Mapping[str, str] | None = None,
    generated_by: str = "",
) -> CoverageReport:
    """Evaluate every lens a profile names and decide whether the run is complete.

    Per-lens keyword maps are keyed by lens_id; a lens absent from a map takes the
    permissive default for that dimension, so a caller only has to speak up about what
    actually went wrong.
    """
    supplied_parameters = supplied_parameters or {}
    available_inputs = available_inputs or {}
    produced = produced or {}
    applicable = applicable or {}
    thresholds_applied = thresholds_applied or {}
    method_versions = method_versions or {}

    _, dangling = resolve_profile_lenses(profile, registry)
    required = set(profile.required_lenses)
    blocking: list[str] = []
    entries: list[LensCoverage] = []

    for lens_id in tuple(profile.required_lenses) + tuple(profile.optional_lenses):
        if lens_id in dangling:
            entries.append(
                LensCoverage(
                    lens_id=lens_id,
                    state=MISSING,
                    reason=(
                        f"profile {profile.profile_id} references lens {lens_id!r}, "
                        "which is not in the registry"
                    ),
                )
            )
            if lens_id in required:
                blocking.append(f"{lens_id}: referenced by profile but not registered")
            continue

        lens = registry.get(lens_id)
        entry = evaluate_lens(
            lens,
            supplied_parameters=supplied_parameters.get(lens_id),
            available_inputs=available_inputs.get(lens_id, ()),
            produced=produced.get(lens_id, True),
            applicable=applicable.get(lens_id, True),
            thresholds_applied=thresholds_applied.get(lens_id, ()),
            method_version=method_versions.get(lens_id, ""),
        )
        entries.append(entry)

        # Only required lenses can block. A degraded required lens blocks too: the run
        # did not meet its stated objective, and saying so is the whole point.
        if lens_id in required and entry.state in (MISSING, DEGRADED):
            blocking.append(f"{lens_id}: {entry.reason}")
        elif lens_id in required and entry.state == NOT_APPLICABLE:
            blocking.append(
                f"{lens_id}: required by {profile.profile_id} but marked not applicable"
            )

    return CoverageReport(
        profile_id=profile.profile_id,
        run_id=run_id,
        entries=tuple(entries),
        complete=not blocking,
        blocking_reasons=tuple(blocking),
        generated_by=generated_by,
    )
