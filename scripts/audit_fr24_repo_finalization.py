#!/usr/bin/env python3
"""Audit the FR24 repo-finalization operations manifest.

This is intentionally lightweight and stdlib-only. It verifies that the
operations chain is complete enough to act as the controlling build order before
the detailed FR24 visual parameter registry is implemented.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Iterable


REQUIRED_OPERATION_COUNT = 59
REQUIRED_OPERATION_MIN = 0
REQUIRED_OPERATION_MAX = 58
REQUIRED_HARDENING_LAYERS = {
    "CI",
    "VERSIONING",
    "CONFIG_DEFAULTS",
    "ERROR_TAXONOMY",
    "FIXTURE_POLICY",
    "REGRESSION_TESTS",
    "HUB_COMPATIBILITY",
    "RELEASE_CHECKLIST",
}
REQUIRED_STAGES = {
    "foundation_before_parameters",
    "parameter_registry",
    "family_modules",
    "fixtures_tests_regression",
    "ci_docs_finalization",
}


def load_manifest(path: pathlib.Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def audit_manifest(manifest: dict) -> list[str]:
    errors: list[str] = []

    operations = manifest.get("operations")
    if not isinstance(operations, list):
        return ["operations must be a list"]

    if len(operations) != REQUIRED_OPERATION_COUNT:
        errors.append(
            f"expected {REQUIRED_OPERATION_COUNT} operations, found {len(operations)}"
        )

    orders = [op.get("order") for op in operations]
    expected_orders = list(range(REQUIRED_OPERATION_MIN, REQUIRED_OPERATION_MAX + 1))
    if orders != expected_orders:
        errors.append("operation order must be contiguous 00-58")

    codes = [op.get("code", "") for op in operations]
    for order, code in zip(expected_orders, codes):
        prefix = f"{order:02d}_"
        if not isinstance(code, str) or not code.startswith(prefix):
            errors.append(f"operation {order:02d} code must start with {prefix!r}")

    layers = set(manifest.get("required_hardening_layers", []))
    missing_layers = sorted(REQUIRED_HARDENING_LAYERS - layers)
    if missing_layers:
        errors.append(f"missing hardening layers: {', '.join(missing_layers)}")

    stages = {op.get("stage") for op in operations}
    missing_stages = sorted(REQUIRED_STAGES - stages)
    if missing_stages:
        errors.append(f"missing operation stages: {', '.join(missing_stages)}")

    for op in operations:
        if op.get("required") is not True:
            errors.append(f"{op.get('code', '<unknown>')} must have required=true")
        if op.get("status") not in {"planned", "in_progress", "complete", "deferred"}:
            errors.append(f"{op.get('code', '<unknown>')} has invalid status")

    required_top_level = {
        "manifest_id",
        "registry_version",
        "repo",
        "active_branch",
        "architecture",
        "completion_rule",
    }
    missing_top_level = sorted(required_top_level - set(manifest))
    if missing_top_level:
        errors.append(f"missing top-level keys: {', '.join(missing_top_level)}")

    return errors


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        default="data/reference/fr24_repo_finalization_operations_v1.json",
        help="Path to the FR24 repo-finalization operations manifest.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    manifest_path = pathlib.Path(args.manifest)
    if not manifest_path.exists():
        print(f"ERROR: manifest not found: {manifest_path}", file=sys.stderr)
        return 2

    errors = audit_manifest(load_manifest(manifest_path))
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print("OK: FR24 repo-finalization operations manifest is audit-clean.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
