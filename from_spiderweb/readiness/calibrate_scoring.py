"""
CALIBRATION DRIVER
Reads a completed --spiderweb-intake output directory and compares the
tier/MBIL/hydro/utility/terrain distributions against expected operational
baseline ranges. Produces calibration_report.json.

Not a PRII module. Not a test. Run after --spiderweb-intake when a real
operational DB export is available.
"""

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

BASELINE: List[Dict[str, Any]] = [
    {"metric": "pct_T4",         "min": 0.20, "max": 0.70,
     "action": "investigate tier thresholds"},
    {"metric": "pct_T1_or_T2",   "min": 0.05, "max": 0.50,
     "action": "check for tier inflation if >0.50"},
    {"metric": "pct_mbil_0",     "min": 0.0,  "max": 0.15,
     "action": "expand MUNICIPAL_CENTROIDS"},
    {"metric": "pct_hydro_yes",  "min": 0.05, "max": 0.40,
     "action": "expand HYDRO_LOCATIONS"},
    {"metric": "pct_utility_yes","min": 0.10, "max": 0.60,
     "action": "expand UTILITY_CORRIDOR_WAYPOINTS"},
    {"metric": "pct_urban_terrain","min": 0.10,"max": 0.50,
     "action": "add urban bounding boxes"},
    {"metric": "dedup_rate",     "min": 0.0,  "max": 0.30,
     "action": "tighten dedup threshold"},
]

# Below this count the sample is too small for tier-distribution checks
MIN_OPERATIONAL_CANDIDATES = 50
# Tier-skew metrics suppressed in fixture mode (meaningless on <50 candidates)
FIXTURE_SKIP_METRICS = {"pct_T4", "pct_T1_or_T2"}

REQUIRED_REPORT_KEYS = [
    "generated_at", "export_dir", "baseline_mode", "status", "missing_inputs",
    "candidate_count", "tier_distribution", "mbil_distribution",
    "signal_rates", "terrain_distribution",
    "dedup_rate", "calibration_flags",
]


class CalibrationDriver:
    def __init__(self, export_dir: str, output_dir: Optional[str] = None):
        self.export_dir = Path(export_dir)
        self.output_dir = Path(output_dir) if output_dir else self.export_dir

    def run(self) -> Dict[str, Any]:
        features  = self._load_overlay()
        gap_audit = self._load_gap_audit()
        missing   = self._missing_inputs()

        n    = len(features)
        mode = "operational" if n >= MIN_OPERATIONAL_CANDIDATES else "fixture"

        tier_dist    = self._tier_distribution(features)
        mbil_dist    = self._mbil_distribution(features)
        signal_rates = self._signal_rates(features, n)
        terrain_dist = self._terrain_distribution(features)
        dedup_rate   = self._dedup_rate(gap_audit, n)

        stats = {
            "pct_T4":           tier_dist.get("T4", 0) / n if n else 0.0,
            "pct_T1_or_T2":     (tier_dist.get("T1", 0) + tier_dist.get("T2", 0)) / n if n else 0.0,
            "pct_mbil_0":       mbil_dist.get("MBIL-0", 0) / n if n else 0.0,
            "pct_hydro_yes":    signal_rates["hydro_yes_pct"],
            "pct_utility_yes":  signal_rates["utility_yes_pct"],
            "pct_urban_terrain":terrain_dist.get("urban", 0) / n if n else 0.0,
            "dedup_rate":       dedup_rate,
        }

        # With 0 candidates all stats are 0/0 — skip baseline checks entirely
        flags = self._compare_to_baseline(stats, mode) if n > 0 else []
        flags.sort(key=lambda f: f["metric"])

        if not flags:
            status = "PASS"
        elif mode == "operational":
            status = "FAIL"
        else:
            status = "WARN"

        report = {
            "generated_at":        datetime.utcnow().isoformat() + "Z",
            "export_dir":          str(self.export_dir),
            "baseline_mode":       mode,
            "status":              status,
            "missing_inputs":      missing,
            "candidate_count":     n,
            "tier_distribution":   dict(tier_dist),
            "mbil_distribution":   dict(mbil_dist),
            "signal_rates":        signal_rates,
            "terrain_distribution":dict(terrain_dist),
            "dedup_rate":          round(dedup_rate, 4),
            "calibration_flags":   flags,
        }

        self._write_report(report)
        return report

    def _missing_inputs(self) -> List[str]:
        missing = []
        if not (self.export_dir / "spiderweb_overlay_candidates.geojson").exists():
            missing.append("spiderweb_overlay_candidates.geojson")
        if not (self.export_dir / "spiderweb_gap_audit.json").exists():
            missing.append("spiderweb_gap_audit.json")
        return missing

    def _load_overlay(self) -> List[Dict[str, Any]]:
        path = self.export_dir / "spiderweb_overlay_candidates.geojson"
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data.get("features", [])
        except Exception:
            return []

    def _load_gap_audit(self) -> Dict[str, Any]:
        path = self.export_dir / "spiderweb_gap_audit.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _tier_distribution(self, features: List[Dict[str, Any]]) -> Counter:
        return Counter(
            f["properties"].get("evidence_tier", "unknown")
            for f in features
        )

    def _mbil_distribution(self, features: List[Dict[str, Any]]) -> Counter:
        return Counter(
            f["properties"].get("mbil_class", "unknown")
            for f in features
        )

    def _signal_rates(
        self, features: List[Dict[str, Any]], n: int
    ) -> Dict[str, float]:
        if n == 0:
            return {"hydro_yes_pct": 0.0, "utility_yes_pct": 0.0}
        hydro = sum(1 for f in features if f["properties"].get("hydro_overlap") == "yes")
        util = sum(1 for f in features if f["properties"].get("utility_overlap") == "yes")
        return {
            "hydro_yes_pct":   round(hydro / n, 4),
            "utility_yes_pct": round(util / n, 4),
        }

    def _terrain_distribution(self, features: List[Dict[str, Any]]) -> Counter:
        return Counter(
            f["properties"].get("terrain_context", "unknown")
            for f in features
        )

    def _dedup_rate(self, gap_audit: Dict[str, Any], n_after: int) -> float:
        removed = gap_audit.get("gaps", {}).get("dedup_gap", {}).get("duplicates_removed", 0)
        total_before = n_after + removed
        if total_before == 0:
            return 0.0
        return round(removed / total_before, 4)

    def _compare_to_baseline(
        self, stats: Dict[str, float], mode: str
    ) -> List[Dict[str, Any]]:
        skip = FIXTURE_SKIP_METRICS if mode == "fixture" else set()
        flags = []
        for b in BASELINE:
            if b["metric"] in skip:
                continue
            val = stats.get(b["metric"])
            if val is None:
                continue
            if val < b["min"]:
                flags.append({
                    "metric":       b["metric"],
                    "value":        round(val, 4),
                    "expected_min": b["min"],
                    "action":       b["action"],
                })
            elif val > b["max"]:
                flags.append({
                    "metric":       b["metric"],
                    "value":        round(val, 4),
                    "expected_max": b["max"],
                    "action":       b["action"],
                })
        return flags

    def explain_flags(self, report: Dict[str, Any]) -> str:
        """Return a human-readable summary of calibration flags in *report*.

        Returns "No calibration flags — PASS" when the flags list is empty.
        """
        flags = report.get("calibration_flags", [])
        if not flags:
            return "No calibration flags — PASS"
        lines = [f"Calibration status: {report.get('status', 'UNKNOWN')}",
                 f"Mode: {report.get('baseline_mode', 'unknown')}",
                 f"{len(flags)} flag(s) raised:"]
        for f in flags:
            metric = f.get("metric", "?")
            value  = f.get("value", "?")
            action = f.get("action", "")
            if "expected_min" in f:
                lines.append(
                    f"  [{metric}] value={value} < min={f['expected_min']} → {action}"
                )
            elif "expected_max" in f:
                lines.append(
                    f"  [{metric}] value={value} > max={f['expected_max']} → {action}"
                )
            else:
                lines.append(f"  [{metric}] value={value} → {action}")
        return "\n".join(lines)

    @staticmethod
    def compare_runs(report_a: Dict[str, Any], report_b: Dict[str, Any]) -> Dict[str, Any]:
        """Compare two calibration run reports.

        Returns a delta dict with per-metric absolute change (b - a).
        Positive delta means metric increased from run A to run B.
        """
        metrics_a = CalibrationDriver._extract_metrics(report_a)
        metrics_b = CalibrationDriver._extract_metrics(report_b)
        all_keys = set(metrics_a) | set(metrics_b)
        deltas = {}
        for k in sorted(all_keys):
            va = metrics_a.get(k)
            vb = metrics_b.get(k)
            if va is not None and vb is not None:
                deltas[k] = round(vb - va, 6)
            else:
                deltas[k] = None
        return {
            "candidate_count_a": report_a.get("candidate_count"),
            "candidate_count_b": report_b.get("candidate_count"),
            "status_a":          report_a.get("status"),
            "status_b":          report_b.get("status"),
            "metric_deltas":     deltas,
        }

    @staticmethod
    def _extract_metrics(report: Dict[str, Any]) -> Dict[str, float]:
        """Pull flat metric values from a calibration report."""
        sr = report.get("signal_rates", {})
        n  = report.get("candidate_count", 0)
        td = report.get("tier_distribution", {})
        md = report.get("mbil_distribution", {})
        te = report.get("terrain_distribution", {})
        return {
            "dedup_rate":         report.get("dedup_rate", 0.0),
            "hydro_yes_pct":      sr.get("hydro_yes_pct", 0.0),
            "utility_yes_pct":    sr.get("utility_yes_pct", 0.0),
            "pct_T4":             td.get("T4", 0) / n if n else 0.0,
            "pct_T1_or_T2":       (td.get("T1", 0) + td.get("T2", 0)) / n if n else 0.0,
            "pct_mbil_0":         md.get("MBIL-0", 0) / n if n else 0.0,
            "pct_urban_terrain":  te.get("urban", 0) / n if n else 0.0,
        }

    def _write_report(self, report: Dict[str, Any]) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "calibration_report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
