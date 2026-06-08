"""
FR24 REGION OCR PARSER

Converts region-level OCR JSONL (output of fr24_batch_run --mode region or
fr24_region_ocr.py) into structured candidate flight/event records.

Input record schema (one JSON object per line):
  image_path       str   absolute or relative path to source image
  image_name       str   filename
  sidecar_path     str   linked Google Takeout sidecar path (empty if none)
  sidecar_title    str   sidecar title field (empty if none)
  match_band       str   strong | reviewable | weak | unmatched
  resolved_status  str   matched_primary | sidecar_duplicate_conflict | unmatched_metadata_gap
  ocr_region       str   unique name for the crop (callsign | altitude | speed | route | panel | map | unknown)
  region_type      str   semantic type of region (callsign | altitude | speed | route | panel | map | unknown)
  region_bbox      dict  {"x":int, "y":int, "w":int, "h":int}
  ocr_text         str   raw OCR output
  ocr_char_count   int   character count of ocr_text
  ocr_status       str   complete | failed | not_run
  parser_version   str   version tag applied during OCR (e.g. "1.0.0")
  error            str   error message if ocr_status == failed

All output rows carry review_status = "region_parsed_candidate" or
"region_low_text_review". No "confirmed" labels are emitted.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Iterable, List

PARSER_VERSION = "1.0.0"

ALLOWED_REVIEW_STATUSES = {
    "region_parsed_candidate",
    "region_low_text_review",
    "region_ocr_failed",
    "region_manual_review_required",
}

AIRPORT_CODES = re.compile(r"\b(BQN|SJU|PSE|SIG|NRR|NIP|NUW|CPX|EIS|PBI|MAZ|ARE)\b")
FT_PATTERN = re.compile(r"\b([0-9,]+)\s*ft\b", re.I)
MPH_PATTERN = re.compile(r"\b([0-9]+)\s*mph\b", re.I)
CALLSIGN_PATTERN = re.compile(r"\b([A-Z0-9]{3,10})\s*\(([A-Z0-9]{2,5})\)", re.I)
REG_PATTERN = re.compile(r"\bREG\.?\s+([A-Z0-9\-]+)\b", re.I)
AIRCRAFT_PATTERNS = [
    r"\b(Sikorsky MH-?60T Jayhawk)",
    r"\b(Lockheed Martin C-?130J-?30 Super [A-Za-z\. ]*)",
    r"\b(Lockheed C-?130T Hercules)",
    r"\b(Boeing C-?17A Globemaster III)",
    r"\b(Grumman C-?2A Greyhound)",
    r"\b(Airbus Helicopters H125)",
    r"\b(Airbus Helicopters H145)",
    r"\b(Airbus Helicopters H130)",
    r"\b(Bell 407)",
    r"\b(Bell 429 GlobalRanger)",
    r"\b(Robinson R44(?: Raven II)?)",
    r"\b(Cessna Citation Sovereign)",
    r"\b(McDonnell Douglas AV-8B\+? Harrier II)",
    r"\b(Leonardo AW109SP GrandNew)",
    r"\b(Bombardier E-11A)",
    r"\b(Icon A5)",
    r"\b(High Altitude Balloon)",
]


def _clean(text: str) -> str:
    return " ".join((text or "").split())


def _find_first(patterns: Iterable[str], text: str) -> str:
    for pattern in patterns:
        m = re.search(pattern, text, flags=re.I)
        if m:
            return m.group(1).strip()
    return ""


def _extract_callsign(text: str) -> str:
    m = CALLSIGN_PATTERN.search(text)
    if m:
        return m.group(1).strip()
    return ""


def _extract_altitude(text: str) -> str:
    m = FT_PATTERN.search(text)
    if m:
        return m.group(1).replace(",", "")
    return ""


def _extract_speed(text: str) -> str:
    m = MPH_PATTERN.search(text)
    if m:
        return m.group(1)
    return ""


def _extract_airport_codes(text: str) -> tuple[str, str]:
    codes = AIRPORT_CODES.findall(text)
    origin = codes[0] if codes else ""
    dest = codes[1] if len(codes) > 1 else ""
    return origin, dest


def _extract_aircraft_type(text: str) -> str:
    return _find_first(AIRCRAFT_PATTERNS, text)


def _extract_registration(text: str) -> str:
    m = REG_PATTERN.search(text)
    if m:
        val = m.group(1).strip()
        return "" if val in {"N", "NO", "N/A"} else val
    return ""


def _parse_bbox(raw) -> str:
    if isinstance(raw, dict):
        return json.dumps(raw, separators=(",", ":"))
    return str(raw or "")


def parse_region_record(record: dict) -> dict:
    text = _clean(record.get("ocr_text", ""))
    region_type = (record.get("region_type") or record.get("ocr_region") or "unknown").lower()
    char_count = 0
    try:
        char_count = int(record.get("ocr_char_count") or 0)
    except Exception:
        pass

    row: dict = {
        "image_path": record.get("image_path", ""),
        "image_name": record.get("image_name", ""),
        "sidecar_path": record.get("sidecar_path", ""),
        "sidecar_title": record.get("sidecar_title", ""),
        "match_band": record.get("match_band", ""),
        "resolved_status": record.get("resolved_status", ""),
        "ocr_region": record.get("ocr_region", region_type),
        "region_type": region_type,
        "region_bbox": _parse_bbox(record.get("region_bbox", "")),
        "ocr_char_count": char_count,
        "ocr_status": record.get("ocr_status", "not_run"),
        "parser_version": PARSER_VERSION,
        "callsign_or_label": "",
        "registration": "",
        "aircraft_type": "",
        "origin_code": "",
        "destination_code": "",
        "barometric_altitude_ft": "",
        "ground_speed_mph": "",
        "flight_status": "",
        "confidence": 0.0,
        "review_status": "region_parsed_candidate",
        "ocr_text_excerpt": text[:500],
    }

    if record.get("ocr_status") == "failed":
        row["review_status"] = "region_ocr_failed"
        return row

    if char_count < 20:
        row["review_status"] = "region_low_text_review"
        if not text:
            return row

    if region_type == "callsign":
        row["callsign_or_label"] = _extract_callsign(text)
        if not row["callsign_or_label"]:
            row["callsign_or_label"] = text[:30].strip()

    elif region_type == "altitude":
        row["barometric_altitude_ft"] = _extract_altitude(text)

    elif region_type == "speed":
        row["ground_speed_mph"] = _extract_speed(text)

    elif region_type == "route":
        row["origin_code"], row["destination_code"] = _extract_airport_codes(text)

    else:
        row["callsign_or_label"] = _extract_callsign(text)
        row["registration"] = _extract_registration(text)
        row["aircraft_type"] = _extract_aircraft_type(text)
        row["origin_code"], row["destination_code"] = _extract_airport_codes(text)
        row["barometric_altitude_ft"] = _extract_altitude(text)
        row["ground_speed_mph"] = _extract_speed(text)

    score = 0.0
    if row["callsign_or_label"]:
        score += 0.20
    if row["aircraft_type"]:
        score += 0.20
    if row["registration"]:
        score += 0.15
    if row["barometric_altitude_ft"]:
        score += 0.15
    if row["ground_speed_mph"]:
        score += 0.15
    if row["origin_code"]:
        score += 0.15
    row["confidence"] = round(min(score, 1.0), 2)

    if char_count < 20:
        row["review_status"] = "region_low_text_review"
    elif row["confidence"] >= 0.20:
        row["review_status"] = "region_parsed_candidate"
    else:
        row["review_status"] = "region_manual_review_required"

    return row


FIELDNAMES = [
    "image_path",
    "image_name",
    "sidecar_path",
    "sidecar_title",
    "match_band",
    "resolved_status",
    "ocr_region",
    "region_type",
    "region_bbox",
    "ocr_char_count",
    "ocr_status",
    "parser_version",
    "callsign_or_label",
    "registration",
    "aircraft_type",
    "origin_code",
    "destination_code",
    "barometric_altitude_ft",
    "ground_speed_mph",
    "flight_status",
    "confidence",
    "review_status",
    "ocr_text_excerpt",
]


def parse_jsonl(input_jsonl: Path, output_csv: Path) -> dict:
    records: List[dict] = []
    with input_jsonl.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(parse_region_record(json.loads(line)))

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    if records:
        with output_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(records)
    else:
        with output_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()

    review_counts = Counter(r["review_status"] for r in records)
    return {
        "input_jsonl": str(input_jsonl),
        "output_csv": str(output_csv),
        "records": len(records),
        "review_status": dict(review_counts),
        "callsign_parsed": sum(bool(r["callsign_or_label"]) for r in records),
        "aircraft_type_parsed": sum(bool(r["aircraft_type"]) for r in records),
        "registration_parsed": sum(bool(r["registration"]) for r in records),
        "altitude_parsed": sum(bool(r["barometric_altitude_ft"]) for r in records),
        "speed_parsed": sum(bool(r["ground_speed_mph"]) for r in records),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse FR24 region OCR JSONL into structured event candidates")
    parser.add_argument(
        "--input-jsonl",
        default="data/_manifests/fr24_audit/fr24_region_ocr_results.jsonl",
    )
    parser.add_argument(
        "--output-csv",
        default="data/_manifests/fr24_audit/fr24_region_parsed_events.csv",
    )
    args = parser.parse_args()
    summary = parse_jsonl(Path(args.input_jsonl), Path(args.output_csv))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
