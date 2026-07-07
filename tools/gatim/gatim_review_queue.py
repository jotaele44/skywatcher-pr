"""Build ranked GATIM review queues from normalized ledger rows."""
from __future__ import annotations

import csv
from pathlib import Path

from .gatim_normalizer import GATIMRow, SCHEMA

PRIORITY_ORDER = {"P0_REVIEW": 0, "P1_REVIEW": 1, "P2_REVIEW": 2, "P2_CONTEXT": 3, "P3_GEOCODE": 4, "": 9}


def sort_for_review(rows: list[GATIMRow]) -> list[GATIMRow]:
    return sorted(
        rows,
        key=lambda row: (PRIORITY_ORDER.get(row.review_priority, 8), -float(row.confidence or 0), row.source_file, int(row.source_row)),
    )


def write_review_queue(rows: list[GATIMRow], output_path: str | Path) -> None:
    selected = sort_for_review(rows)
    with Path(output_path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SCHEMA)
        writer.writeheader()
        for row in selected:
            writer.writerow(row.to_dict())
