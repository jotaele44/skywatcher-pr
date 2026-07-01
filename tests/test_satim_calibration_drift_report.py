"""Tests for the SATIM active-vs-control calibration drift report."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from satim_calibration_drift_report import build_report  # noqa: E402

ACTIVE_SET = REPO_ROOT / "data" / "satim_calibration" / "moca_fr24_2025"
CONTROL_SET = REPO_ROOT / "data" / "satim_calibration" / "control_moca_groundtruth"


def test_build_report_includes_active_and_fit_constants():
    report = build_report(ACTIVE_SET, CONTROL_SET)
    assert "SATIM-CAL-MOCA-C6038_v1" in report
    assert "PALM" in report and "WATER" in report
    assert "active=" in report and "fit=" in report
    assert "review" in report and "promote_to_candidate" in report
    assert "n=1" in report  # each canonical class has exactly one control exemplar


def test_build_report_notes_thin_evidence_caveat():
    report = build_report(ACTIVE_SET, CONTROL_SET)
    assert "drift signal" in report


def test_cli_runs_cleanly_with_defaults():
    result = subprocess.run(
        [sys.executable, "scripts/satim_calibration_drift_report.py"],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "SATIM calibration drift report" in result.stdout
