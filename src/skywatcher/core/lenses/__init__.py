"""Declarative analysis lenses, objective profiles, and run coverage.

Core-owned so both halves of the pipeline can read it: satim and fpim may import core
but not each other (ADR v2.0 section 3.1), so a registry shared by Flight Data
Collection and Satellite Image Processing has to live here.
"""

from __future__ import annotations

from skywatcher.core.lenses.coverage import evaluate_coverage, evaluate_lens
from skywatcher.core.lenses.models import (
    COVERAGE_STATES,
    DEGRADED,
    EVIDENCE_AXES,
    MISSING,
    NOT_APPLICABLE,
    OWNERS,
    SATISFIED,
    STAGE_CROSS_DOMAIN,
    STAGE_FLIGHT,
    STAGE_SATELLITE,
    STAGES,
    CoverageReport,
    LensCoverage,
    LensSpec,
    ObjectiveProfile,
    ParameterSpec,
)
from skywatcher.core.lenses.registry import (
    LensRegistry,
    ObjectiveProfileRegistry,
    load_default_registries,
    resolve_profile_lenses,
    unknown_lens_references,
)
from skywatcher.core.lenses.thresholds import (
    ThresholdNotExecutable,
    ThresholdRegistry,
    ThresholdSpec,
    default_registry,
)

__all__ = [
    "COVERAGE_STATES",
    "DEGRADED",
    "EVIDENCE_AXES",
    "MISSING",
    "NOT_APPLICABLE",
    "OWNERS",
    "SATISFIED",
    "STAGES",
    "STAGE_CROSS_DOMAIN",
    "STAGE_FLIGHT",
    "STAGE_SATELLITE",
    "CoverageReport",
    "LensCoverage",
    "LensRegistry",
    "LensSpec",
    "ObjectiveProfile",
    "ObjectiveProfileRegistry",
    "ParameterSpec",
    "ThresholdNotExecutable",
    "ThresholdRegistry",
    "ThresholdSpec",
    "default_registry",
    "evaluate_coverage",
    "evaluate_lens",
    "load_default_registries",
    "resolve_profile_lenses",
    "unknown_lens_references",
]
