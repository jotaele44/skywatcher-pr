"""CSV exports for GATIM ledgers."""
from __future__ import annotations

import csv
from pathlib import Path

from tools.gatim.core.normalizer import SCHEMA
from tools.gatim.core.review_queue import next_action, review_reason, sort_for_review

REVIEW_SCHEMA = SCHEMA + ["queue_rank", "review_reason", "next_action"]


def write_ledger(rows: list, output_path: str | Path) -> None:
    with Path(output_path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SCHEMA)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_dict())


def write_review_queue(rows: list, output_path: str | Path) -> None:
    selected = sort_for_review(rows)
    with Path(output_path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_SCHEMA)
        writer.writeheader()
        for rank, row in enumerate(selected, start=1):
            out = row.to_dict()
            out.update({"queue_rank": str(rank), "review_reason": review_reason(row), "next_action": next_action(row)})
            writer.writerow(out)
