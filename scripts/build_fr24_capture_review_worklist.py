#!/usr/bin/env python3
"""Build a reviewer worklist for FR24 screenshot capture geometry.

The output CSV is intentionally blank for geometry fields. A reviewer can fill
the screenshot viewport bbox and aircraft-icon pixel only when the aircraft icon
is visible. scripts/load_fr24_source_drop.py can then ingest the completed CSV
without mutating the original evidence folders.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

DEFAULT_MEDIA_INDEX = Path("/Users/jotaele/Documents/FR24/FR24_DataBank/Media_Canonical/freeze_final/final_active_media_index.csv")
DEFAULT_OBSERVATIONS = Path("/Users/jotaele/Documents/Financials/Consolidated/entities/aircraft_observations.csv")
REPO_ROOT = Path(__file__).resolve().parents[1]

FIELDS = [
    "aircraft_obs_id",
    "screenshot_id",
    "filename",
    "sha256",
    "source_path",
    "size_bytes",
    "date_bucket",
    "media_match_status",
    "registration",
    "callsign",
    "filename_ts",
    "review_status",
    "reviewer",
    "reviewed_at",
    "aircraft_icon_visibility",
    "image_width",
    "image_height",
    "capture_bbox_min_lon",
    "capture_bbox_min_lat",
    "capture_bbox_max_lon",
    "capture_bbox_max_lat",
    "capture_geometry_method",
    "capture_geometry_confidence",
    "capture_geometry_uncertainty_m",
    "control_point_count",
    "control_point_residual_px",
    "aircraft_icon_pixel_x",
    "aircraft_icon_pixel_y",
    "aircraft_point_method",
    "aircraft_point_confidence",
    "aircraft_point_uncertainty_m",
    "notes",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _media_by_filename(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for row in rows:
        filename = Path(row.get("path", "")).name.lower()
        if filename:
            out.setdefault(filename, row)
    return out


def build_worklist(
    media_index: Path,
    out: Path,
    *,
    observations: Path | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    media_rows = read_csv(media_index)
    observation_rows = read_csv(observations) if observations and observations.exists() else []
    media_by_name = _media_by_filename(media_rows)
    rows = observation_rows or [
        {"filename": Path(row.get("path", "")).name, "_media_only": "1"}
        for row in media_rows
    ]
    out.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    matched = 0
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            if limit is not None and written >= limit:
                break
            filename = Path(row.get("filename", "")).name
            media = media_by_name.get(filename.lower(), {})
            if media:
                matched += 1
            media_path = media.get("path", "")
            writer.writerow({
                "aircraft_obs_id": row.get("aircraft_obs_id", ""),
                "screenshot_id": row.get("screenshot_id", ""),
                "filename": filename,
                "sha256": media.get("sha256", ""),
                "source_path": media_path,
                "size_bytes": media.get("size", ""),
                "date_bucket": media.get("date_bucket", ""),
                "media_match_status": "FOUND" if media else "UNRESOLVED",
                "registration": row.get("registration", ""),
                "callsign": row.get("callsign", ""),
                "filename_ts": row.get("filename_ts", ""),
                "review_status": "pending",
                "aircraft_icon_visibility": "unreviewed",
                "capture_geometry_method": "reviewer_georeferenced_bbox",
                "aircraft_point_method": "screenshot_icon_georeference",
            })
            written += 1
    return {
        "media_index": str(media_index),
        "observations": str(observations) if observations else None,
        "worklist": str(out),
        "media_rows": len(media_rows),
        "aircraft_observation_rows": len(observation_rows),
        "worklist_rows": written,
        "media_filename_matches": matched,
        "media_filename_unresolved": written - matched,
        "review_rule": (
            "Fill bbox and aircraft icon pixel only when the aircraft icon is "
            "visible; otherwise leave coordinates blank and set visibility to "
            "not_visible, ambiguous, or occluded."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--media-index", default=str(DEFAULT_MEDIA_INDEX))
    parser.add_argument("--observations", default=str(DEFAULT_OBSERVATIONS))
    parser.add_argument(
        "--out",
        default=str(REPO_ROOT / "reports" / "source_drops" / "fr24_capture_review_worklist.csv"),
    )
    parser.add_argument("--summary-out", default=None)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    summary = build_worklist(
        Path(args.media_index),
        Path(args.out),
        observations=Path(args.observations) if args.observations else None,
        limit=args.limit,
    )
    if args.summary_out:
        summary_out = Path(args.summary_out)
        summary_out.parent.mkdir(parents=True, exist_ok=True)
        summary_out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
