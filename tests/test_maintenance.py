"""Skywatcher maintenance adapter: repo-specific checks + shared-package wiring.

Generic detection/runner behavior now lives in thehub-pr's shared
`prii_maintenance` package (thehub-pr/packages/prii_maintenance/tests/); this
file keeps only the checks genuinely specific to skywatcher-pr
(`maintenance/adapters/local.py`) plus a smoke test proving the CLI shim's
dependency-injection wiring (`prii_maintenance.run_maintenance(...,
local_checks=local.run_checks)`) actually invokes this repo's adapter.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from maintenance.adapters import local  # noqa: E402
from prii_maintenance import run_maintenance  # noqa: E402
from prii_maintenance import state as state_mod  # noqa: E402


def _federation(root, *, blocking=None, export_dir="exports/federation"):
    fed = {
        "program_id": "skywatcher-pr",
        "canonical_outputs": {"canonical_export_dir": export_dir},
        "federation_readiness_gate": {"blocking_conditions": blocking or []},
    }
    (root / "federation.json").write_text(json.dumps(fed), encoding="utf-8")
    return state_mod.collect_repo_state(root)


def _write_threshold(root, rel, thresholds):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"promotion_thresholds": thresholds}), encoding="utf-8")


# ---- adapter: canonical export dir ----


def test_export_dir_present_no_finding(tmp_path):
    (tmp_path / "exports" / "federation").mkdir(parents=True)
    state = _federation(tmp_path)
    assert local.check_canonical_export_dir("skywatcher-pr", tmp_path, state) == []


def test_export_dir_absent_with_synthetic_blocker_is_info(tmp_path):
    state = _federation(
        tmp_path, blocking=["only the synthetic example package is present"]
    )
    findings = local.check_canonical_export_dir("skywatcher-pr", tmp_path, state)
    assert len(findings) == 1
    assert findings[0].severity == "info"


def test_export_dir_absent_without_blocker_is_critical(tmp_path):
    state = _federation(tmp_path, blocking=["unrelated blocker"])
    findings = local.check_canonical_export_dir("skywatcher-pr", tmp_path, state)
    assert len(findings) == 1
    assert findings[0].severity == "critical"


# ---- adapter: classifier threshold drift ----


def test_threshold_ordered_ok(tmp_path):
    _write_threshold(
        tmp_path,
        "exports/satim_calibration/c1/summary.json",
        {"review": 0.55, "cross_source_required": 0.7, "promote_to_candidate": 0.8},
    )
    state = _federation(tmp_path)
    assert (
        local.check_classifier_threshold_drift("skywatcher-pr", tmp_path, state) == []
    )


def test_threshold_misordered_is_critical(tmp_path):
    _write_threshold(
        tmp_path,
        "exports/satim_calibration/c1/summary.json",
        {"review": 0.9, "cross_source_required": 0.7, "promote_to_candidate": 0.8},
    )
    state = _federation(tmp_path)
    findings = local.check_classifier_threshold_drift("skywatcher-pr", tmp_path, state)
    assert len(findings) == 1
    assert findings[0].severity == "critical"


# ---- shared-package wiring smoke test ----


def test_run_maintenance_invokes_local_adapter_and_is_not_blocked_when_clean(tmp_path):
    """Prove the CLI shim's local_checks injection actually reaches this repo's
    adapter through the shared prii_maintenance package."""
    (tmp_path / "exports" / "federation").mkdir(parents=True)
    _write_threshold(
        tmp_path,
        "exports/satim_calibration/c1/summary.json",
        {"review": 0.55, "cross_source_required": 0.7, "promote_to_candidate": 0.8},
    )
    _federation(tmp_path)

    report = run_maintenance(
        root=tmp_path,
        mode="audit",
        write=False,
        program_id="skywatcher-pr",
        local_checks=local.run_checks,
    )

    assert report.promotion_blocked is False
