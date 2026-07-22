"""
PRII READINESS ENGINE
Aggregates PRII gate results and calibration status into a single
prii_readiness_report.json with a tri-state readiness verdict.

Reads from an export directory that contains artifacts produced by:
  --export-pr-intel  →  integration_report.json
  --calibrate-scoring → calibration_report.json

Readiness contract:
  READY      All PRII gates PASS + calibration PASS (or absent)
  DEGRADED   No hard failures but at least one warning
             (calibration WARN, missing integration_report, etc.)
  NOT_READY  Any PRII gate FAIL  OR  calibration FAIL

This module is a pure assessment layer: it reads existing artifacts and
writes prii_readiness_report.json.  It does not run the pipeline itself
and has no CLI surface (added in a later phase).
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from fr24.calibration.readiness_adapter import satim_report_to_legacy_calibration
except Exception:  # pragma: no cover - keeps legacy engine importable in partial builds
    satim_report_to_legacy_calibration = None


READINESS_STATUS_READY            = "READY"
READINESS_STATUS_DEGRADED         = "DEGRADED"
READINESS_STATUS_NOT_READY        = "NOT_READY"
READINESS_STATUS_READY_FOR_OPS    = "READY_FOR_OPERATIONS"

REQUIRED_REPORT_KEYS = [
    "generated_at",
    "export_dir",
    "readiness_status",
    "blockers",
    "warnings",
    "missing_inputs",
    "gate_summary",
]


class PRIIReadinessEngine:
    """
    Aggregates PRII integration and calibration reports into a readiness verdict.

    Usage:
        engine = PRIIReadinessEngine("/path/to/export_dir")
        report = engine.assess()
        print(report["readiness_status"])   # READY | DEGRADED | NOT_READY
    """

    def __init__(self, export_dir: str, min_operational_candidates: Optional[int] = None):
        self.export_dir = Path(export_dir)
        # Optional operational-candidate floor for PRODUCTION_READY. Default
        # None preserves historical behaviour (candidate_count is reported, not
        # gated). Set e.g. 50 to require >= that many operational candidates.
        self.min_operational_candidates = min_operational_candidates

    def assess(self) -> Dict[str, Any]:
        integration = self._load_json("integration_report.json")
        calibration  = self._load_json("calibration_report.json")

        missing_inputs: List[str] = []
        blockers: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = []

        # ── PRII gate assessment ──────────────────────────────────────────────
        prii_overall: Optional[str] = None
        prii_gates:   Dict[str, Any] = {}

        if integration is None:
            missing_inputs.append("integration_report.json")
            warnings.append({
                "source": "prii_report",
                "detail": "integration_report.json not found — PRII gates unverified",
            })
        else:
            prii_overall = integration.get("overall_status")
            prii_gates   = integration.get("gates", {})
            for gate_name, gate in prii_gates.items():
                if gate.get("status") == "FAIL":
                    blockers.append({
                        "source":  "prii_gate",
                        "gate":    gate_name,
                        "detail":  self._gate_detail(gate_name, gate),
                    })

        # ── Calibration assessment ────────────────────────────────────────────
        cal_status:  Optional[str] = None
        cal_mode:    Optional[str] = None
        cal_flags:   List[dict]    = []
        cal_count:   Optional[int] = None

        if calibration is None:
            missing_inputs.append("calibration_report.json")
            # Missing calibration is a warning only: the pipeline may not have
            # been run yet.  It is not a hard blocker.
            warnings.append({
                "source": "calibration",
                "detail": "calibration_report.json not found — scoring baseline unverified",
            })
        else:
            cal_status = calibration.get("status")
            cal_mode   = calibration.get("baseline_mode")
            cal_flags  = calibration.get("calibration_flags", [])
            cal_count  = calibration.get("candidate_count")

            if cal_status == "FAIL":
                for flag in cal_flags:
                    blockers.append({
                        "source": "calibration",
                        "flag":   flag.get("metric", "unknown"),
                        "detail": (
                            f"value={flag.get('value')} outside range, "
                            f"action: {flag.get('action', '')}"
                        ),
                    })
            elif cal_status == "WARN":
                warnings.append({
                    "source": "calibration",
                    "detail": (
                        f"status=WARN (mode={cal_mode}) — "
                        "calibration flags present but suppressed in fixture mode"
                    ),
                })

        # ── Derive overall readiness ──────────────────────────────────────────
        if blockers:
            readiness_status = READINESS_STATUS_NOT_READY
        elif warnings:
            readiness_status = READINESS_STATUS_DEGRADED
        else:
            readiness_status = READINESS_STATUS_READY

        # calibration_ready: True only when mode=operational and status not FAIL
        calibration_ready = (
            cal_mode == "operational" and cal_status in ("PASS", "WARN")
        )

        # Task 200: READY_FOR_OPERATIONS — highest status, requires all gates
        # PASS AND calibration operational (not just fixture-mode READY).
        if readiness_status == READINESS_STATUS_READY and calibration_ready:
            final_status = READINESS_STATUS_READY_FOR_OPS
        else:
            final_status = readiness_status

        report = {
            "generated_at":    datetime.utcnow().isoformat() + "Z",
            "export_dir":      str(self.export_dir),
            "readiness_status": readiness_status,
            "final_status":    final_status,
            "calibration_ready": calibration_ready,
            "blockers":        blockers,
            "warnings":        warnings,
            "missing_inputs":  missing_inputs,
            "gate_summary": {
                "prii_overall":       prii_overall,
                "prii_gates":         prii_gates,
                "calibration_status": cal_status,
                "calibration_flags":  cal_flags,
                "candidate_count":    cal_count,
                "baseline_mode":      cal_mode,
            },
        }

        self._write_report(report)
        return report

    # ── helpers ───────────────────────────────────────────────────────────────

    def _load_json(self, filename: str) -> Optional[Dict[str, Any]]:
        path = self.export_dir / filename
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return self._normalise_loaded_json(filename, payload)

    @staticmethod
    def _normalise_loaded_json(filename: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize newer artifact schemas into contracts expected by assess()."""
        if (
            filename == "calibration_report.json"
            and isinstance(payload, dict)
            and payload.get("schema_version") == "satim.calibration.v1"
            and satim_report_to_legacy_calibration is not None
        ):
            return satim_report_to_legacy_calibration(payload)
        return payload

    @staticmethod
    def _gate_detail(gate_name: str, gate: Dict[str, Any]) -> str:
        if gate_name == "coordinate_coverage":
            return (
                f"pct_with_coords={gate.get('pct_with_coords')} "
                f"< threshold={gate.get('threshold')}"
            )
        if gate_name == "ocr_confidence_gate":
            return (
                f"avg_confidence={gate.get('avg_confidence')} "
                f"< threshold={gate.get('threshold')}"
            )
        if gate_name == "evidence_chain_coverage":
            return (
                f"pct_with_screenshot={gate.get('pct_with_screenshot')} "
                f"< threshold={gate.get('threshold')}"
            )
        if gate_name == "schema_validation":
            return f"invalid={gate.get('invalid')} records failed schema validation"
        if gate_name == "export_completeness":
            return f"missing files: {gate.get('missing', [])}"
        if gate_name == "temporal_integrity":
            return f"violations={gate.get('violations')}"
        return f"gate {gate_name} failed"

    def assess_satellite_manifests(
        self, manifest_dir: Optional[str] = None
    ) -> Dict[str, Any]:
        """Return a schema gateResult for satellite manifest presence."""
        search_dir = Path(manifest_dir) if manifest_dir else self.export_dir
        if not search_dir.exists():
            return {"status": "MISSING", "message": f"directory not found: {search_dir}"}
        manifests = list(search_dir.glob("*.json"))
        manifests = [p for p in manifests if "manifest" in p.name.lower()]
        if not manifests:
            return {
                "status": "WARN",
                "message": f"no satellite manifests found in {search_dir}",
            }
        return {
            "status": "PASS",
            "message": f"{len(manifests)} satellite manifest(s) found",
        }

    def get_gate_status_text(self, gate_name: str, gate: Dict[str, Any]) -> str:
        """Return a compact human-readable summary for a single gate."""
        status = gate.get("status", "UNKNOWN")
        if gate_name == "coordinate_coverage":
            return (
                f"{gate_name}: {status} "
                f"(pct_with_coords={gate.get('pct_with_coords')}, "
                f"threshold={gate.get('threshold')})"
            )
        if gate_name == "ocr_confidence_gate":
            return (
                f"{gate_name}: {status} "
                f"(avg_confidence={gate.get('avg_confidence')}, "
                f"threshold={gate.get('threshold')})"
            )
        if gate_name == "schema_validation":
            return f"{gate_name}: {status} (invalid={gate.get('invalid', 0)})"
        if gate_name == "export_completeness":
            missing = gate.get("missing", [])
            return f"{gate_name}: {status} (missing={missing})"
        if gate_name == "temporal_integrity":
            return f"{gate_name}: {status} (violations={gate.get('violations', 0)})"
        return f"{gate_name}: {status}"

    def to_schema_report(
        self,
        assess_result: Dict[str, Any],
        manifest_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Convert assess() output to prii_readiness_report schema format.

        The schema uses flat gate objects with {status, message} instead of
        the verbose gate_summary structure produced by assess().
        """
        gate_summary = assess_result.get("gate_summary", {})
        prii_gates   = gate_summary.get("prii_gates", {})

        # ── prii gate ─────────────────────────────────────────────────────────
        prii_overall = gate_summary.get("prii_overall")
        if prii_overall is None:
            prii_gate = {"status": "MISSING", "message": "integration_report.json absent"}
        elif prii_overall == "PASS":
            prii_gate = {"status": "PASS", "message": "all PRII gates pass"}
        else:
            failing = [
                self.get_gate_status_text(n, g)
                for n, g in prii_gates.items()
                if g.get("status") == "FAIL"
            ]
            prii_gate = {"status": "FAIL", "message": "; ".join(failing) or "gate failed"}

        # ── calibration gate ──────────────────────────────────────────────────
        cal_status = gate_summary.get("calibration_status")
        if cal_status is None:
            cal_gate = {"status": "MISSING", "message": "calibration_report.json absent"}
        elif cal_status == "PASS":
            cal_gate = {"status": "PASS", "message": "calibration within baseline ranges"}
        elif cal_status == "WARN":
            cal_gate = {
                "status": "WARN",
                "message": (
                    f"fixture mode ({gate_summary.get('baseline_mode')}) — "
                    "skipped tier checks"
                ),
            }
        else:
            flags = gate_summary.get("calibration_flags", [])
            flag_names = ", ".join(f.get("metric", "?") for f in flags)
            cal_gate = {"status": "FAIL", "message": f"flags: {flag_names}"}

        # ── satellite_manifests gate ──────────────────────────────────────────
        sat_gate = self.assess_satellite_manifests(manifest_dir)

        # ── status mapping ────────────────────────────────────────────────────
        rs = assess_result.get("readiness_status", READINESS_STATUS_NOT_READY)
        schema_status_map = {
            READINESS_STATUS_READY:     "READY",
            READINESS_STATUS_DEGRADED:  "DEGRADED",
            READINESS_STATUS_NOT_READY: "NOT_READY",
        }
        schema_status = schema_status_map.get(rs, rs)

        warnings = [w.get("detail", str(w)) for w in assess_result.get("warnings", [])]
        errors   = [b.get("detail", str(b)) for b in assess_result.get("blockers", [])]

        return {
            "generated_at": assess_result.get("generated_at", ""),
            "status":        schema_status,
            "gates": {
                "prii":                prii_gate,
                "calibration":         cal_gate,
                "satellite_manifests": sat_gate,
            },
            "warnings": warnings,
            "errors":   errors,
            "notes":    None,
        }

    def format_readiness_text(self, report: Dict[str, Any]) -> str:
        """Return a human-readable multi-line summary of a readiness report."""
        lines = [
            f"Readiness Status: {report.get('readiness_status', report.get('status', 'UNKNOWN'))}",
            f"Generated:        {report.get('generated_at', '')}",
        ]

        blockers = report.get("blockers", [])
        if blockers:
            lines.append(f"Blockers ({len(blockers)}):")
            for b in blockers:
                lines.append(f"  [{b.get('source', '?')}] {b.get('detail', b)}")

        warnings = report.get("warnings", [])
        if warnings:
            lines.append(f"Warnings ({len(warnings)}):")
            for w in warnings:
                if isinstance(w, dict):
                    lines.append(f"  [{w.get('source', '?')}] {w.get('detail', w)}")
                else:
                    lines.append(f"  {w}")

        missing = report.get("missing_inputs", [])
        if missing:
            lines.append(f"Missing inputs: {', '.join(missing)}")

        gate_summary = report.get("gate_summary", {})
        if gate_summary:
            lines.append("Gate summary:")
            prii_gates = gate_summary.get("prii_gates", {})
            for gate_name, gate in prii_gates.items():
                lines.append(f"  {self.get_gate_status_text(gate_name, gate)}")
            lines.append(
                f"  calibration: {gate_summary.get('calibration_status', 'N/A')} "
                f"(mode={gate_summary.get('baseline_mode', 'N/A')}, "
                f"candidates={gate_summary.get('candidate_count', 'N/A')})"
            )

        return "\n".join(lines)

    def export_dashboard_json(
        self,
        assess_result: Dict[str, Any],
        output_path: str,
        manifest_dir: Optional[str] = None,
    ) -> None:
        """Write schema-compliant dashboard JSON to *output_path*."""
        schema_report = self.to_schema_report(assess_result, manifest_dir=manifest_dir)
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(schema_report, indent=2), encoding="utf-8")

    def health_check(self) -> Dict[str, Any]:
        """Return a compact health-check dict for the export directory.

        status is "healthy" if both input artifacts are present and readable,
        "degraded" if one is missing, "unhealthy" if neither is readable.
        """
        checks: Dict[str, Any] = {}

        for fname in ("integration_report.json", "calibration_report.json"):
            path = self.export_dir / fname
            if not path.exists():
                checks[fname] = "missing"
            else:
                try:
                    json.loads(path.read_text(encoding="utf-8"))
                    checks[fname] = "ok"
                except Exception:
                    checks[fname] = "unreadable"

        statuses = list(checks.values())
        if all(s == "ok" for s in statuses):
            overall = "healthy"
        elif all(s != "ok" for s in statuses):
            overall = "unhealthy"
        else:
            overall = "degraded"

        return {
            "export_dir": str(self.export_dir),
            "status":     overall,
            "checks":     checks,
        }

    @property
    def PRODUCTION_READY(self) -> bool:
        """Return True when the readiness report reaches READY_FOR_OPERATIONS,
        calibration is operational (calibration_ready=True), and there are no
        blockers.

        By default the operational ``candidate_count`` is *reported but not
        gated*. To additionally require a minimum number of operational
        candidates (e.g. the historical "≥50" target), construct the engine with
        ``min_operational_candidates=50`` — the count is then enforced here. The
        default (None) preserves prior behaviour.
        """
        try:
            report = self.assess()
        except Exception:
            return False
        if (
            report.get("final_status") != READINESS_STATUS_READY_FOR_OPS
            or report.get("calibration_ready") is not True
            or report.get("blockers")
        ):
            return False
        if self.min_operational_candidates is not None:
            # candidate_count is emitted under gate_summary (see assess()).
            count = (report.get("gate_summary") or {}).get("candidate_count")
            if not isinstance(count, int) or count < self.min_operational_candidates:
                return False
        return True

    def _write_report(self, report: Dict[str, Any]) -> None:
        self.export_dir.mkdir(parents=True, exist_ok=True)
        (self.export_dir / "prii_readiness_report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
