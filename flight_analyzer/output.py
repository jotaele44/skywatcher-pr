"""CSV output utilities for flight analysis results."""

import csv
from pathlib import Path
from typing import IO, Tuple

CSV_COLUMNS = [
    'filename',
    'flight_number',
    'registration',
    'aircraft_type',
    'callsign',
    'origin',
    'destination',
    'altitude_ft',
    'speed_kts',
    'heading_deg',
    'utc_time',
    'squawk',
    'operator',
    'route_shape',
    'purpose_label',
    'confidence',
    'reasoning',
    'ocr_raw_text',
]


def open_csv(path: str) -> Tuple[IO, csv.DictWriter]:
    """Open *path* for writing and return (file_handle, DictWriter) with header written."""
    fh = open(path, 'w', newline='', encoding='utf-8')
    writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction='ignore')
    writer.writeheader()
    return fh, writer


def build_row(filename: str, ocr_fields: dict, classification: dict) -> dict:
    """Merge filename, OCR fields, and classification result into a single CSV row."""
    row = {'filename': filename}
    row.update(ocr_fields)
    row.update(classification)
    # Ensure all columns are present (missing keys stay as empty string)
    for col in CSV_COLUMNS:
        row.setdefault(col, '')
    return row


def write_error_row(writer: csv.DictWriter, filename: str, error_msg: str) -> None:
    """Write a placeholder row when processing fails for a given file."""
    writer.writerow({
        'filename': filename,
        'purpose_label': 'error',
        'reasoning': error_msg,
        **{col: '' for col in CSV_COLUMNS if col not in ('filename', 'purpose_label', 'reasoning')},
    })
