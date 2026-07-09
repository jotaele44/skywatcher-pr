"""Equivalence test for the Core module reorg: prii_readiness_engine.py is now
a backward-compat shim over skywatcher.core.readiness_engine. See
docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md."""

import json

from prii_readiness_engine import PRIIReadinessEngine as OldEngine
from prii_readiness_engine import READINESS_STATUS_READY as OLD_READY
from skywatcher.core.readiness_engine import PRIIReadinessEngine as NewEngine
from skywatcher.core.readiness_engine import READINESS_STATUS_READY as NEW_READY


def test_shim_reexports_identical_symbols():
    assert OldEngine is NewEngine
    assert OLD_READY == NEW_READY == "READY"


def test_shim_functional_equivalence(tmp_path):
    (tmp_path / "integration_report.json").write_text(
        json.dumps({"overall_status": "PASS", "gates": {}}), encoding="utf-8"
    )
    (tmp_path / "calibration_report.json").write_text(
        json.dumps({"status": "PASS", "baseline_mode": "operational", "candidate_count": 1}),
        encoding="utf-8",
    )
    old_report = OldEngine(str(tmp_path)).assess()
    new_report = NewEngine(str(tmp_path)).assess()
    assert old_report["readiness_status"] == new_report["readiness_status"] == OLD_READY
