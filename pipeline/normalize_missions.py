"""Backward-compat shim. Logic moved to skywatcher.core.normalize_missions.
See docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md."""
from __future__ import annotations

from skywatcher.core.normalize_missions import (
    normalize_blackout,
    normalize_mission,
    normalize_mission_record,
    normalize_behavior,
)

__all__ = [
    "normalize_blackout",
    "normalize_mission",
    "normalize_mission_record",
    "normalize_behavior",
]

if __name__ == "__main__":
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser()
    parser.add_argument("raw_text")
    parser.add_argument("--kind", choices=["mission", "behavior", "blackout"], default="mission")
    parser.add_argument("--config-dir", default="configs")
    args = parser.parse_args()
    func = {"mission": normalize_mission, "behavior": normalize_behavior, "blackout": normalize_blackout}[args.kind]
    print(json.dumps(func(args.raw_text, Path(args.config_dir)), indent=2, ensure_ascii=False))
