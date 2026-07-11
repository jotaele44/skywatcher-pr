#!/usr/bin/env python3
"""Build the SATIM L4 FR24 export CSV from the OCR events corpus.

L4 (`fr24.calibration.l4_registry_audit`) audits registry coverage over an
FR24 export keyed by aircraft fields. The processed OCR corpus already carries
this per-tail in ``outputs/ocr_events/events.csv`` but under different column
names. This shim does a pure column remap -- it invents no data.

Source columns (events.csv):
    tail, screenshots, in_known_fleet, registry_status, registry_type,
    registry_owner, best_confidence, status, alt_ft, speed_mph,
    airport_codes, sample_image

L4-expected columns:
    registration, callsign, operator, aircraft_type, tail_number
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

DEFAULT_SOURCE = "outputs/ocr_events/events.csv"
DEFAULT_OUTPUT = "data/fr24/exports/fr24_export.csv"

OUTPUT_FIELDS = [
    "registration",
    "callsign",
    "operator",
    "aircraft_type",
    "tail_number",
    "sightings",
    "registry_status",
]


def build(source: str, output: str) -> int:
    rows = list(csv.DictReader(Path(source).open(newline="", encoding="utf-8")))
    out_rows = []
    for row in rows:
        tail = (row.get("tail") or "").strip()
        if not tail:
            continue
        out_rows.append(
            {
                "registration": tail,
                "callsign": tail,
                "operator": (row.get("registry_owner") or "").strip(),
                "aircraft_type": (row.get("registry_type") or "").strip(),
                "tail_number": tail,
                "sightings": (row.get("screenshots") or "").strip(),
                "registry_status": (row.get("registry_status") or "").strip(),
            }
        )

    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(out_rows)
    return len(out_rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    count = build(args.source, args.output)
    print(f"wrote {count} rows -> {args.output}")


if __name__ == "__main__":
    main()
