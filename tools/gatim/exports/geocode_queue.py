"""Geocode-hold queue export for GATIM rows without direct coordinates."""
from __future__ import annotations

import csv
from pathlib import Path

GEOCODE_SCHEMA = [
    "gatim_id",
    "source_file",
    "source_dataset",
    "source_row",
    "title",
    "note",
    "url",
    "tags",
    "comment",
    "coord_status",
    "normalization_notes",
    "next_action",
]


def geocode_rows(rows: list) -> list:
    return [row for row in rows if row.coord_status in {"needs_geocode", "missing"}]


def write_geocode_queue(rows: list, output_path: str | Path) -> None:
    with Path(output_path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=GEOCODE_SCHEMA)
        writer.writeheader()
        for row in geocode_rows(rows):
            out = {key: str(getattr(row, key, "")) for key in GEOCODE_SCHEMA}
            out["next_action"] = "resolve_coordinate_or_hold"
            writer.writerow(out)
