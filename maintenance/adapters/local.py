"""Skywatcher-specific maintenance checks (workbook Adapter Rules).

- check_canonical_export_dir: exports/federation must exist, OR a synthetic-only
  blocker must be declared in the federation readiness gate (otherwise critical).
- check_classifier_threshold_drift: SATIM promotion thresholds must stay ordered
  (review <= cross_source_required <= promote_to_candidate); a misordering is a
  drift that requires review -> critical.

Read-only and audit-first.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..models import MaintenanceFinding

_SATIM_DIRS = ("exports/satim_calibration", "reports/satim")
_THRESHOLD_ORDER = ("review", "cross_source_required", "promote_to_candidate")


def check_canonical_export_dir(
    repo: str, root: Path, state: dict
) -> list[MaintenanceFinding]:
    outputs = state["canonical_outputs"]
    rel = outputs.get("canonical_export_dir", "exports/federation")
    if (root / rel).is_dir():
        return []
    gate = state["federation"].get("federation_readiness_gate", {})
    conditions = " ".join(str(c) for c in gate.get("blocking_conditions", [])).lower()
    declared = "synthetic" in conditions or "no live" in conditions
    if declared:
        return [
            MaintenanceFinding(
                finding_id=f"{repo}:export_integrity:canonical_export_dir",
                repo=repo,
                category="export_integrity",
                severity="info",
                action="none",
                message="canonical export dir absent; covered by a declared synthetic-only blocker",
                path=rel,
            )
        ]
    return [
        MaintenanceFinding(
            finding_id=f"{repo}:export_integrity:canonical_export_dir",
            repo=repo,
            category="export_integrity",
            severity="critical",
            action="blocked",
            message="canonical export dir missing and no synthetic-only blocker declared",
            path=rel,
        )
    ]


def _threshold_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for rel in _SATIM_DIRS:
        base = root / rel
        if base.is_dir():
            files.extend(sorted(base.rglob("*.json")))
    return files


def check_classifier_threshold_drift(
    repo: str, root: Path, state: dict
) -> list[MaintenanceFinding]:
    findings: list[MaintenanceFinding] = []
    for path in _threshold_files(root):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        thresholds = data.get("promotion_thresholds")
        if not isinstance(thresholds, dict):
            continue
        values = [thresholds.get(k) for k in _THRESHOLD_ORDER]
        if any(not isinstance(v, (int, float)) for v in values):
            continue
        if not (values[0] <= values[1] <= values[2]):
            findings.append(
                MaintenanceFinding(
                    finding_id=f"{repo}:promotion_gate:threshold_{path.stem}",
                    repo=repo,
                    category="promotion_gate",
                    severity="critical",
                    action="blocked",
                    message=f"classifier promotion thresholds out of order in {path.relative_to(root)}",
                    path=str(path.relative_to(root)),
                    detail=dict(zip(_THRESHOLD_ORDER, values)),
                )
            )
    return findings


CHECKS = (check_canonical_export_dir, check_classifier_threshold_drift)


def run_checks(repo: str, root: Path, state: dict) -> list[MaintenanceFinding]:
    findings: list[MaintenanceFinding] = []
    for check in CHECKS:
        findings.extend(check(repo, root, state))
    return findings
