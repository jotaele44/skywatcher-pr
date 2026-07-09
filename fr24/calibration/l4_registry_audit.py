"""L4 SATIM calibration: aircraft/operator registry coverage audit."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from .models import LayerCalibrationResult, write_json

try:  # pragma: no cover
    from skywatcher.core.known_operators import KNOWN_OPERATORS
except Exception:
    KNOWN_OPERATORS = {}

ONBOARDING_THRESHOLD = {
    "minimum_sightings": 3,
    "requires_faa_confirmation": True,
    "requires_operational_source": True,
}

KNOWN_GAP_KEYWORDS = ("CBP", "CUSTOMS", "BORDER", "NOAA", "P-3", "DHC-8", "DOD", "SOCOM")


def load_csv(path: str | Path) -> List[Dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def registry_tokens(registry: Any = KNOWN_OPERATORS) -> set[str]:
    tokens: set[str] = set()
    if isinstance(registry, Mapping):
        iterable = registry.items()
    else:
        iterable = enumerate(registry or [])
    for key, value in iterable:
        tokens.add(str(key).upper())
        if isinstance(value, Mapping):
            for field in ("registration", "callsign", "operator", "agency", "tail_number"):
                if value.get(field):
                    tokens.add(str(value[field]).upper())
        elif value:
            tokens.add(str(value).upper())
    return {token for token in tokens if token and token != "NONE"}


def row_matches_registry(row: Mapping[str, Any], tokens: set[str]) -> bool:
    haystack = " ".join(str(row.get(field, "")) for field in ("registration", "callsign", "operator", "aircraft_type")).upper()
    return any(token in haystack for token in tokens)


def audit_rows(rows: Sequence[Mapping[str, Any]], registry: Any = KNOWN_OPERATORS) -> Dict[str, Any]:
    tokens = registry_tokens(registry)
    total = len(rows)
    matched = [row for row in rows if row_matches_registry(row, tokens)]
    coverage = len(matched) / total if total else 0.0
    sighting_keys = Counter(str(row.get("registration") or row.get("callsign") or "UNKNOWN").upper() for row in rows)
    candidates = [
        {"key": key, "sightings": count, "onboarding_threshold": ONBOARDING_THRESHOLD}
        for key, count in sighting_keys.items()
        if key != "UNKNOWN" and count >= ONBOARDING_THRESHOLD["minimum_sightings"] and key not in tokens
    ]
    known_gap_hits = [row for row in rows if any(keyword in " ".join(str(v).upper() for v in row.values()) for keyword in KNOWN_GAP_KEYWORDS)]
    return {
        "record_count": total,
        "registry_token_count": len(tokens),
        "matched_known_operator_count": len(matched),
        "registry_coverage": coverage,
        "onboarding_candidates": candidates,
        "known_gap_hit_count": len(known_gap_hits),
    }


def calibrate(fr24_csv: str) -> Dict[str, Any]:
    rows = load_csv(fr24_csv)
    metrics = audit_rows(rows)
    findings = []
    if not rows:
        findings.append({"severity": "warning", "detail": "no FR24 export rows found"})
    if metrics["registry_coverage"] < 0.50 and rows:
        findings.append({"severity": "warning", "detail": "registry coverage below 50%"})
    if metrics["known_gap_hit_count"]:
        findings.append({"severity": "warning", "detail": "FR24 export contains keywords for known registry gaps"})
    status = "READY"
    if not rows:
        status = "MISSING"
    elif findings:
        status = "PARTIAL"
    return LayerCalibrationResult(
        layer="L4_aircraft_intelligence",
        status=status,
        metrics=metrics,
        thresholds={"registry_coverage_min": 0.50, **ONBOARDING_THRESHOLD},
        findings=findings,
    ).to_dict()


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit SATIM L4 aircraft-intelligence registry coverage")
    parser.add_argument("--fr24-csv", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    write_json(args.output, calibrate(args.fr24_csv))


if __name__ == "__main__":
    main()
