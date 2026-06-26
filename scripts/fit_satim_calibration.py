#!/usr/bin/env python3
"""Re-fit a SATIM calibration set from labeled cross-source outcomes.

Reads a set's ``ground_truth.csv`` (produced by
``scripts/satim_cross_source_check.py`` and/or
``scripts/satim_harvest_review_labels.py``), derives empirical
``scoring_adjustments`` and ``promotion_thresholds`` via :mod:`satim_fit`, and
writes a *new* versioned set (default ``<set>_v2``) without touching the source.
The emitted set is structured to pass ``scripts/validate_satim_calibration.py``:
the calibration id is bumped consistently across registry_entry.yaml,
marker_legend.yaml, and false_positive_classes.yaml.

Usage:
    python scripts/fit_satim_calibration.py data/satim_calibration/moca_fr24_2025
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from satim_fit import emit_fp_classes_yaml, fit_calibration  # noqa: E402
from satim_ground_truth import GROUND_TRUTH_FILE, read_ground_truth  # noqa: E402


def _bump_id(value: str, suffix: str) -> str:
    base = re.sub(r"_v\d+$", "", value.strip())
    return f"{base}{suffix}"


def _rewrite_id_line(path: Path, key: str, new_id: str) -> None:
    """Replace a top-level ``key: <id>`` line in a YAML file, in place."""
    if not path.exists():
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines:
        if line.startswith(f"{key}:"):
            out.append(f"{key}: {new_id}")
        else:
            out.append(line)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def refit_set(source_dir: Path, out_dir: Path, *, version_suffix: str = "_v2") -> Path:
    """Fit constants from ``source_dir`` and write a new set at ``out_dir``."""
    rows = read_ground_truth(source_dir / GROUND_TRUTH_FILE)
    if not rows:
        raise SystemExit(
            f"no labeled rows in {source_dir / GROUND_TRUTH_FILE}; "
            "run satim_cross_source_check.py or satim_harvest_review_labels.py first"
        )
    result = fit_calibration(rows)

    if out_dir.exists():
        shutil.rmtree(out_dir)
    shutil.copytree(source_dir, out_dir)
    # Don't carry the parent's ground-truth into the derived set.
    (out_dir / GROUND_TRUTH_FILE).unlink(missing_ok=True)

    fp_path = out_dir / "false_positive_classes.yaml"
    original = fp_path.read_text(encoding="utf-8")
    current_id = ""
    for line in original.splitlines():
        if line.startswith("calibration_id:"):
            current_id = line.split(":", 1)[1].strip()
            break
    new_id = _bump_id(current_id or "SATIM-CAL", version_suffix)

    fp_path.write_text(
        emit_fp_classes_yaml(
            original, new_id, result.scoring_adjustments, result.promotion_thresholds
        ),
        encoding="utf-8",
    )
    # Keep the id consistent across the set so the validator's cross-file check passes.
    _rewrite_id_line(out_dir / "registry_entry.yaml", "registry_id", new_id)
    _rewrite_id_line(out_dir / "marker_legend.yaml", "calibration_id", new_id)
    return out_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("set_dir", type=Path)
    parser.add_argument(
        "--out", type=Path, default=None, help="output set dir (default: <set>_v2 sibling)"
    )
    args = parser.parse_args()

    out_dir = args.out or args.set_dir.with_name(args.set_dir.name + "_v2")
    written = refit_set(args.set_dir, out_dir)
    print(f"wrote refitted set to {written}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
