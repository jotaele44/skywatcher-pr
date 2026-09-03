#!/usr/bin/env python3
# ruff: noqa: E402, I001
"""Freeze, route, and materialize a Skywatcher evidence batch in one command."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from skywatcher.evidence_adapters import materialize_visuals
from skywatcher.evidence_router import route_paths


def main() -> int:
    parser = argparse.ArgumentParser(description="Federated Skywatcher evidence ingest")
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()

    args.workspace.mkdir(parents=True, exist_ok=True)
    plan = route_paths(args.inputs)
    visuals = materialize_visuals(plan.manifest, args.workspace / "visuals")
    result = plan.to_dict()
    result["materialized_visuals"] = [row.to_dict() for row in visuals]
    materialization_states = {row.state for row in visuals}
    result["gates"]["VISUAL_MATERIALIZATION"] = (
        "PASS"
        if visuals and materialization_states == {"PASS"}
        else "BLOCKED"
        if "BLOCKED" in materialization_states
        else "OPEN"
    )
    output = args.workspace / "evidence_route_plan.json"
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(output)
    denominator = result["gates"]["DENOMINATOR"]
    return 0 if denominator != "BLOCKED" and "FAIL" not in materialization_states else 2


if __name__ == "__main__":
    raise SystemExit(main())
