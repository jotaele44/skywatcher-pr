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
ROUTE_STOP_WORDS = {
    "ALT",
    "BAROMETRIC",
    "GROUND",
    "SPEED",
    "REG",
    "UTC",
    "VIEW",
    "ROUTE",
    "MORE",
    "INFO",
    "FOLLOW",
    "SHARE",
    "NOT",
    "AVAILABLE",
}

SHORT_AIRCRAFT_TYPES = {
    "AS50": "Airbus Helicopters H125",
    "B407": "Bell 407",
    "B429": "Bell 429 GlobalRanger",
    "C172": "Cessna 172K Skyhawk",
    "C401": "Cessna 401",
    "C402": "Cessna 402",
    "EC30": "Airbus Helicopters H130",
    "H125": "Airbus Helicopters H125",
    "H130": "Airbus Helicopters H130",
}

AIRCRAFT_PATTERNS = [
    re.compile(r"\b(Airbus\s+Helicopters?\s+H\d{3})\b", re.I),
    re.compile(r"\b(Airbus\s+H\d{3})\b", re.I),
    re.compile(r"\b(Bell\s+\d{3}[A-Za-z0-9 -]*)\b", re.I),
    re.compile(r"\b(Cessna\s+\d{3}[A-Za-z0-9 -]*)\b", re.I),
    re.compile(r"\b(EC\d{3}[A-Za-z0-9 -]*)\b", re.I),
]

FROM_RE = re.compile(r"\b(?:from|origin|depart(?:ed|ure)?)\s*:?\s*([A-Z0-9]{3,4})\b", re.I)
TO_RE = re.compile(r"\b(?:to|dest(?:ination)?|arrival)\s*:?\s*([A-Z0-9]{3,4})\b", re.I)
ROUTE_RE = re.compile(r"\b([A-Z0-9]{3,4})\b\s*(?:→|->|»\-?|>|-|to)\s*\b([A-Z0-9]{3,4}|N/?A)\b", re.I)
BARO_ROUTE_LINE_RE = re.compile(r"^(.+?)\s+BAROMETRIC\s+ALT\.?", re.I | re.M)
NEAR_RE = re.compile(r"\b(?:near|over|location)\s*:?\s*([A-Za-zÀ-ÿ0-9 .,'~/-]+)", re.I)

TIMESTAMP_PATTERNS = [
    re.compile(r"\b(\d{4}-\d{2}-\d{2})[ T](\d{2})[:\-](\d{2})(?:[:\-](\d{2}))?\b"),
    re.compile(r"\b(\d{2}/\d{2}/\d{4})[ T](\d{2})[:\-](\d{2})(?:[:\-](\d{2}))?\b"),
]

FR24_UTC_LINE_RE = re.compile(
    r"\b(?:[A-Za-z]{3},\s*)?([A-Za-z]{3})\s+(\d{1,2}),\s+(\d{4})\s*\|\s*"
    r"(\d{1,2}):(\d{2})\s*([AP]M)\s*u?tc\s*([+-]\d{2}:?\d{2})",
    re.I,
)


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
    if not match:
        return ""
    code = match.group(1)
    return "" if code in ROUTE_STOP_WORDS else code


def normalize_timestamp(date_text: str, hour: str, minute: str, second: str | None = None) -> str:
    second = second or "00"

    if "/" in date_text:
        dt = datetime.strptime(f"{date_text} {hour}:{minute}:{second}", "%m/%d/%Y %H:%M:%S")
        return dt.isoformat()

    return f"{date_text}T{hour}:{minute}:{second}"


def normalize_aircraft_type(value: str) -> str:
    value = " ".join(value.split())
    value = re.sub(r"\s+REG(?:ISTRATION)?\b.*$", "", value, flags=re.I).strip()
    return value


def extract_short_aircraft_type(text: str) -> str:
    # FR24 often renders the type beside the tail: "N407PR (B407".
    for match in re.finditer(r"\(([A-Z0-9]{3,4})\b", text, flags=re.I):
        code = match.group(1).upper()
        if code in SHORT_AIRCRAFT_TYPES:
            return SHORT_AIRCRAFT_TYPES[code]

    for code, aircraft_type in SHORT_AIRCRAFT_TYPES.items():
        if re.search(rf"\b{re.escape(code)}\b", text, flags=re.I):
            return aircraft_type

    return ""


def extract_aircraft_type(text: str) -> str:
    for pattern in AIRCRAFT_PATTERNS:
        match = pattern.search(text)
        if match:
            return normalize_aircraft_type(match.group(1))

    return extract_short_aircraft_type(text)


def normalized_baro_route_token(token: str) -> str | None:
    value = token.upper()
    if value in {"N/A", "NA"}:
        return ""
    if value in ROUTE_STOP_WORDS or value in SHORT_AIRCRAFT_TYPES:
        return None
    if re.fullmatch(r"[A-Z0-9]{3,4}", value):
        return value
    return None


def route_codes_from_baro_line(text: str) -> tuple[str, str]:
    match = BARO_ROUTE_LINE_RE.search(text)
    if not match:
        return "", ""

    prefix = match.group(1)
    tokens = re.findall(r"N/?A|\b[A-Za-z0-9]{3,4}\b", prefix, flags=re.I)

    codes: list[str] = []
    for token in tokens:
        code = normalized_baro_route_token(token)
        if code is not None:
            codes.append(code)

    if not codes:
        return "", ""
    if len(codes) == 1:
        return codes[0], ""
    return codes[-2], codes[-1]


def extract_route(text: str) -> tuple[str, str]:
    origin = ""
    destination = ""

    from_match = FROM_RE.search(text)
    if from_match:
        origin = airport_code(from_match.group(1))

    to_match = TO_RE.search(text)
    if to_match:
        destination = airport_code(to_match.group(1))

    route_match = ROUTE_RE.search(text)
    if route_match:
        origin = origin or airport_code(route_match.group(1))
        destination = destination or airport_code(route_match.group(2))

    baro_origin, baro_destination = route_codes_from_baro_line(text)
    origin = origin or baro_origin
    destination = destination or baro_destination

    return origin, destination


def extract_nearest_location(text: str) -> str:
    match = NEAR_RE.search(text)
    if not match:
        return ""

    value = match.group(1).strip()
    value = re.split(r"\n| {2,}|\t", value)[0].strip(" ,")
    return normalize_na(value)


def normalize_fr24_utc_line(match: re.Match[str]) -> str:
    month, day, year, hour, minute, meridiem, offset = match.groups()
    try:
        dt = datetime.strptime(
            f"{month} {day} {year} {hour}:{minute} {meridiem.upper()}",
            "%b %d %Y %I:%M %p",
        )
    except ValueError:
        return ""
    offset = offset if ":" in offset else f"{offset[:3]}:{offset[3:]}"
    return f"{dt:%Y-%m-%dT%H:%M}:00{offset}"


def extract_timeline_timestamp(text: str) -> tuple[bool, str]:
    utc_line = FR24_UTC_LINE_RE.search(text)
    if utc_line:
        ts = normalize_fr24_utc_line(utc_line)
        if ts:
            return True, ts

    lowered = text.lower()
    timeline_hint = (
        "timeline" in lowered
        or "playback" in lowered
        or "history" in lowered
        or "utc -04:00" in lowered
        or bool(re.search(r"\b\d{1,2}:\d{2}\s*(?:AM|PM)\b", text, flags=re.I))
    )

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
