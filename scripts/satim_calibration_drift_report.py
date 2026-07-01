#!/usr/bin/env python3
"""Report drift between an active SATIM calibration set and control ground truth.

The active set's ``scoring_adjustments`` / ``promotion_thresholds`` are
hand-picked (see ``docs/SATIM_CALIBRATION.md``). ``data/satim_calibration/
control_moca_groundtruth/`` carries real, orthorectified-imagery-verified
outcomes for a small number of exemplars. Nothing currently compares the two,
so drift between the hand-picked constants and what the control evidence
would support is invisible. This script makes that comparison visible; it
does not write anything or promote a refit (use ``scripts/fit_satim_calibration.py``
for that once ground truth is substantial enough to act on).

Usage::

    python scripts/satim_calibration_drift_report.py
    python scripts/satim_calibration_drift_report.py --active data/satim_calibration/<set>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from satim_calibration import CANONICAL_FALSE_POSITIVE_CLASSES, load_calibration_set  # noqa: E402
from satim_fit import THRESHOLD_ORDER, fit_calibration  # noqa: E402
from satim_ground_truth import GROUND_TRUTH_FILE, read_ground_truth  # noqa: E402

CAVEAT = (
    "Control evidence is currently thin (see the n counts above; "
    "data/satim_calibration/control_moca_groundtruth/ground_truth.csv has one "
    "exemplar per canonical class). This is a drift signal to grow ground "
    "truth against, not a basis for auto-adopting the fit."
)


def build_report(active_set_dir: Path, control_set_dir: Path) -> str:
    active = load_calibration_set(active_set_dir)
    rows = read_ground_truth(control_set_dir / GROUND_TRUTH_FILE)
    fit = fit_calibration(rows)

    lines = [
        "SATIM calibration drift report",
        f"  active set:  {active.calibration_id} ({active_set_dir})",
        f"  control set: {control_set_dir} ({fit.n_rows} ground-truth rows)",
        "",
        "scoring_adjustments (active vs. empirical fit from control evidence):",
    ]
    active_adjustments = active.scoring_adjustments
    for cls in CANONICAL_FALSE_POSITIVE_CLASSES:
        active_val = active_adjustments.get(cls, 0.0)
        fit_val = fit.scoring_adjustments.get(cls, 0.0)
        stats = fit.class_stats.get(cls)
        n = stats.n if stats else 0
        delta = round(fit_val - active_val, 4)
        lines.append(
            f"  {cls:<16} active={active_val:+.4f}  fit={fit_val:+.4f}  "
            f"delta={delta:+.4f}  (n={n})"
        )

    lines.append("")
    lines.append("promotion_thresholds (active vs. empirical fit):")
    for band in THRESHOLD_ORDER:
        active_val = active.promotion_thresholds.get(band, 0.0)
        fit_val = fit.promotion_thresholds.get(band, 0.0)
        delta = round(fit_val - active_val, 4)
        lines.append(
            f"  {band:<24} active={active_val:.4f}  fit={fit_val:.4f}  delta={delta:+.4f}"
        )

    lines.append("")
    lines.append(f"NOTE: {CAVEAT}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--active",
        type=Path,
        default=Path("data/satim_calibration/moca_fr24_2025"),
        help="active calibration set directory",
    )
    parser.add_argument(
        "--control",
        type=Path,
        default=Path("data/satim_calibration/control_moca_groundtruth"),
        help="control ground-truth calibration set directory",
    )
    args = parser.parse_args(argv)
    print(build_report(args.active, args.control))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
