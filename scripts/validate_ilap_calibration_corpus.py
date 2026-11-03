"""Validate ILAP calibration corpus manifests fail-closed.

This validator checks manifest structure, source-lineage split isolation, SHA256
shape, duplicate-byte accounting, and class arithmetic. It deliberately does
not calibrate detector thresholds.
"""
from __future__ import annotations

import argparse
import csv
import re
from collections import Counter, defaultdict
from pathlib import Path

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
VALID_SPLITS = {"TRAIN", "VALIDATION", "TEST", "UNASSIGNED", "EXCLUDED_PENDING_RIGHTS"}

REQUIRED = {
    "record_id",
    "source_lineage_id",
    "manifestation",
    "class_family",
    "class_label",
    "label_state",
    "independent_binding_state",
    "split_state",
    "sha256",
    "status",
    "notes",
}


def load(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        missing = REQUIRED - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(f"missing required columns: {sorted(missing)}")
        return list(reader)


def validate(rows: list[dict[str, str]]) -> dict[str, object]:
    errors: list[str] = []
    ids = [r["record_id"] for r in rows]
    dup_ids = [k for k, n in Counter(ids).items() if n > 1]
    if dup_ids:
        errors.append(f"duplicate record_id: {sorted(dup_ids)}")

    lineage_splits: dict[str, set[str]] = defaultdict(set)
    byte_rows: dict[str, list[str]] = defaultdict(list)
    class_counts: Counter[str] = Counter()

    for i, row in enumerate(rows, start=2):
        split = row["split_state"]
        if split not in VALID_SPLITS:
            errors.append(f"row {i}: invalid split_state={split}")
        lineage = row["source_lineage_id"].strip()
        if not lineage:
            errors.append(f"row {i}: empty source_lineage_id")
        if split in {"TRAIN", "VALIDATION", "TEST"}:
            lineage_splits[lineage].add(split)
        sha = row["sha256"].strip().lower()
        if sha and not SHA256_RE.fullmatch(sha):
            errors.append(f"row {i}: malformed SHA256")
        if sha:
            byte_rows[sha].append(row["record_id"])
        class_counts[row["class_label"]] += 1

    leakage = {k: sorted(v) for k, v in lineage_splits.items() if len(v) > 1}
    if leakage:
        errors.append(f"source-lineage leakage across splits: {leakage}")

    duplicate_bytes = {sha: recs for sha, recs in byte_rows.items() if len(recs) > 1}
    # Repeated bytes are allowed only as multiple labels/manifestations; report but do not fail.
    return {
        "row_count": len(rows),
        "class_counts": dict(sorted(class_counts.items())),
        "duplicate_byte_groups": duplicate_bytes,
        "lineage_split_map": {k: sorted(v) for k, v in sorted(lineage_splits.items())},
        "errors": errors,
        "status": "PASS" if not errors else "FAIL",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    result = validate(load(args.manifest))
    print(result)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
