"""OCR OBSERVATION NORMALIZATION (mission responsibility 5)

Normalizes raw OCR output into cleaned, structured observation rows and fuses
whole-image OCR with region OCR (flagging field conflicts). Wraps the existing,
tested implementations in ``fr24.ocr_parse`` and ``fr24.ocr_fusion`` (both pure
stdlib + regex — safe to import eagerly).

The prohibited-label vocabulary is preserved from ``fr24.ocr_fusion`` so the
candidate-only, no-auto-confirmation policy is honored consistently.
"""

from __future__ import annotations

from fr24.ocr_fusion import (
    DISALLOWED_REVIEW_STATUSES,
    fuse_records,
    run_fusion,
)
from fr24.ocr_parse import clean, confidence_score, find_first, parse_record

__all__ = [
    "clean",
    "confidence_score",
    "find_first",
    "parse_record",
    "fuse_records",
    "run_fusion",
    "DISALLOWED_REVIEW_STATUSES",
    "normalize_observation",
]


def normalize_observation(record: dict) -> dict:
    """Normalize a single raw OCR record into a cleaned observation dict.

    Thin convenience wrapper over :func:`fr24.ocr_parse.parse_record` that also
    attaches the derived confidence score, giving callers one call for the
    common "clean + parse + score" path.
    """
    parsed = parse_record(record)
    if "confidence" not in parsed:
        parsed["confidence"] = confidence_score(parsed)
    return parsed
