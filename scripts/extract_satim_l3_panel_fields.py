"""Extract SATIM L3 FR24 panel fields from OCR text.

The extractor is intentionally split into two layers:
1. OCR text acquisition, optional and environment-dependent.
2. Deterministic parsing of panel text into L3 fields.

Tests cover layer 2 so CI does not require Tesseract.
"""

from __future__ import annotations

import argparse
import csv
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping


N_A_VALUES = {"", "N/A", "NA", "N/A NOT AVAILABLE", "NOT AVAILABLE", "UNKNOWN", "NONE"}

AIRCRAFT_PATTERNS = [
    re.compile(r"\b(Airbus\s+Helicopters?\s+H\d{3})\b", re.I),
    re.compile(r"\b(Airbus\s+H\d{3})\b", re.I),
    re.compile(r"\b(Bell\s+\d{3}[A-Za-z0-9 -]*)\b", re.I),
    re.compile(r"\b(Cessna\s+\d{3}[A-Za-z0-9 -]*)\b", re.I),
    re.compile(r"\b(EC\d{3}[A-Za-z0-9 -]*)\b", re.I),
]

FROM_RE = re.compile(r"\b(?:from|origin|depart(?:ed|ure)?)\s*:?\s*([A-Z0-9]{3,4})\b", re.I)
TO_RE = re.compile(r"\b(?:to|dest(?:ination)?|arrival)\s*:?\s*([A-Z0-9]{3,4})\b", re.I)
ROUTE_RE = re.compile(r"\b([A-Z0-9]{3,4})\b\s*(?:→|->|-|to)\s*\b([A-Z0-9]{3,4})\b", re.I)
NEAR_RE = re.compile(r"\b(?:near|over|location)\s*:?\s*([A-Za-zÀ-ÿ0-9 .,'~/-]+)", re.I)

TIMESTAMP_PATTERNS = [
    re.compile(r"\b(\d{4}-\d{2}-\d{2})[ T](\d{2})[:\-](\d{2})(?:[:\-](\d{2}))?\b"),
    re.compile(r"\b(\d{2}/\d{2}/\d{4})[ T](\d{2})[:\-](\d{2})(?:[:\-](\d{2}))?\b"),
]


def clean(value: Any) -> str:
    return str(value or "").strip()


def normalize_na(value: Any) -> str:
    text = clean(value)
    return "" if text.upper() in N_A_VALUES else text


def airport_code(value: Any) -> str:
    text = normalize_na(value).upper()
    if not text:
        return ""
    match = re.search(r"\b([A-Z0-9]{3,4})\b", text)
    return match.group(1) if match else ""


def normalize_timestamp(date_text: str, hour: str, minute: str, second: str | None = None) -> str:
    second = second or "00"

    if "/" in date_text:
        dt = datetime.strptime(f"{date_text} {hour}:{minute}:{second}", "%m/%d/%Y %H:%M:%S")
        return dt.isoformat()

    return f"{date_text}T{hour}:{minute}:{second}"


def extract_aircraft_type(text: str) -> str:
    for pattern in AIRCRAFT_PATTERNS:
        match = pattern.search(text)
        if match:
            return " ".join(match.group(1).split())
    return ""


def extract_route(text: str) -> tuple[str, str]:
    origin = ""
    destination = ""

    from_match = FROM_RE.search(text)
    if from_match:
        origin = airport_code(from_match.group(1))

    to_match = TO_RE.search(text)
    if to_match:
        destination = airport_code(to_match.group(1))

    if not origin or not destination:
        route_match = ROUTE_RE.search(text)
        if route_match:
            origin = origin or airport_code(route_match.group(1))
            destination = destination or airport_code(route_match.group(2))

    return origin, destination


def extract_nearest_location(text: str) -> str:
    match = NEAR_RE.search(text)
    if not match:
        return ""

    value = match.group(1).strip()
    value = re.split(r"\n| {2,}|\t", value)[0].strip(" ,")
    return normalize_na(value)


def extract_timeline_timestamp(text: str) -> tuple[bool, str]:
    lowered = text.lower()
    timeline_hint = "timeline" in lowered or "playback" in lowered or "history" in lowered

    for pattern in TIMESTAMP_PATTERNS:
        match = pattern.search(text)
        if match:
            ts = normalize_timestamp(match.group(1), match.group(2), match.group(3), match.group(4))
            return True, ts

    return timeline_hint, ""


def parse_panel_text(text: str, image_path: str = "") -> Dict[str, Any]:
    origin_code, destination_code = extract_route(text)
    timeline_present, ocr_timeline_timestamp = extract_timeline_timestamp(text)

    return {
        "image_path": image_path,
        "aircraft_type": extract_aircraft_type(text),
        "origin_code": origin_code,
        "destination_code": destination_code,
        "nearest_location": extract_nearest_location(text),
        "timeline_present": str(timeline_present).lower(),
        "ocr_timeline_timestamp": ocr_timeline_timestamp,
        "ocr_text_available": str(bool(text.strip())).lower(),
    }


def read_csv(path: str | Path) -> List[Dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8", errors="replace") as handle:
        return list(csv.DictReader(handle))


def image_paths_from_csv(path: str | Path) -> List[str]:
    return [clean(row.get("image_path")) for row in read_csv(path) if clean(row.get("image_path"))]


def text_path_for_image(ocr_text_dir: Path, image_path: str) -> Path:
    return ocr_text_dir / f"{Path(image_path).stem}.txt"


def run_tesseract(image_path: str, text_path: Path) -> str:
    text_path.parent.mkdir(parents=True, exist_ok=True)
    base = text_path.with_suffix("")

    subprocess.run(
        ["tesseract", image_path, str(base), "--psm", "6"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    return text_path.read_text(encoding="utf-8", errors="replace") if text_path.exists() else ""


def load_or_ocr_text(image_path: str, ocr_text_dir: Path, run_ocr: bool) -> str:
    text_path = text_path_for_image(ocr_text_dir, image_path)

    if text_path.exists():
        return text_path.read_text(encoding="utf-8", errors="replace")

    if run_ocr:
        return run_tesseract(image_path, text_path)

    return ""


def write_rows(path: str | Path, rows: Iterable[Mapping[str, Any]]) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "image_path",
        "aircraft_type",
        "origin_code",
        "destination_code",
        "nearest_location",
        "timeline_present",
        "ocr_timeline_timestamp",
        "ocr_text_available",
    ]

    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract SATIM L3 panel fields from OCR text")
    parser.add_argument("--image-list-csv", required=True)
    parser.add_argument("--ocr-text-dir", default="/tmp/satim_l3_panel_text")
    parser.add_argument("--run-tesseract", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    ocr_text_dir = Path(args.ocr_text_dir)
    rows = []

    for image_path in image_paths_from_csv(args.image_list_csv):
        text = load_or_ocr_text(image_path, ocr_text_dir, args.run_tesseract)
        rows.append(parse_panel_text(text, image_path=image_path))

    write_rows(args.output, rows)

    print("records:", len(rows))
    print("output:", args.output)


if __name__ == "__main__":
    main()
