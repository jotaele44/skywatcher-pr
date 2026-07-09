"""Backward-compat shim. Logic moved to skywatcher.core.normalize_locations.
See docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md."""
from __future__ import annotations

from skywatcher.core.normalize_locations import (
    VALID_VISIBILITY,
    AliasIndex,
    build_location_index,
    load_simple_yaml,
    normalize_flight_locations,
    normalize_location,
)

__all__ = [
    "VALID_VISIBILITY",
    "AliasIndex",
    "build_location_index",
    "load_simple_yaml",
    "normalize_flight_locations",
    "normalize_location",
]

if __name__ == "__main__":
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser()
    parser.add_argument("raw_text")
    parser.add_argument("--config-dir", default="configs")
    args = parser.parse_args()
    print(json.dumps(normalize_location(args.raw_text, Path(args.config_dir)), indent=2, ensure_ascii=False))
