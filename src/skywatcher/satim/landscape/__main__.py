from __future__ import annotations

import argparse
import json
from pathlib import Path

from .benchmark import evaluate_benchmark_manifest
from .calibration import load_calibration_profile
from .classifier import assess_image


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run fail-closed SATIM landscape candidate recognition"
    )
    parser.add_argument("image")
    parser.add_argument(
        "--calibration",
        help="Calibration profile JSON; without it agriculture remains unresolved",
    )
    parser.add_argument("--benchmark", help="Benchmark manifest JSON")
    parser.add_argument("--temporal-recurrence", action="store_true")
    args = parser.parse_args()

    calibration = (
        load_calibration_profile(args.calibration) if args.calibration else None
    )
    benchmark = (
        evaluate_benchmark_manifest(args.benchmark) if args.benchmark else None
    )
    result = assess_image(
        Path(args.image),
        calibration=calibration,
        benchmark=benchmark,
        temporal_recurrence=args.temporal_recurrence,
    )
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
