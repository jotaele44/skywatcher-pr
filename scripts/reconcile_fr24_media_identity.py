#!/usr/bin/env python3
"""Reconcile aircraft observation rows to the frozen FR24 media inventory.

This script distinguishes exact filename identity from candidate-only discovery
signals. Timestamp + registration matches are useful review candidates, but they
are not promoted as source identity because source taxonomy and normalized names
do not prove canonical file identity.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

DEFAULT_MEDIA_INDEX = Path("/Users/jotaele/Documents/FR24/FR24_DataBank/Media_Canonical/freeze_final/final_active_media_index.csv")
DEFAULT_OBSERVATIONS = Path("/Users/jotaele/Documents/Financials/Consolidated/entities/aircraft_observations.csv")
REPO_ROOT = Path(__file__).resolve().parents[1]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def date_bucket(value: str) -> str:
    digits = re.sub(r"[^0-9]", "", (value or "")[:10])
    return digits if len(digits) == 8 else ""


def aircraft_key(row: dict[str, str]) -> str:
    return (row.get("registration") or row.get("callsign") or "").strip().upper()


def media_aircraft_key(row: dict[str, str]) -> str:
    return (row.get("aircraft_or_callsign") or "").strip().upper()


def reconcile(
    *,
    media_index: Path,
    observations: Path,
    csv_out: Path,
    json_out: Path,
) -> dict[str, Any]:
    media_rows = read_csv(media_index)
    obs_rows = read_csv(observations)

    media_by_filename = {
        Path(row.get("path", "")).name.lower(): row
        for row in media_rows
        if Path(row.get("path", "")).name
    }
    obs_by_filename = {
        Path(row.get("filename", "")).name.lower(): row
        for row in obs_rows
        if Path(row.get("filename", "")).name
    }
    media_by_date_aircraft: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in media_rows:
        key = (row.get("date_bucket", ""), media_aircraft_key(row))
        if key[0] and key[1]:
            media_by_date_aircraft[key].append(row)

    exact_names = sorted(set(media_by_filename) & set(obs_by_filename))
    obs_only = sorted(set(obs_by_filename) - set(media_by_filename))
    media_only = sorted(set(media_by_filename) - set(obs_by_filename))

    candidate_rows: list[dict[str, Any]] = []
    exact_rows: list[dict[str, Any]] = []
    for name in exact_names:
        media = media_by_filename[name]
        obs = obs_by_filename[name]
        exact_rows.append({
            "match_status": "FOUND",
            "match_basis": "exact_filename",
            "aircraft_obs_id": obs.get("aircraft_obs_id", ""),
            "observation_filename": obs.get("filename", ""),
            "media_filename": Path(media.get("path", "")).name,
            "media_sha256": media.get("sha256", ""),
            "candidate_count": 1,
        })

    for obs in obs_rows:
        reg = aircraft_key(obs)
        bucket = date_bucket(obs.get("filename_ts") or obs.get("filename", ""))
        candidates = media_by_date_aircraft.get((bucket, reg), []) if bucket and reg else []
        if candidates:
            candidate_rows.append({
                "match_status": "CANDIDATE_NOT_IDENTITY",
                "match_basis": "date_bucket_plus_aircraft_token",
                "aircraft_obs_id": obs.get("aircraft_obs_id", ""),
                "observation_filename": obs.get("filename", ""),
                "observation_date_bucket": bucket,
                "aircraft_token": reg,
                "candidate_count": len(candidates),
                "candidate_media_filenames": "|".join(Path(row.get("path", "")).name for row in candidates[:10]),
                "candidate_media_sha256": "|".join(row.get("sha256", "") for row in candidates[:10]),
            })

    csv_out.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "match_status", "match_basis", "aircraft_obs_id", "observation_filename",
        "observation_date_bucket", "aircraft_token", "media_filename",
        "media_sha256", "candidate_count", "candidate_media_filenames",
        "candidate_media_sha256",
    ]
    with csv_out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in exact_rows + candidate_rows:
            writer.writerow({field: row.get(field, "") for field in fields})

    summary = {
        "media_index": str(media_index),
        "observations": str(observations),
        "media_rows": len(media_rows),
        "aircraft_observation_rows": len(obs_rows),
        "media_filename_unique": len(media_by_filename),
        "observation_filename_unique": len(obs_by_filename),
        "intersection_exact_filename": len(exact_names),
        "observation_only_filenames": len(obs_only),
        "media_only_filenames": len(media_only),
        "union_filenames": len(set(media_by_filename) | set(obs_by_filename)),
        "symmetric_difference_filenames": len(set(media_by_filename) ^ set(obs_by_filename)),
        "candidate_not_identity_rows": len(candidate_rows),
        "candidate_unique_rows": sum(1 for row in candidate_rows if row["candidate_count"] == 1),
        "candidate_ambiguous_rows": sum(1 for row in candidate_rows if row["candidate_count"] > 1),
        "identity_policy": "Exact filename is FOUND; date/aircraft-token matches are discovery candidates only.",
    }
    json_out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--media-index", default=str(DEFAULT_MEDIA_INDEX))
    parser.add_argument("--observations", default=str(DEFAULT_OBSERVATIONS))
    parser.add_argument("--csv-out", default=str(REPO_ROOT / "reports" / "source_drops" / "fr24_media_identity_reconciliation.csv"))
    parser.add_argument("--json-out", default=str(REPO_ROOT / "reports" / "source_drops" / "fr24_media_identity_reconciliation_summary.json"))
    args = parser.parse_args()
    summary = reconcile(
        media_index=Path(args.media_index),
        observations=Path(args.observations),
        csv_out=Path(args.csv_out),
        json_out=Path(args.json_out),
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
