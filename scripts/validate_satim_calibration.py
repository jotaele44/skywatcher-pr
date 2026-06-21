#!/usr/bin/env python3
"""Validate SATIM visual-analysis calibration sets.

Dependency-light integrity checker for ``data/satim_calibration/<set>/``
calibration packets. Mirrors the style of ``validate_airspace_export.py``:
errors accumulate and force a non-zero exit; warnings are reported but do not
fail the build (so the known non-canonical ``false_positive_class`` values in
the seed data stay visible without breaking CI).

Usage::

    python scripts/validate_satim_calibration.py data/satim_calibration
    python scripts/validate_satim_calibration.py data/satim_calibration/moca_fr24_2025
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any

# Allow running both as a script and via the package path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.normalize_locations import load_simple_yaml  # noqa: E402
from satim_calibration import (  # noqa: E402
    CANONICAL_FALSE_POSITIVE_CLASSES,
    FALSE_POSITIVE_FILE,
    LABELS_COLUMNS,
    LABELS_FILE,
    MARKER_LEGEND_FILE,
    REGISTRY_FILE,
)

REQUIRED_FILES = (
    "README.md",
    REGISTRY_FILE,
    MARKER_LEGEND_FILE,
    FALSE_POSITIVE_FILE,
    LABELS_FILE,
)
PROMOTION_THRESHOLD_KEYS = ("review", "cross_source_required", "promote_to_candidate")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_set(set_dir: Path) -> tuple[list[str], list[str]]:
    """Validate a single calibration set. Returns (errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []
    name = set_dir.name

    missing = [f for f in REQUIRED_FILES if not (set_dir / f).exists()]
    if missing:
        errors.append(f"{name}: missing required files: {', '.join(sorted(missing))}")
        return errors, warnings  # cannot continue without the core files

    try:
        registry = load_simple_yaml(set_dir / REGISTRY_FILE)
        marker_legend = load_simple_yaml(set_dir / MARKER_LEGEND_FILE)
        false_positives = load_simple_yaml(set_dir / FALSE_POSITIVE_FILE)
    except (ValueError, FileNotFoundError) as exc:
        errors.append(f"{name}: YAML parse error: {exc}")
        return errors, warnings

    # --- registry id consistency -------------------------------------------
    registry_id = registry.get("registry_id")
    if not registry_id:
        errors.append(f"{name}: registry_entry.yaml missing registry_id")
    for fname, doc in ((MARKER_LEGEND_FILE, marker_legend), (FALSE_POSITIVE_FILE, false_positives)):
        cid = doc.get("calibration_id")
        if registry_id and cid and cid != registry_id:
            errors.append(
                f"{name}: {fname} calibration_id '{cid}' != registry_id '{registry_id}'"
            )

    if not registry.get("evidence_tier"):
        warnings.append(f"{name}: registry_entry.yaml missing evidence_tier")
    if not registry.get("required_cross_source_validation"):
        warnings.append(f"{name}: registry_entry.yaml missing required_cross_source_validation")

    # --- marker legend ------------------------------------------------------
    marker_classes = marker_legend.get("marker_classes") or {}
    marker_types = set(marker_classes.keys())
    if not marker_types:
        errors.append(f"{name}: marker_legend.yaml defines no marker_classes")
    for marker, body in marker_classes.items():
        body = body or {}
        if not body.get("meaning") or not body.get("satim_role"):
            warnings.append(f"{name}: marker_class '{marker}' missing meaning/satim_role")
    if not marker_legend.get("promotion_checks"):
        warnings.append(f"{name}: marker_legend.yaml missing promotion_checks")

    # --- false-positive scoring + thresholds --------------------------------
    adjustments = false_positives.get("scoring_adjustments") or {}
    if not adjustments:
        errors.append(f"{name}: false_positive_classes.yaml missing scoring_adjustments")
    for cls, adj in adjustments.items():
        if not _is_number(adj):
            errors.append(f"{name}: scoring_adjustment for {cls} is not numeric ({adj!r})")
        elif not -1.0 <= float(adj) <= 0.0:
            warnings.append(
                f"{name}: scoring_adjustment for {cls} = {adj} is outside the "
                f"expected suppressive range [-1.0, 0.0]"
            )
    for canonical in CANONICAL_FALSE_POSITIVE_CLASSES:
        if canonical not in adjustments:
            warnings.append(
                f"{name}: canonical false_positive_class '{canonical}' has no scoring_adjustment"
            )

    # --- false-positive aliases (observed -> canonical) ---------------------
    aliases = false_positives.get("false_positive_aliases") or {}
    for observed, target in aliases.items():
        if target not in adjustments:
            errors.append(
                f"{name}: false_positive_aliases['{observed}'] -> '{target}' "
                f"is not a canonical scoring class"
            )

    thresholds = false_positives.get("promotion_thresholds") or {}
    missing_thresholds = [k for k in PROMOTION_THRESHOLD_KEYS if k not in thresholds]
    if missing_thresholds:
        errors.append(
            f"{name}: promotion_thresholds missing keys: {', '.join(missing_thresholds)}"
        )
    else:
        for key in PROMOTION_THRESHOLD_KEYS:
            val = thresholds[key]
            if not _is_number(val) or not 0.0 <= float(val) <= 1.0:
                errors.append(f"{name}: promotion_threshold '{key}' = {val!r} not in [0.0, 1.0]")
        if all(_is_number(thresholds[k]) for k in PROMOTION_THRESHOLD_KEYS):
            ordered = [float(thresholds[k]) for k in PROMOTION_THRESHOLD_KEYS]
            if not ordered[0] <= ordered[1] <= ordered[2]:
                errors.append(
                    f"{name}: promotion_thresholds must be ordered "
                    f"review <= cross_source_required <= promote_to_candidate (got {ordered})"
                )

    # --- labels.csv ---------------------------------------------------------
    with (set_dir / LABELS_FILE).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        header = set(reader.fieldnames or [])
        missing_cols = [c for c in LABELS_COLUMNS if c not in header]
        if missing_cols:
            errors.append(f"{name}: labels.csv missing columns: {', '.join(missing_cols)}")
        rows = list(reader)

    if not rows:
        warnings.append(f"{name}: labels.csv has no data rows")

    non_canonical: dict[str, int] = {}
    for i, row in enumerate(rows, start=2):  # row 1 is the header
        rid = (row.get("image_id") or f"row{i}").strip()
        # confidence in [0, 1]
        raw_conf = (row.get("confidence") or "").strip()
        try:
            conf = float(raw_conf)
            if not 0.0 <= conf <= 1.0:
                errors.append(f"{name}: {rid} confidence {conf} outside [0.0, 1.0]")
        except ValueError:
            errors.append(f"{name}: {rid} confidence is not a number ({raw_conf!r})")
        # marker_type must exist in the legend
        marker = (row.get("marker_type") or "").strip()
        if marker and marker_types and marker not in marker_types:
            errors.append(
                f"{name}: {rid} marker_type '{marker}' not defined in marker_legend.yaml"
            )
        # false_positive_class should resolve to a canonical class (warn only)
        fp = (row.get("false_positive_class") or "").strip()
        if fp and fp not in adjustments and aliases.get(fp) not in adjustments:
            non_canonical[fp] = non_canonical.get(fp, 0) + 1

    if non_canonical:
        detail = ", ".join(f"{k} x{v}" for k, v in sorted(non_canonical.items()))
        warnings.append(
            f"{name}: {sum(non_canonical.values())} label(s) use an unresolved "
            f"false_positive_class (not canonical and not aliased): {detail}"
        )

    return errors, warnings


def discover_sets(path: Path) -> list[Path]:
    if (path / REGISTRY_FILE).exists():
        return [path]
    return [p.parent for p in sorted(path.glob(f"*/{REGISTRY_FILE}"))]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate SATIM calibration sets")
    parser.add_argument(
        "path",
        nargs="?",
        default="data/satim_calibration",
        help="A calibration set dir or the calibration root (default: data/satim_calibration)",
    )
    args = parser.parse_args(argv)

    path = Path(args.path)
    if not path.exists():
        print(f"VALIDATION FAILED\n- path does not exist: {path}")
        return 1

    sets = discover_sets(path)
    if not sets:
        print(f"VALIDATION FAILED\n- no calibration sets (with {REGISTRY_FILE}) found under {path}")
        return 1

    all_errors: list[str] = []
    all_warnings: list[str] = []
    for set_dir in sets:
        errors, warnings = validate_set(set_dir)
        all_errors.extend(errors)
        all_warnings.extend(warnings)

    print(f"Validated {len(sets)} calibration set(s) under {path}")
    if all_warnings:
        print(f"\nWARNINGS ({len(all_warnings)}):")
        for w in all_warnings:
            print(f"- {w}")

    if all_errors:
        print(f"\nVALIDATION FAILED ({len(all_errors)} error(s)):")
        for e in all_errors:
            print(f"- {e}")
        return 1

    print("\nVALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
