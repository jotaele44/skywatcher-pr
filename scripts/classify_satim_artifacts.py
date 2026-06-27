#!/usr/bin/env python3
"""Classify SATIM observations against artifact controls.

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


def classify(description: str) -> tuple[str, str]:
    text = description.lower()
    if "fr24" in text or "route" in text or "playback" in text or "diagonal line" in text or "track" in text:
        return "TRACK_LINE", "high"
    if "logo" in text or "player" in text or "label" in text or "overlay" in text:
        return "UI_OVERLAY", "high"
    if "zoom" in text or "blur" in text or "smear" in text:
        return "ZOOM_BLUR", "high"
    if "shadow" in text or "canopy" in text or "forest" in text:
        return "SHADOW_CONFUSION", "medium"
    if "tile" in text or "epoch" in text or "mosaic" in text or "seam" in text:
        return "TILE_SEAM", "medium"
    if "compression" in text or "jpeg" in text or "artifact" in text:
        return "COMPRESSION", "medium"
    return "HOLD_REVIEW", "low"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_csv", help="CSV with artifact_id,event_id,page,description columns")
    parser.add_argument("--out", default="classified_tile_artifacts.csv")
    args = parser.parse_args()

    with Path(args.input_csv).open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    for row in rows:
        artifact_class, risk = classify(row.get("description", ""))
        if not row.get("artifact_class") or row.get("artifact_class") == "STRUCTURAL_SIGNAL":
            row["artifact_class"] = artifact_class
        if not row.get("artifact_risk"):
            row["artifact_risk"] = risk
        row.setdefault("impact_on_analysis", "Requires analyst review before promotion.")
        row.setdefault("promotion_status", "hold_artifact_control")
        row.setdefault("promotion_rule", "No STRUCTURAL_SIGNAL promotion without georeference and independent corroboration.")

    fieldnames = sorted({key for row in rows for key in row.keys()})
    with Path(args.out).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
