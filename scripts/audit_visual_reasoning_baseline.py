#!/usr/bin/env python3
"""Static audit for Skywatcher's legacy visual-reasoning implementation surface.

This scanner is intentionally descriptive rather than semantic: every numeric
literal that can be reached in the bounded target surface is preserved in the
report instead of guessing whether it is a harmless algorithmic constant or a
meaningful threshold. Vector 2 therefore cannot silently lose a magic number;
Vector 3 can adjudicate each candidate against the canonical parameter registry.

The audit also inventories mixed-domain markers that must remain quarantined
from the canonical visual-reasoning engine.
"""

from __future__ import annotations

import argparse
import ast
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

EXPLICIT_TARGETS = (
    Path("fr24/rlsm_pipeline.py"),
    Path("fr24/rlsm_unlabeled.py"),
)

MIXED_DOMAIN_MARKERS = (
    "P_ROUTE",
    "FR24_ROUTE_PROXIMITY",
    "ADS_B_GAP",
    "route_proximity",
    "visual_feature_proximity_score",
)

RLSM_SEMANTIC_MARKERS = (
    "quarry",
    "tank",
    "pad",
    "antenna",
    "clearing",
    "facility_cluster",
)


@dataclass(frozen=True)
class NumericLiteral:
    path: str
    line: int
    column: int
    value: int | float
    context: str
    assignment: str | None
    classification: str


@dataclass(frozen=True)
class MarkerHit:
    path: str
    marker: str
    count: int
    classification: str


class _NumericVisitor(ast.NodeVisitor):
    def __init__(self, rel_path: str) -> None:
        self.rel_path = rel_path
        self.function_stack: list[str] = []
        self.assignment_stack: list[str | None] = []
        self.rows: list[NumericLiteral] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self.function_stack.append(node.name)
        self.generic_visit(node)
        self.function_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self.function_stack.append(node.name)
        self.generic_visit(node)
        self.function_stack.pop()

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        target = ",".join(_target_name(item) for item in node.targets)
        self.assignment_stack.append(target)
        self.visit(node.value)
        self.assignment_stack.pop()

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:  # noqa: N802
        target = _target_name(node.target)
        self.assignment_stack.append(target)
        if node.value is not None:
            self.visit(node.value)
        self.assignment_stack.pop()

    def visit_Constant(self, node: ast.Constant) -> None:  # noqa: N802
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            return
        assignment = self.assignment_stack[-1] if self.assignment_stack else None
        context = self.function_stack[-1] if self.function_stack else "<module>"
        classification = _classify_literal(assignment, context)
        self.rows.append(
            NumericLiteral(
                path=self.rel_path,
                line=node.lineno,
                column=node.col_offset,
                value=node.value,
                context=context,
                assignment=assignment,
                classification=classification,
            )
        )


def _target_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, (ast.Tuple, ast.List)):
        return ",".join(_target_name(item) for item in node.elts)
    return type(node).__name__


def _classify_literal(assignment: str | None, context: str) -> str:
    if assignment and assignment.upper() == assignment and any(ch.isalpha() for ch in assignment):
        return "NAMED_CONSTANT_PARAMETER_CANDIDATE"
    if assignment and ("WEIGHT" in assignment.upper() or "THRESH" in assignment.upper()):
        return "WEIGHT_OR_THRESHOLD_PARAMETER_CANDIDATE"
    if context.startswith("test_"):
        return "TEST_LITERAL"
    return "ALGORITHM_LITERAL_REQUIRES_ADJUDICATION"


def target_files(root: Path = REPO_ROOT) -> list[Path]:
    files = {root / rel for rel in EXPLICIT_TARGETS}
    files.update(root.glob("satim_*.py"))
    files.update((root / "fr24" / "calibration").glob("*.py"))
    return sorted(path for path in files if path.is_file())


def numeric_inventory(root: Path = REPO_ROOT) -> list[NumericLiteral]:
    rows: list[NumericLiteral] = []
    for path in target_files(root):
        rel = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        visitor = _NumericVisitor(rel)
        visitor.visit(tree)
        rows.extend(visitor.rows)
    return rows


def marker_inventory(root: Path = REPO_ROOT) -> list[MarkerHit]:
    rows: list[MarkerHit] = []
    for path in target_files(root):
        rel = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        for marker in MIXED_DOMAIN_MARKERS:
            count = text.count(marker)
            if count:
                rows.append(MarkerHit(rel, marker, count, "MIXED_DOMAIN_REVIEW"))
        if rel == "fr24/rlsm_unlabeled.py":
            lower = text.lower()
            for marker in RLSM_SEMANTIC_MARKERS:
                count = lower.count(marker.lower())
                if count:
                    rows.append(MarkerHit(rel, marker, count, "RLSM_SEMANTIC_BOUNDARY_CONFLICT"))
    return rows


def root_satim_classification(root: Path = REPO_ROOT) -> dict[str, Any]:
    from skywatcher.core.module_boundaries import MODULE_BOUNDARIES

    root_names = {path.name for path in root.glob("satim_*.py")}
    classified: dict[str, str] = {}
    for bucket, patterns in MODULE_BOUNDARIES.items():
        for pattern in patterns:
            if pattern in root_names:
                classified[pattern] = bucket
    return {
        "denominator": len(root_names),
        "classified": dict(sorted(classified.items())),
        "unclassified": sorted(root_names - set(classified)),
    }


def audit(root: Path = REPO_ROOT) -> dict[str, Any]:
    numeric = numeric_inventory(root)
    markers = marker_inventory(root)
    classification = root_satim_classification(root)
    return {
        "audit_version": "0.2.0",
        "scope": "bounded_visual_baseline",
        "target_file_count": len(target_files(root)),
        "numeric_literal_count": len(numeric),
        "numeric_literals": [asdict(row) for row in numeric],
        "marker_hits": [asdict(row) for row in markers],
        "root_satim_classification": classification,
        "invariants": {
            "all_numeric_literals_preserved_for_adjudication": True,
            "numeric_literal_presence_does_not_equal_parameter_validation": True,
            "unclassified_root_satim_required": 0,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    report = audit()
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")

    if args.check and report["root_satim_classification"]["unclassified"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
