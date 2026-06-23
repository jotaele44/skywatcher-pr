"""CLI enrichment for SATIM candidates using PR airport footprint registries."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

from .features.airport_alignment import enrich_candidate_with_airport_alignment, load_airport_footprints


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def enrich_candidates(
    candidates_csv: Path,
    output_csv: Path,
    footprint_registries: list[Path],
) -> dict[str, int]:
    candidates = read_rows(candidates_csv)
    footprints = load_airport_footprints(footprint_registries)
    enriched = [enrich_candidate_with_airport_alignment(row, footprints) for row in candidates]
    write_rows(output_csv, enriched)
    return {"candidate_count": len(candidates), "airport_footprint_count": len(footprints)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich SATIM candidates with airport footprint alignment scores")
    parser.add_argument("--candidates-csv", required=True, type=Path)
    parser.add_argument("--output-csv", required=True, type=Path)
    parser.add_argument(
        "--footprint-registry",
        action="append",
        type=Path,
        default=[],
        help="Registry CSV path. May be supplied more than once.",
    )
    args = parser.parse_args()

    registries = args.footprint_registry or [
        Path("registry/puerto_rico_airspace_footprints.csv"),
        Path("registry/puerto_rico_helipads.csv"),
    ]
    enrich_candidates(args.candidates_csv, args.output_csv, registries)


if __name__ == "__main__":
    main()
