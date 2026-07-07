"""Guardrail checks for GATIM source text and generated labels."""
from __future__ import annotations

from pathlib import Path

FORBIDDEN_PHRASES = [
    "confirmed anomaly",
    "verified anomaly",
    "proof of anomaly",
    "confirmed site meaning",
    "target private residence",
    "raw uploaded csv",
]

ALLOWED_STATUS_TERMS = {"coordinate_overlap", "nearby_FN", "P0_REVIEW", "P1_REVIEW", "P2_REVIEW", "P2_CONTEXT", "P3_GEOCODE"}


def scan_text(text: str) -> list[str]:
    lowered = text.lower()
    return [phrase for phrase in FORBIDDEN_PHRASES if phrase in lowered]


def scan_paths(paths: list[str | Path]) -> dict[str, list[str]]:
    findings: dict[str, list[str]] = {}
    for path in paths:
        text = Path(path).read_text(encoding="utf-8")
        hits = scan_text(text)
        if hits:
            findings[str(path)] = hits
    return findings


def validate_output_labels(rows: list) -> list[str]:
    findings = []
    for row in rows:
        fields = [row.class_primary, row.review_priority, row.satim_link_status]
        for field in fields:
            if field and scan_text(str(field)):
                findings.append(f"{row.gatim_id}:{field}")
    return findings
