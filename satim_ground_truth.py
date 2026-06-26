"""Shared labeled-outcome store for empirical SATIM calibration.

Cross-source validation (``scripts/satim_cross_source_check.py``) and review-queue
harvesting (``scripts/satim_harvest_review_labels.py``) both append verdicts to a
per-set ``ground_truth.csv``; the empirical fitter (``scripts/fit_satim_calibration.py``)
consumes it. Centralising the schema and the append/dedupe logic here keeps the
three scripts consistent.

A row records, for one marked feature, whether cross-checking confirmed it as a
real ground feature (``is_false_positive=0``) or refuted it as an FR24-only
artifact / false positive (``is_false_positive=1``). False-positive classes are
normalized against the engine's canonical set (``satim_calibration``), optionally
via a set's ``false_positive_aliases``.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from satim_calibration import CANONICAL_FALSE_POSITIVE_CLASSES

GROUND_TRUTH_FILE = "ground_truth.csv"
GROUND_TRUTH_FIELDS = (
    "image_id",
    "false_positive_class",
    "confidence",
    "is_false_positive",
    "source",
)

# A verdict is identified by feature + provenance, so re-running a harness is
# idempotent but a second independent source can still add corroboration.
_DEDUPE_KEY = ("image_id", "false_positive_class", "source")


def normalize_fp_class(raw: Any, aliases: Mapping[str, str] | None = None) -> str | None:
    """Return the canonical FP class for ``raw`` or ``None`` if blank/unknown.

    Resolves via the engine's canonical set; a non-canonical value is mapped
    through ``aliases`` (a set's ``false_positive_aliases``) when supplied.
    """
    if raw is None:
        return None
    text = str(raw).strip().upper()
    if not text:
        return None
    if text in CANONICAL_FALSE_POSITIVE_CLASSES:
        return text
    if aliases:
        target = aliases.get(text)
        if target in CANONICAL_FALSE_POSITIVE_CLASSES:
            return target
    return None


def _row_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return tuple(str(row.get(field, "")).strip() for field in _DEDUPE_KEY)  # type: ignore[return-value]


def read_ground_truth(path: str | Path) -> list[dict[str, str]]:
    """Read existing ground-truth rows, or ``[]`` if the file is absent."""
    file = Path(path)
    if not file.exists():
        return []
    with file.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def normalize_row(
    row: Mapping[str, Any], aliases: Mapping[str, str] | None = None
) -> dict[str, str] | None:
    """Coerce a raw verdict into a canonical ground-truth row, or ``None``."""
    fp = normalize_fp_class(row.get("false_positive_class"), aliases)
    if fp is None:
        return None
    try:
        confidence = float(row.get("confidence"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    raw_fp_flag = str(row.get("is_false_positive", "")).strip().lower()
    if raw_fp_flag in ("1", "true", "yes", "fp"):
        is_fp = "1"
    elif raw_fp_flag in ("0", "false", "no", "tp"):
        is_fp = "0"
    else:
        return None
    return {
        "image_id": str(row.get("image_id", "")).strip(),
        "false_positive_class": fp,
        "confidence": f"{confidence:.4f}",
        "is_false_positive": is_fp,
        "source": str(row.get("source", "")).strip(),
    }


def append_ground_truth(
    path: str | Path,
    rows: Iterable[Mapping[str, Any]],
    aliases: Mapping[str, str] | None = None,
) -> int:
    """Append new verdicts, skipping any already present by feature+source.

    Returns the number of rows actually written.
    """
    file = Path(path)
    existing = read_ground_truth(file)
    seen = {_row_key(r) for r in existing}
    new_rows: list[dict[str, str]] = []
    for raw in rows:
        norm = normalize_row(raw, aliases)
        if norm is None:
            continue
        key = _row_key(norm)
        if key in seen:
            continue
        seen.add(key)
        new_rows.append(norm)
    if not new_rows:
        return 0

    file.parent.mkdir(parents=True, exist_ok=True)
    write_header = not file.exists()
    with file.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(GROUND_TRUTH_FIELDS))
        if write_header:
            writer.writeheader()
        writer.writerows(new_rows)
    return len(new_rows)
