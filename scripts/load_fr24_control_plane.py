#!/usr/bin/env python3
"""Load FR24 control-plane flight_summary/track_points exports into Skywatcher."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from server.backend.console.fr24_control_plane import ingest_fr24_control_plane


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--flight-summary", type=Path, required=True)
    parser.add_argument("--track-points", type=Path, required=True)
    parser.add_argument(
        "--source-ref",
        default="FR24_14DAY_FETCH_V1_1.0.0rc4",
        help="Immutable source/version label bound into provenance.",
    )
    args = parser.parse_args()

    args.db.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(args.db)
    try:
        summary = ingest_fr24_control_plane(
            connection,
            flight_summary=args.flight_summary,
            track_points=args.track_points,
            source_ref=args.source_ref,
        )
    finally:
        connection.close()

    print(json.dumps(summary.to_dict(), indent=2, sort_keys=True))
    return 1 if summary.identity_survival_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
