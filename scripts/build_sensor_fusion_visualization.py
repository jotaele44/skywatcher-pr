#!/usr/bin/env python3
"""Build dashboard visualization payload for sensor-fusion analytics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def read_json(path: Path, default: object) -> object:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def build_visualization_payload(anomaly_payload: dict[str, object]) -> dict[str, object]:
    anomalies = anomaly_payload.get("anomalies", [])
    bands: dict[str, int] = {}
    by_corridor: dict[str, int] = {}
    if isinstance(anomalies, list):
        for item in anomalies:
            if not isinstance(item, dict):
                continue
            band = str(item.get("review_band", "unbanded"))
            corridor = str(item.get("corridor_id", "unassigned"))
            bands[band] = bands.get(band, 0) + 1
            by_corridor[corridor] = by_corridor.get(corridor, 0) + 1
    return {
        "dashboard": "sensor_fusion_analytics",
        "live_tracking": False,
        "operator_action": "review_context_only",
        "charts": {
            "review_bands": [{"band": key, "count": value} for key, value in sorted(bands.items())],
            "corridor_counts": [{"corridor_id": key, "count": value} for key, value in sorted(by_corridor.items())],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anomalies", type=Path, default=Path("outputs/sensor_fusion/anomaly_review.json"))
    parser.add_argument("--output", type=Path, default=Path("outputs/dashboard/sensor_fusion_analytics.json"))
    args = parser.parse_args()

    anomaly_payload = read_json(args.anomalies, {})
    payload = build_visualization_payload(anomaly_payload if isinstance(anomaly_payload, dict) else {})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "dashboard": payload["dashboard"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
