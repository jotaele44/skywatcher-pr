from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_registry_audit_passes() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/audit_visual_reasoning_runtime.py", "--check"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(completed.stdout)
    assert report["pass"] is True
    assert report["missing_parameter_registry_entries"] == []
    assert report["missing_reason_registry_entries"] == []
    assert report["prohibited_legacy_references"] == []
    assert report["unregistered_float_compare_literals"] == []
