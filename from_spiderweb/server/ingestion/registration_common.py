"""
Shared helpers for aircraft-registration handling across the server ingestion
layer (ingest, reconcile, alerts).

`normalize_registration` mirrors fr24/rlsm_extractors.py::_normalize_for_match
(ASCII-fold + upper + strip) and additionally drops separators so that
"N-5854 Z", "n5854z" and "N5854Z" all compare equal.
"""
from __future__ import annotations

import csv
import unicodedata
from pathlib import Path
from typing import Iterable, List

# FR24 aircraft-detail columns shared by the events table, the FR24 export CSV,
# and the ingest mapping. Order is informational only.
AIRCRAFT_FIELDS = [
    "registration",
    "callsign",
    "aircraft_type",
    "operator",
    "origin_code",
    "destination_code",
    "altitude_ft",
    "ground_speed_mph",
    "flight_status",
    "image_path",
]


def _ascii_fold(value: str) -> str:
    return (
        unicodedata.normalize("NFKD", value)
        .encode("ascii", "ignore")
        .decode("ascii")
    )


def normalize_registration(value: object) -> str:
    """Normalize a registration for equality matching.

    Returns "" for empty/None input. Uppercases, ASCII-folds, and removes
    whitespace and separator characters (-, ., /).
    """
    if not value:
        return ""
    text = _ascii_fold(str(value)).upper().strip()
    for sep in (" ", "\t", "-", ".", "/"):
        text = text.replace(sep, "")
    return text


def load_known_registrations(path: Path) -> List[str]:
    """Load a known/expected registration list from a file.

    Accepts either a newline-delimited text file or a CSV with a
    ``registration`` (or ``callsign``) column. Returns normalized, de-duplicated
    registrations in first-seen order.
    """
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    first = lines[0] if lines else ""

    raw: Iterable[str]
    header = first.lower()
    if "registration" in header or "callsign" in header:
        # CSV with a named column.
        rows = list(csv.DictReader(lines))
        raw = [r.get("registration") or r.get("callsign") or "" for r in rows]
    else:
        # Newline-delimited list (optionally headerless single-column CSV).
        raw = [line.split(",")[0] for line in lines]

    seen: dict[str, None] = {}
    for item in raw:
        norm = normalize_registration(item)
        if norm and norm not in seen:
            seen[norm] = None
    return list(seen.keys())
