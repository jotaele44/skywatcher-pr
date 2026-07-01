#!/usr/bin/env python3
"""Build historical sensor-fusion baselines from JSONL records."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from skywatcher.fusion.historical_baselines import build_historical_baselines


def read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    records: list[dict[str, object]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if text:
                records.append(json.loads(text))
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--air-events", type=Path, default=Path("outputs/sensor_fusion/air_events.jsonl"))
    parser.add_argument("--context-records", type=Path, default=Path("outputs/sensor_fusion/coastal_context.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("outputs/sensor_fusion/historical_baselines.json"))
    args = parser.parse_args()

    records = read_jsonl(args.air_events) + read_jsonl(args.context_records)
    baselines = build_historical_baselines(records)
    payload = {"baseline_type": "historical_aggregate", "live_tracking": False, "baselines": baselines}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"baselines": len(baselines), "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
