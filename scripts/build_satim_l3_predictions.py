"""Build SATIM L3 prediction JSON from OCR events plus registry enrichment.

This script intentionally does not read manual truth values as predictions.
It may read a truth/review CSV only to select the image_path rows to emit.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional


TIMESTAMP_RE = re.compile(
    r"(?P<date>\d{4}-\d{2}-\d{2})T(?P<time>\d{2}-\d{2}-\d{2})"
)


def clean(value: Any) -> str:
    return str(value or "").strip()


def read_csv(path: str | Path) -> List[Dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8", errors="replace") as handle:
        return list(csv.DictReader(handle))


def parse_bool(value: Any) -> bool:
    return clean(value).lower() in {"1", "true", "yes", "y"}


def index_registry(rows: Iterable[Mapping[str, Any]]) -> Dict[str, Mapping[str, Any]]:
    out: Dict[str, Mapping[str, Any]] = {}
    for row in rows:
        tail = clean(row.get("tail")).upper()
        if tail:
            out[tail] = row
    return out


def find_image_path(baseline_root: Path, sample_image: str) -> str:
    sample_image = clean(sample_image)
    if not sample_image:
        return ""

    matches = list(baseline_root.glob(f"**/{sample_image}"))
    if matches:
        return str(matches[0])

    return sample_image


def timestamp_from_filename(image_path: str) -> tuple[str, str, float]:
    name = Path(image_path).name
    match = TIMESTAMP_RE.search(name)
    if not match:
        return "", "", 0.0

    date = match.group("date")
    time = match.group("time").replace("-", ":")
    return f"{date}T{time}", "filename_timestamp", 0.70


def file_creation_timestamp(image_path: str) -> tuple[str, str, float]:
    path = Path(image_path)
    if not path.exists():
        return timestamp_from_filename(image_path)

    stat = path.stat()
    created = getattr(stat, "st_birthtime", None)
    if created is None:
        created = stat.st_mtime

    dt = datetime.fromtimestamp(created, tz=timezone.utc).replace(microsecond=0)
    return dt.isoformat().replace("+00:00", "Z"), "file_creation_time", 0.80


def select_image_paths(path: str | Path | None) -> set[str]:
    if not path:
        return set()

    rows = read_csv(path)
    return {
        clean(row.get("image_path"))
        for row in rows
        if clean(row.get("image_path"))
    }


def build_records(
    ocr_events: List[Mapping[str, Any]],
    registry_rows: List[Mapping[str, Any]],
    baseline_root: Path,
    image_filter: set[str] | None = None,
) -> List[Dict[str, Any]]:
    registry = index_registry(registry_rows)
    records: List[Dict[str, Any]] = []

    for row in ocr_events:
        sample_image = clean(row.get("sample_image"))
        image_path = find_image_path(baseline_root, sample_image)

        if image_filter and image_path not in image_filter:
            continue

        tail = clean(row.get("tail")).upper()
        reg = registry.get(tail, {})

        make_model = clean(reg.get("make_model"))
        registry_type = clean(reg.get("aircraft_type"))
        owner = clean(reg.get("owner_or_status"))

        aircraft_type = make_model or registry_type

        # Current OCR event packet does not expose timeline OCR presence.
        # Apply the canonical fallback: no visible/OCR timeline signal => file creation timestamp.
        event_timestamp, timestamp_source, timestamp_confidence = file_creation_timestamp(image_path)

        records.append({
            "image_path": image_path,
            "registration": tail,
            "callsign": tail,
            "altitude_ft": clean(row.get("alt_ft")),
            "ground_speed_mph": clean(row.get("speed_mph")),

            "aircraft_type": aircraft_type,
            "aircraft_type_source": "registry_make_model" if make_model else ("registry_aircraft_type" if registry_type else ""),
            "operator": owner,
            "operator_source": "registry_owner_or_status" if owner else "",

            # These remain blank until panel OCR emits route/location fields.
            "origin_code": "",
            "destination_code": "",
            "nearest_location": "",

            # Timestamp provenance fields.
            "event_timestamp": event_timestamp,
            "timestamp_source": timestamp_source,
            "timeline_present": False,
            "ocr_timeline_timestamp": "",
            "file_created_at": event_timestamp if timestamp_source == "file_creation_time" else "",
            "filename_timestamp": event_timestamp if timestamp_source == "filename_timestamp" else "",
            "timestamp_confidence": timestamp_confidence,

            "ocr_confidence": clean(row.get("best_confidence")),
            "source": "ocr_events.csv+ocr_new_tails.csv",
        })

    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="Build SATIM L3 prediction JSON")
    parser.add_argument("--ocr-events", required=True)
    parser.add_argument("--registry-tails", required=True)
    parser.add_argument("--baseline-root", default="data/FR24_baseline")
    parser.add_argument("--image-list-csv", default="")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    image_filter = select_image_paths(args.image_list_csv) if args.image_list_csv else set()

    records = build_records(
        ocr_events=read_csv(args.ocr_events),
        registry_rows=read_csv(args.registry_tails),
        baseline_root=Path(args.baseline_root),
        image_filter=image_filter or None,
    )

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"records": records}, indent=2), encoding="utf-8")

    print("records:", len(records))
    print("output:", out)


if __name__ == "__main__":
    main()
