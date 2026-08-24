from __future__ import annotations
import argparse
import json
from pathlib import Path
from .benchmark import evaluate_benchmark_manifest
from .calibration import load_calibration_profile
from .classifier import assess_image

def main() -> int:
    p=argparse.ArgumentParser(description="Run fail-closed SATIM landscape candidate recognition")
    p.add_argument("image")
    p.add_argument("--calibration", help="Calibration profile JSON; without it agriculture remains unresolved")
    p.add_argument("--benchmark", help="Benchmark manifest JSON")
    p.add_argument("--temporal-recurrence", action="store_true")
    a=p.parse_args()
    calibration=load_calibration_profile(a.calibration) if a.calibration else None
    benchmark=evaluate_benchmark_manifest(a.benchmark) if a.benchmark else None
    result=assess_image(Path(a.image), calibration=calibration, benchmark=benchmark, temporal_recurrence=a.temporal_recurrence)
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    return 0

if __name__=="__main__": raise SystemExit(main())
