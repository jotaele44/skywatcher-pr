from __future__ import annotations

import argparse
import json
from pathlib import Path

from .benchmark import evaluate_benchmark_manifest
from .classifier import assess_image


def main() -> int:
    parser = argparse.ArgumentParser(description="Run SATIM landscape candidate recognition")
    parser.add_argument("image", help="Image path")
    parser.add_argument("--benchmark", help="Benchmark manifest JSON")
    parser.add_argument("--temporal-recurrence", action="store_true")
    args = parser.parse_args()

    benchmark = evaluate_benchmark_manifest(args.benchmark) if args.benchmark else None
    result = assess_image(
        Path(args.image),
        benchmark=benchmark,
        temporal_recurrence=args.temporal_recurrence,
    )
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
