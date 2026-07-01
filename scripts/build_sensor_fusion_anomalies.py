#!/usr/bin/env python3
"""Build aggregate sensor-fusion anomaly review candidates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from skywatcher.fusion.anomaly_scoring import score_against_historical_baselines


def read_json(path: Path, default: object) -> object:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-baselines", type=Path, default=Path("outputs/sensor_fusion/corridor_baselines.json"))
    parser.add_argument("--historical-baselines", type=Path, default=Path("outputs/sensor_fusion/historical_baselines.json"))
    parser.add_argument("--output", type=Path, default=Path("outputs/sensor_fusion/anomaly_review.json"))
    args = parser.parse_args()

    current_payload = read_json(args.current_baselines, {"baselines": []})
    historical_payload = read_json(args.historical_baselines, {"baselines": []})
    current_records = current_payload.get("baselines", []) if isinstance(current_payload, dict) else []
    historical_records = historical_payload.get("baselines", []) if isinstance(historical_payload, dict) else []
    anomalies = score_against_historical_baselines(current_records, historical_records)
    payload = {
        "surface_type": "anomaly_review_context",
        "operator_action": "review_context_only",
        "live_tracking": False,
        "operational_cueing": False,
        "anomaly_count": len(anomalies),
        "anomalies": anomalies,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"anomalies": len(anomalies), "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
