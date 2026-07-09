"""Backward-compat shim. Logic moved to skywatcher.core.normalize_operators.
See docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md."""
from __future__ import annotations

from skywatcher.core.normalize_operators import (
    NA_VALUES,
    OperatorIndex,
    build_operator_index,
    normalize_aircraft_identity,
    normalize_aircraft_record,
    normalize_operator,
)

__all__ = [
    "NA_VALUES",
    "OperatorIndex",
    "build_operator_index",
    "normalize_aircraft_identity",
    "normalize_aircraft_record",
    "normalize_operator",
]

if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser()
    parser.add_argument("raw_tail")
    parser.add_argument("--aircraft-type", default=None)
    args = parser.parse_args()
    print(json.dumps(normalize_aircraft_identity(args.raw_tail, args.aircraft_type), indent=2, ensure_ascii=False))
