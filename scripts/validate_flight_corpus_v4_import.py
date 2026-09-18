#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "config" / "flight_corpus_v4.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))

    assert manifest["schema_version"] == "skywatcher.flight_corpus.import.v1"
    assert manifest["corpus_version"] == "V4"

    denominators = manifest["denominators"]
    contract_denominators = contract["denominators"]
    keys = (
        "nonempty_logical_records",
        "single_point_exclusions",
        "trajectory_eligible",
        "unordered_pair_denominator",
    )
    for key in keys:
        assert denominators[key] == contract_denominators[key], (
            f"denominator mismatch: {key}"
        )

    assert denominators["trajectory_eligible"] == (
        denominators["nonempty_logical_records"]
        - denominators["single_point_exclusions"]
    )
    assert denominators["unordered_pair_denominator"] == (
        denominators["trajectory_eligible"]
        * (denominators["trajectory_eligible"] - 1)
        // 2
    )

    dataset_ids: set[str] = set()
    dataset_paths: set[str] = set()
    for row in manifest["datasets"]:
        assert row["dataset_id"] not in dataset_ids, "duplicate dataset_id"
        assert row["path"] not in dataset_paths, "duplicate dataset path"
        dataset_ids.add(row["dataset_id"])
        dataset_paths.add(row["path"])

        path = (args.manifest.parent / row["path"]).resolve()
        assert path.is_file(), f"missing dataset: {row['path']}"
        assert sha256(path) == row["sha256"], f"hash mismatch: {row['path']}"

    required_blockers = set(contract["blocked"])
    assert required_blockers.issubset(set(manifest["blocked"])), (
        "V4 blocker silently removed"
    )

    print("FLIGHT_CORPUS_V4_IMPORT=PASS")
    print(f"DATASETS={len(manifest['datasets'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
