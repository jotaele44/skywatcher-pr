#!/usr/bin/env python3
"""Auto-label FR24_3D_RENDER artifacts from a render sweep.

Reads a CSV of render-sweep observations (``feature_id, param_set, present`` and
optional ``image_id``) where each row records whether a feature appeared under one
render parameter set, and appends auto-labeled FR24_3D_RENDER false positives to a
calibration set's ``ground_truth.csv`` via :mod:`satim_render_diff`.

The renderer itself (asset/network-gated) is out of scope; this consumes its
cached output so it runs offline.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from satim_ground_truth import GROUND_TRUTH_FILE, append_ground_truth  # noqa: E402
from satim_render_diff import autolabel_render_diff  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("set_dir", type=Path)
    parser.add_argument(
        "--observations",
        type=Path,
        required=True,
        help="render-sweep observations CSV (feature_id, param_set, present)",
    )
    args = parser.parse_args()

    with args.observations.open(newline="", encoding="utf-8") as handle:
        observations = list(csv.DictReader(handle))
    rows = autolabel_render_diff(observations)
    written = append_ground_truth(args.set_dir / GROUND_TRUTH_FILE, rows)
    print(f"auto-labeled {len(rows)} render-diff artifacts; appended {written} new rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
