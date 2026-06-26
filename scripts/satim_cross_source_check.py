#!/usr/bin/env python3
"""Cross-source validation harness for SATIM marked features.

Implements a calibration set's ``required_cross_source_validation``: each feature
marked in ``labels.csv`` is checked against historical orthoimagery (Esri World
Imagery, Sentinel-2, USGS/NOAA) and recorded as confirmed (a real ground feature)
or refuted (an FR24-only rendering artifact). Verdicts are appended to the set's
``ground_truth.csv`` for the empirical fitter to consume.

Live imagery access is governed by the environment's network policy, so this
harness is **cache-driven**: it reads verdicts from a CSV (``--verdicts``) and can
therefore run fully offline. The verdicts file has columns
``image_id, false_positive_class, verdict, source`` where ``verdict`` is
``confirmed`` / ``refuted`` (synonyms: ``persists`` / ``fr24_only``).
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from satim_calibration import load_calibration_set  # noqa: E402
from satim_ground_truth import (  # noqa: E402
    GROUND_TRUTH_FILE,
    append_ground_truth,
    normalize_fp_class,
)

_CONFIRMED = {"confirmed", "persists", "real", "tp"}
_REFUTED = {"refuted", "fr24_only", "artifact", "fp"}


def _verdict_key(image_id: str, fp_class: str, aliases: Mapping[str, str]) -> tuple[str, str]:
    return (str(image_id).strip(), normalize_fp_class(fp_class, aliases) or "")


def load_verdicts(
    path: Path, aliases: Mapping[str, str]
) -> dict[tuple[str, str], dict[str, str]]:
    """Index cached verdicts by (image_id, canonical FP class)."""
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    index: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        key = _verdict_key(row.get("image_id", ""), row.get("false_positive_class", ""), aliases)
        if key[1]:
            index[key] = row
    return index


def build_ground_truth_rows(
    labels: Sequence,
    verdicts: Mapping[tuple[str, str], Mapping[str, str]],
    aliases: Mapping[str, str],
) -> list[dict[str, str]]:
    """Join cross-source verdicts onto marked features into ground-truth rows."""
    out: list[dict[str, str]] = []
    for label in labels:
        fp = normalize_fp_class(label.false_positive_class, aliases)
        if fp is None:
            continue
        verdict_row = verdicts.get((str(label.image_id).strip(), fp))
        if verdict_row is None:
            continue
        verdict = str(verdict_row.get("verdict", "")).strip().lower()
        if verdict in _CONFIRMED:
            is_fp = "0"
        elif verdict in _REFUTED:
            is_fp = "1"
        else:
            continue
        out.append(
            {
                "image_id": label.image_id,
                "false_positive_class": fp,
                "confidence": f"{label.confidence:.4f}",
                "is_false_positive": is_fp,
                "source": verdict_row.get("source", "cross_source"),
            }
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("set_dir", type=Path)
    parser.add_argument(
        "--verdicts",
        type=Path,
        required=True,
        help="cached cross-source verdicts CSV (offline input)",
    )
    args = parser.parse_args()

    calibration_set = load_calibration_set(args.set_dir)
    aliases = calibration_set.false_positive_aliases
    verdicts = load_verdicts(args.verdicts, aliases)
    rows = build_ground_truth_rows(calibration_set.labels, verdicts, aliases)
    written = append_ground_truth(args.set_dir / GROUND_TRUTH_FILE, rows, aliases)
    print(f"matched {len(rows)} verdicts; appended {written} new ground-truth rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
