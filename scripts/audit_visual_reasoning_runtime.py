#!/usr/bin/env python3
"""Audit canonical SATIM visual-reasoning runtime modules against frozen registries."""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PATHS = (
    REPO_ROOT / "src/skywatcher/satim/visual_reasoning_runtime.py",
    REPO_ROOT / "src/skywatcher/satim/infrastructure_reasoning.py",
    REPO_ROOT / "src/skywatcher/satim/shadow_photometry.py",
)
PARAMETER_REGISTRY = REPO_ROOT / "configs/visual_reasoning/parameter_registry_v0_2.yaml"
REASON_REGISTRY = REPO_ROOT / "configs/visual_reasoning/reason_codes_v0_2.yaml"
PROHIBITED_LEGACY_REFERENCES = (
    "satim_visual_route_gap",
    "fr24.rlsm_unlabeled",
    "fr24/rlsm_unlabeled.py",
)
PARAMETER_ID_RE = re.compile(r"^[A-Z][A-Z0-9_]*\.[A-Z0-9_.]+$")


class RuntimeVisitor(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.parameter_ids: set[str] = set()
        self.reason_codes: set[str] = set()
        self.float_compare_literals: list[dict[str, Any]] = []

    def visit_Constant(self, node: ast.Constant) -> None:  # noqa: N802
        if isinstance(node.value, str):
            if node.value.startswith("RC_"):
                self.reason_codes.add(node.value)
            elif PARAMETER_ID_RE.fullmatch(node.value) and not node.value.endswith(".*"):
                self.parameter_ids.add(node.value)
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:  # noqa: N802
        values = [node.left, *node.comparators]
        for value in values:
            if isinstance(value, ast.Constant) and isinstance(value.value, float):
                if value.value not in {0.0, 1.0}:
                    self.float_compare_literals.append(
                        {
                            "path": str(self.path.relative_to(REPO_ROOT)),
                            "line": value.lineno,
                            "column": value.col_offset,
                            "value": value.value,
                        }
                    )
        self.generic_visit(node)


def audit() -> dict[str, Any]:
    parameter_ids: set[str] = set()
    reason_codes: set[str] = set()
    float_compare_literals: list[dict[str, Any]] = []
    combined_source: list[str] = []

    for path in RUNTIME_PATHS:
        source = path.read_text(encoding="utf-8")
        combined_source.append(source)
        tree = ast.parse(source, filename=path.as_posix())
        visitor = RuntimeVisitor(path)
        visitor.visit(tree)
        parameter_ids.update(visitor.parameter_ids)
        reason_codes.update(visitor.reason_codes)
        float_compare_literals.extend(visitor.float_compare_literals)

    source_text = "\n".join(combined_source)
    parameter_text = PARAMETER_REGISTRY.read_text(encoding="utf-8")
    reason_text = REASON_REGISTRY.read_text(encoding="utf-8")
    missing_parameters = sorted(
        parameter_id for parameter_id in parameter_ids if parameter_id not in parameter_text
    )
    missing_reason_codes = sorted(
        reason_code for reason_code in reason_codes if reason_code not in reason_text
    )
    prohibited_hits = sorted(
        reference for reference in PROHIBITED_LEGACY_REFERENCES if reference in source_text
    )

    return {
        "audit_version": "0.2.0",
        "runtime_modules": [str(path.relative_to(REPO_ROOT)) for path in RUNTIME_PATHS],
        "parameter_ids_referenced": sorted(parameter_ids),
        "parameter_count": len(parameter_ids),
        "missing_parameter_registry_entries": missing_parameters,
        "reason_codes_referenced": sorted(reason_codes),
        "reason_code_count": len(reason_codes),
        "missing_reason_registry_entries": missing_reason_codes,
        "prohibited_legacy_references": prohibited_hits,
        "unregistered_float_compare_literals": float_compare_literals,
        "pass": not (
            missing_parameters
            or missing_reason_codes
            or prohibited_hits
            or float_compare_literals
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = audit()
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    if args.check and not report["pass"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
