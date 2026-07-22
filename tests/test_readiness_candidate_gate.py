"""PRODUCTION_READY: candidate_count is reported-not-gated by default; an
optional min_operational_candidates floor enforces it when set. Resolves the
prior doc/code drift (docstring claimed a >=50 gate the code never applied)."""

from __future__ import annotations

from skywatcher.core.readiness_engine import PRIIReadinessEngine


def _ops_report(candidate_count):
    return {
        "final_status": "READY_FOR_OPERATIONS",
        "calibration_ready": True,
        "blockers": [],
        "candidate_count": candidate_count,
    }


def test_default_does_not_gate_on_candidate_count(tmp_path):
    e = PRIIReadinessEngine(str(tmp_path))
    e.assess = lambda: _ops_report(1)  # type: ignore[method-assign]
    assert e.PRODUCTION_READY is True  # not gated by default


def test_opt_in_gate_blocks_below_floor(tmp_path):
    e = PRIIReadinessEngine(str(tmp_path), min_operational_candidates=50)
    e.assess = lambda: _ops_report(10)  # type: ignore[method-assign]
    assert e.PRODUCTION_READY is False


def test_opt_in_gate_passes_at_or_above_floor(tmp_path):
    e = PRIIReadinessEngine(str(tmp_path), min_operational_candidates=50)
    e.assess = lambda: _ops_report(50)  # type: ignore[method-assign]
    assert e.PRODUCTION_READY is True


def test_gate_requires_ready_for_operations(tmp_path):
    e = PRIIReadinessEngine(str(tmp_path), min_operational_candidates=1)
    e.assess = lambda: {**_ops_report(100), "final_status": "DEGRADED"}  # type: ignore[method-assign]
    assert e.PRODUCTION_READY is False
