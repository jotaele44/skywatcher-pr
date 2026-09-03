#!/usr/bin/env python3
"""Ingest provider-neutral aviation_vision_extraction.v1 JSON into RLSM."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from skywatcher.ai_imagery.vision_result_ingest import ingest_extractions


def _read_records(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text.startswith("["):
        value = json.loads(text)
        if not isinstance(value, list):
            raise ValueError("JSON input must be an array or JSONL")
        return value
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline provider-neutral vision-result ingestion into RLSM."
    )
    parser.add_argument("--input", required=True, help="JSON array or JSONL extraction records")
    parser.add_argument("--rlsm-db", required=True, help="RLSM SQLite database")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--observed-at", default=None)
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    db_path = Path(args.rlsm_db)
    if not input_path.exists() or not db_path.exists():
        print(json.dumps({"error": "input_or_database_missing"}))
        return 1
    observed_at = args.observed_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        records = _read_records(input_path)
        conn = sqlite3.connect(str(db_path))
        try:
            stats = ingest_extractions(
                conn, records, observed_at=observed_at, dry_run=bool(args.dry_run)
            )
        finally:
            conn.close()
    except (ValueError, json.JSONDecodeError, sqlite3.DatabaseError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(stats, indent=2, sort_keys=True))
    return 0 if stats["failed"] == 0 and stats["unmatched"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
