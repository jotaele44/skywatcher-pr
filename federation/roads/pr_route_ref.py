"""Puerto Rico route-number parsing, pinned from spiderweb-pr.

DO NOT EDIT. This file is a verbatim extract of the authority implementation in
jotaele44/spiderweb-pr at commit c24b38d9fda8e5ad292f0e770330d81a19de806e,
spiderweb_pr_road_name_gazetteer_ingest/pipeline/road_gazetteer_ingest.py
(the stdlib-only parsing functions; the pandas ingest is not included).
The rules are explained in that repo's
spiderweb_pr_road_name_gazetteer_ingest/docs/ROAD_NUMBERING_LOGIC.md.

pr_route_ref.pin.json records this file's SHA-256; tests/test_pr_route_ref_pin.py
fails if the two disagree. To change the logic, change it in spiderweb-pr,
then re-extract this file and update the pin.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, Optional, Tuple

ROUTE_PATTERNS = [
    re.compile(r"\b(?:PR|P\.?R\.?|PRI|P\.R|PUERTO\s+RICO\s+(?:HIGHWAY|HWY|ROUTE)|CARRETERA(?:\s+ESTATAL)?|CARR\.?|RUTA)\s*[- ]?\s*(\d{1,5}[A-Z]?)\b", re.I),
    re.compile(r"\b(\d{1,5}[A-Z]?)\s*(?:PR|P\.?R\.?)\b", re.I),
]

def strip_diacritics(value: str) -> str:
    if value is None:
        return ""
    return "".join(c for c in unicodedata.normalize("NFKD", str(value)) if not unicodedata.combining(c))

def route_number_from_text(*values: object) -> str:
    text = " ".join(str(v) for v in values if v is not None and str(v).strip() and str(v).lower() != "nan")
    if not text:
        return ""
    for pat in ROUTE_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(1).upper()
    return ""

# Puerto Rico route-number bands (see docs/ROAD_NUMBERING_LOGIC.md).
# A band describes where a number sits in the numbering scheme, NOT the road's
# network class: one route can be signed primary, urban-primary, secondary or
# tertiary depending on the area it crosses. Bounds are inclusive; adjust here if
# DTOP/ACT review says otherwise. Published sources disagree on the tertiary upper
# bound (999 vs 9999); the wider bound is used.
ROUTE_NUMBER_BANDS: List[Tuple[int, int, str]] = [
    (1, 99, "primary_band"),
    (100, 299, "secondary_band"),
    (300, 9999, "tertiary_band"),
]

RAMAL_SUFFIX = "R"

_ROUTE_SPLIT = re.compile(r"^(\d{1,5})([A-Z]?)$")
_KM_PATTERN = re.compile(r"\b(?:KM|K\.M\.?|KIL[OÓ]METRO)\s*\.?\s*(\d{1,3}(?:[.,]\d{1,2})?)(?:\s*(?:HM|HEC?T[OÓ]METRO)\s*\.?\s*(\d))?", re.I)


def route_number_band(base_number: object) -> str:
    """Return the numbering band for a base route number, or 'unknown'."""
    try:
        n = int(str(base_number).strip())
    except (TypeError, ValueError):
        return "unknown"
    for lo, hi, band in ROUTE_NUMBER_BANDS:
        if lo <= n <= hi:
            return band
    return "unknown"


def split_route_number(route_number: str) -> Tuple[str, str]:
    """Split '3R' -> ('3', 'R'); '191' -> ('191', ''); unparseable -> ('', '')."""
    m = _ROUTE_SPLIT.match(str(route_number or "").strip().upper())
    if not m:
        return "", ""
    return str(int(m.group(1))), m.group(2)


def km_marker_from_text(*values: object) -> Optional[float]:
    """Parse a kilometre marker ('Km 12.4', 'Carr. 3 Km 5 Hm 2') to kilometres."""
    text = " ".join(str(v) for v in values if v is not None and str(v).strip() and str(v).lower() != "nan")
    m = _KM_PATTERN.search(strip_diacritics(text)) if text else None
    if not m:
        return None
    km = float(m.group(1).replace(",", "."))
    if m.group(2):
        km += int(m.group(2)) / 10.0
    return round(km, 3)


def parse_route_ref(*values: object) -> Dict[str, object]:
    """Break a free-text road reference into its numbering parts."""
    route_number = route_number_from_text(*values)
    base, suffix = split_route_number(route_number)
    return {
        "route_number": route_number,
        "base_number": base,
        "suffix": suffix,
        "is_ramal": suffix == RAMAL_SUFFIX,
        "route_number_band": route_number_band(base) if base else "unknown",
        "km": km_marker_from_text(*values),
    }
