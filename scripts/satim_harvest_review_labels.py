#!/usr/bin/env python3
"""Harvest manual-review outcomes into SATIM ground truth.

Closes the active-learning loop: reviewer decisions recorded in the FR24
``ManualReviewQueue`` (SQLite) are mapped to true-positive / false-positive labels
and appended to a calibration set's ``ground_truth.csv``, which the empirical
fitter then re-consumes. Each calibration pass therefore becomes continuous rather
than one-shot.

A reviewed item contributes a label when its ``metadata`` JSON carries
``image_id`` and ``false_positive_class`` and its resolution maps to a verdict
(confirmed -> real feature, rejected -> false positive).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fr24.manual_review_queue import ManualReviewQueue  # noqa: E402
from satim_calibration import load_calibration_set  # noqa: E402
from satim_ground_truth import (  # noqa: E402
    GROUND_TRUTH_FILE,
    append_ground_truth,
    normalize_fp_class,
)

_CONFIRMED = {"confirmed", "approved", "real", "persists", "accept", "accepted", "tp"}
_REJECTED = {"rejected", "false_positive", "artifact", "fr24_only", "suppress", "fp"}


def resolution_to_flag(resolution: str | None) -> str | None:
    """Map a reviewer resolution string to ``is_false_positive`` (or ``None``)."""
    text = str(resolution or "").strip().lower()
    if not text:
        return None
    if any(token in text for token in _CONFIRMED):
        return "0"
    if any(token in text for token in _REJECTED):
        return "1"
    return None


def harvest_rows(
    reviewed_items: Sequence[Mapping[str, object]],
    aliases: Mapping[str, str] | None = None,
) -> list[dict[str, str]]:
    """Convert reviewed queue items into ground-truth rows."""
    out: list[dict[str, str]] = []
    for item in reviewed_items:
        flag = resolution_to_flag(item.get("resolution"))  # type: ignore[arg-type]
        if flag is None:
            continue
        meta = item.get("metadata")
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except (ValueError, TypeError):
                meta = {}
        if not isinstance(meta, Mapping):
            continue
        fp = normalize_fp_class(meta.get("false_positive_class"), aliases)
        if fp is None:
            continue
        out.append(
            {
                "image_id": str(meta.get("image_id", "")),
                "false_positive_class": fp,
                "confidence": str(meta.get("confidence", "")),
                "is_false_positive": flag,
                "source": f"review_queue:{item.get('item_id', '')}",
            }
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("set_dir", type=Path)
    parser.add_argument(
        "--queue-dir",
        type=Path,
        required=True,
        help="directory containing the review_queue.db SQLite store",
    )
    args = parser.parse_args()

    aliases = load_calibration_set(args.set_dir).false_positive_aliases
    queue = ManualReviewQueue(str(args.queue_dir))
    reviewed = queue.get_all(status="reviewed")
    rows = harvest_rows(reviewed, aliases)
    written = append_ground_truth(args.set_dir / GROUND_TRUTH_FILE, rows, aliases)
    print(f"harvested {len(rows)} labeled decisions; appended {written} new rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
