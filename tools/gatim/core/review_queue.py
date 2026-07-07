"""Review queue ranking for GATIM rows."""
from __future__ import annotations

PRIORITY_ORDER = {"P0_REVIEW": 0, "P1_REVIEW": 1, "P2_REVIEW": 2, "P2_CONTEXT": 3, "P3_GEOCODE": 4, "": 9}


def sort_for_review(rows: list) -> list:
    return sorted(
        rows,
        key=lambda row: (PRIORITY_ORDER.get(row.review_priority, 8), -float(row.confidence or 0), row.source_file, int(row.source_row)),
    )


def review_reason(row) -> str:
    if row.coord_status != "direct":
        return "coordinate resolution required"
    if row.class_primary in {"ILAP", "INFRASTRUCTURE"}:
        return "high-priority fixed-location review class"
    if row.class_primary == "UAP_CASE_ANCHOR":
        return "context anchor only"
    return "feature and terrain review candidate"


def next_action(row) -> str:
    if row.coord_status != "direct":
        return "geocode_or_hold"
    return "manual_satellite_review"
