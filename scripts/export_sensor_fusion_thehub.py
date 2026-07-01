#!/usr/bin/env python3
"""Export Skywatcher sensor-fusion analytics for TheHub ingestion."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def read_json(path: Path, default: object) -> object:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def build_thehub_export(anomaly_payload: dict[str, object], dashboard_payload: dict[str, object]) -> dict[str, object]:
    return {
        "producer": "skywatcher-pr",
        "consumer": "thehub-pr",
        "export_contract": "sensor_fusion_analytics_v1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "live_tracking": False,
        "operational_cueing": False,
        "operator_action": "review_context_only",
        "anomaly_count": anomaly_payload.get("anomaly_count", 0),
        "dashboard": dashboard_payload.get("dashboard", "sensor_fusion_context"),
        "metrics": dashboard_payload.get("metrics", {}),
        "review_bands": dashboard_payload.get("review_bands", {}),
        "guardrails": {
            "context_only": True,
            "public_live_tracking": False,
            "operational_cueing": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anomalies", type=Path, default=Path("outputs/sensor_fusion/anomaly_review.json"))
    parser.add_argument("--dashboard", type=Path, default=Path("outputs/dashboard/sensor_fusion_context.json"))
    parser.add_argument("--output", type=Path, default=Path("outputs/federation/thehub_sensor_fusion_analytics.json"))
    args = parser.parse_args()

    anomalies = read_json(args.anomalies, {})
    dashboard = read_json(args.dashboard, {})
    payload = build_thehub_export(anomalies if isinstance(anomalies, dict) else {}, dashboard if isinstance(dashboard, dict) else {})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "contract": payload["export_contract"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
