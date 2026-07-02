#!/usr/bin/env python3
"""Canonical SATIM artifact classifier CLI.

Conservative rule: unknowns are held for review. The classifier must never
promote a weak or unknown row directly to STRUCTURAL_SIGNAL.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

ARTIFACT_CLASSES = {
    "TRACK_LINE",
    "TILE_SEAM",
    "UI_OVERLAY",
    "ZOOM_BLUR",
    "COMPRESSION",
    "MIXED_EPOCH",
    "SHADOW_CONFUSION",
    "LABEL_COLLISION",
    "HOLD_REVIEW",
}


def classify_text(text: str) -> tuple[str, str]:
    value = text.lower()
    if any(term in value for term in ["fr24", "route", "playback", "diagonal line", "track"]):
        return "TRACK_LINE", "high"
    if any(term in value for term in ["logo", "player", "label", "overlay"]):
        return "UI_OVERLAY", "high"
    if any(term in value for term in ["zoom", "blur", "smear"]):
        return "ZOOM_BLUR", "high"
    if any(term in value for term in ["shadow", "canopy", "forest"]):
        return "SHADOW_CONFUSION", "medium"
    if any(term in value for term in ["tile", "epoch", "mosaic", "seam"]):
        return "TILE_SEAM", "medium"
    if any(term in value for term in ["compression", "jpeg", "artifact"]):
        return "COMPRESSION", "medium"
    return "HOLD_REVIEW", "low"


def classify_row(row: dict[str, str]) -> dict[str, str]:
    joined = " ".join(str(value) for value in row.values())
    artifact_class, risk = classify_text(joined)

    if not row.get("artifact_class") or row.get("artifact_class") == "STRUCTURAL_SIGNAL":
        row["artifact_class"] = artifact_class
    if not row.get("artifact_risk"):
        row["artifact_risk"] = risk
    row.setdefault("impact_on_analysis", "Requires analyst review before promotion.")
    row.setdefault("promotion_status", "hold_artifact_control")
    row.setdefault("promotion_rule", "No STRUCTURAL_SIGNAL promotion without georeference and independent corroboration.")
    return row


def classify_csv(input_csv: Path, output_csv: Path) -> None:
    with input_csv.open(newline="", encoding="utf-8") as f:
        rows = [classify_row(dict(row)) for row in csv.DictReader(f)]

    fieldnames = sorted({key for row in rows for key in row.keys()})
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Classify SATIM artifact rows conservatively")
    parser.add_argument("input_csv", help="CSV containing artifact/visual observation rows")
    parser.add_argument("--out", default="classified_tile_artifacts.csv")
    args = parser.parse_args()

    classify_csv(Path(args.input_csv), Path(args.out))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
