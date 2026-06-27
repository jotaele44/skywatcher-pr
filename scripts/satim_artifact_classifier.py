#!/usr/bin/env python3
"""Classify SATIM visual observations against artifact controls.

Conservative test stub: separates flight-app route geometry from basemap tile
artifacts and holds uncorroborated runtime-media observations before promotion.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def classify_row(row: dict) -> dict:
    text = " ".join(str(v).lower() for v in row.values())
    classes: list[str] = []

    if any(term in text for term in ["fr24", "track", "playback", "diagonal", "route"]):
        classes.append("TRACK_LINE")
    if any(term in text for term in ["logo", "player", "label", "overlay"]):
        classes.append("UI_OVERLAY")
    if any(term in text for term in ["zoom", "blur", "smear"]):
        classes.append("ZOOM_BLUR")
    if any(term in text for term in ["shadow", "canopy", "forest"]):
        classes.append("SHADOW_CONFUSION")
    if any(term in text for term in ["tile", "seam", "epoch", "mosaic"]):
        classes.append("TILE_SEAM")
    if any(term in text for term in ["compression", "jpeg", "artifact"]):
        classes.append("COMPRESSION")

    if not classes:
        classes = ["HOLD_REVIEW"]

    row["classifier_artifact_classes"] = ";".join(dict.fromkeys(classes))
    row["promotion_status"] = "hold_artifact_control"
    row["promotion_rule"] = "No STRUCTURAL_SIGNAL promotion without georeference and independent corroboration."
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_csv")
    parser.add_argument("output_csv")
    args = parser.parse_args()

    input_path = Path(args.input_csv)
    output_path = Path(args.output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with input_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = [classify_row(dict(row)) for row in reader]
        fieldnames = list(reader.fieldnames or []) + [
            "classifier_artifact_classes",
            "promotion_status",
            "promotion_rule",
        ]

    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"wrote {output_path}")


if __name__ == "__main__":
    main()
