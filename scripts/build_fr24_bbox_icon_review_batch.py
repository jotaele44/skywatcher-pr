#!/usr/bin/env python3
"""Build reviewed FR24 bbox/icon source-drop observations from media evidence.

The input review CSV is intentionally explicit: each row must name a frozen
media filename/SHA, the georeferenced capture bbox, and the visible aircraft
icon pixel. This script validates those bindings and emits the observation CSV
consumed by scripts/load_fr24_source_drop.py plus an arithmetic closure summary.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MEDIA_INDEX = Path("/Users/jotaele/Documents/FR24/FR24_DataBank/Media_Canonical/freeze_final/final_active_media_index.csv")
MEDIA_ROOT = Path("/Users/jotaele/Documents")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def media_maps(media_rows: list[dict[str, str]]) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    by_filename: dict[str, dict[str, str]] = {}
    by_sha: dict[str, dict[str, str]] = {}
    for row in media_rows:
        filename = Path(row.get("path", "")).name.lower()
        sha = row.get("sha256", "").lower()
        if filename:
            by_filename.setdefault(filename, row)
        if sha:
            by_sha.setdefault(sha, row)
    return by_filename, by_sha


def require(row: dict[str, str], field: str) -> str:
    value = (row.get(field) or "").strip()
    if not value:
        raise ValueError(f"missing required field {field}")
    return value


def build_batch(
    *,
    review_in: Path,
    media_index: Path,
    observations_out: Path,
    summary_out: Path,
    source_ref: str,
) -> dict[str, Any]:
    review_rows = read_csv(review_in)
    media_rows = read_csv(media_index)
    by_filename, by_sha = media_maps(media_rows)

    observations: list[dict[str, str]] = []
    validation_rows: list[dict[str, Any]] = []
    accepted = 0
    unresolved = 0
    rejected = 0

    for index, row in enumerate(review_rows, start=1):
        status = (row.get("review_status") or "").strip().upper()
        visibility = (row.get("aircraft_icon_visibility") or "").strip().lower()
        filename = Path(require(row, "filename")).name
        expected_sha = require(row, "sha256").lower()
        media = by_filename.get(filename.lower()) or by_sha.get(expected_sha)
        source_path = Path(row.get("absolute_source_path") or "")
        if not source_path.is_absolute() and media:
            source_path = MEDIA_ROOT / media["path"]

        problems: list[str] = []
        if status != "COMPLETED":
            problems.append("review_status is not COMPLETED")
        if visibility != "visible":
            problems.append("aircraft icon is not visible")
        if not media:
            problems.append("media row not found in frozen index")
        elif media.get("sha256", "").lower() != expected_sha:
            problems.append("review SHA does not match frozen media index")
        if not source_path.exists():
            problems.append("absolute source path does not exist")
        else:
            actual_sha = sha256_file(source_path)
            if actual_sha != expected_sha:
                problems.append("source file SHA does not match review SHA")

        if problems:
            unresolved += 1 if status != "REJECTED" else 0
            rejected += 1 if status == "REJECTED" else 0
            validation_rows.append({
                "row": index,
                "filename": filename,
                "status": "REJECTED" if status == "REJECTED" else "UNRESOLVED",
                "problems": problems,
            })
            continue

        accepted += 1
        validation_rows.append({
            "row": index,
            "filename": filename,
            "status": "ACCEPTED",
            "problems": [],
        })
        observations.append({
            "aircraft_obs_id": row.get("aircraft_obs_id") or f"{source_ref}_{index:04d}",
            "screenshot_id": row.get("screenshot_id") or f"{source_ref}_{index:04d}",
            "filename": filename,
            "filename_ts": row.get("observed_at") or row.get("filename_ts") or "",
            "registration": row.get("registration") or "",
            "callsign": row.get("callsign") or "",
            "aircraft_type": row.get("aircraft_type") or "",
            "altitude_ft": row.get("altitude_ft") or "",
            "speed_kt": row.get("speed_kt") or "",
            "heading_deg": row.get("heading_deg") or "",
            "operator_text": row.get("operator_text") or "",
            "identity_status": row.get("identity_status") or "review_bound",
            "confidence": row.get("confidence") or "0.65",
            "source_zone": row.get("source_zone") or "fr24_bbox_icon_review",
            "raw_excerpt": row.get("raw_excerpt") or "",
            "observed_at": row.get("observed_at") or row.get("filename_ts") or "",
        })

    observations_out.parent.mkdir(parents=True, exist_ok=True)
    obs_fields = [
        "aircraft_obs_id", "screenshot_id", "filename", "filename_ts",
        "registration", "callsign", "aircraft_type", "altitude_ft", "speed_kt",
        "heading_deg", "operator_text", "identity_status", "confidence",
        "source_zone", "raw_excerpt", "observed_at",
    ]
    with observations_out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=obs_fields)
        writer.writeheader()
        writer.writerows(observations)

    summary = {
        "source_ref": source_ref,
        "created_at": utc_now(),
        "review_in": str(review_in),
        "media_index": str(media_index),
        "observations_out": str(observations_out),
        "review_rows": len(review_rows),
        "accepted_rows": accepted,
        "unresolved_rows": unresolved,
        "rejected_rows": rejected,
        "arithmetic": f"{len(review_rows)}={accepted}+{unresolved}+{rejected}",
        "validation_rows": validation_rows,
        "geometry_semantics": (
            "Accepted rows are visible-icon screenshot-derived approximate points; "
            "they are not exact aircraft coordinates."
        ),
    }
    summary_out.parent.mkdir(parents=True, exist_ok=True)
    summary_out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-in", required=True)
    parser.add_argument("--media-index", default=str(DEFAULT_MEDIA_INDEX))
    parser.add_argument("--observations-out", required=True)
    parser.add_argument("--summary-out", required=True)
    parser.add_argument("--source-ref", default="fr24_bbox_icon_review_batch")
    args = parser.parse_args()
    build_batch(
        review_in=Path(args.review_in),
        media_index=Path(args.media_index),
        observations_out=Path(args.observations_out),
        summary_out=Path(args.summary_out),
        source_ref=args.source_ref,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
