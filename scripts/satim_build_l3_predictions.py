#!/usr/bin/env python3
"""Build the SATIM L3 predictions JSON from the OCR sightings corpus.

L3 (`fr24.calibration.l3_ocr_scoring`) compares per-screenshot OCR predictions
against ground truth, keyed by ``image_path``. The OCR pipeline already emitted
per-screenshot results to ``outputs/ocr_events/full_sightings.jsonl``; this shim
reshapes them into the JSON list L3's ``load_predictions`` accepts. No data is
invented -- only field names are mapped.

Sighting fields -> L3 prediction fields:
    path        -> image_path
    tail        -> callsign
    alt_ft      -> altitude_ft
    type_guess  -> aircraft_type
    airport_codes[0]/[1] -> origin_code / destination_code
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_SOURCE = "outputs/ocr_events/full_sightings.jsonl"
DEFAULT_OUTPUT = "reports/fr24/vision_ingest_output.json"


def build(source: str, output: str) -> int:
    records = []
    with Path(source).open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            s = json.loads(line)
            codes = s.get("airport_codes") or []
            records.append(
                {
                    "image_path": s.get("path", ""),
                    "callsign": s.get("tail") or "",
                    "altitude_ft": s.get("alt_ft") or "",
                    "aircraft_type": s.get("type_guess") or "",
                    "origin_code": codes[0] if len(codes) > 0 else "",
                    "destination_code": codes[1] if len(codes) > 1 else "",
                    "nearest_location": "",
                }
            )

    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
    return len(records)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    count = build(args.source, args.output)
    print(f"wrote {count} predictions -> {args.output}")


if __name__ == "__main__":
    main()
