"""
FR24 BATCH STATUS

Reads the batch run ledger CSV and reports completion counts per batch/mode.
Handles a missing or empty ledger by printing zero-count status and exiting
cleanly.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict, Counter
from pathlib import Path


def read_ledger(ledger_path: Path) -> list:
    if not ledger_path.exists():
        return []
    with ledger_path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def summarize(rows: list) -> dict:
    by_batch_mode: dict = defaultdict(Counter)
    all_images: dict = defaultdict(set)

    for row in rows:
        key = (row.get("batch_id", ""), row.get("mode", ""))
        status = row.get("status", "unknown")
        by_batch_mode[key][status] += 1
        all_images[key].add(row.get("image_path", ""))

    batches: dict = {}
    for (batch_id, mode), counts in sorted(by_batch_mode.items()):
        if batch_id not in batches:
            batches[batch_id] = {}
        batches[batch_id][mode] = {
            "total_rows": sum(counts.values()),
            "unique_images": len(all_images[(batch_id, mode)]),
            "complete": counts.get("complete", 0),
            "failed": counts.get("failed", 0),
            "skipped": counts.get("skipped", 0),
        }

    overall_counts: Counter = Counter()
    for counts in by_batch_mode.values():
        overall_counts.update(counts)

    return {
        "batches": batches,
        "overall": {
            "total_rows": sum(overall_counts.values()),
            "complete": overall_counts.get("complete", 0),
            "failed": overall_counts.get("failed", 0),
            "skipped": overall_counts.get("skipped", 0),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Report FR24 batch run status from ledger")
    parser.add_argument("--ledger", default="data/_manifests/fr24_audit/fr24_batch_run_ledger.csv")
    parser.add_argument("--batch-id", default="", help="Filter to a specific batch_id (empty = all)")
    args = parser.parse_args()

    ledger_path = Path(args.ledger)
    rows = read_ledger(ledger_path)

    if args.batch_id:
        rows = [r for r in rows if r.get("batch_id") == args.batch_id]

    summary = summarize(rows)
    summary["ledger"] = str(ledger_path)
    summary["ledger_exists"] = ledger_path.exists()
    summary["total_ledger_rows"] = len(rows)

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
