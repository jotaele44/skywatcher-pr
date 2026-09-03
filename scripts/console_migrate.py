#!/usr/bin/env python3
"""Apply or roll back Skywatcher console SQLite migrations."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.backend.console.migrations import LATEST_VERSION, migrate, rollback


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("db", type=Path, help="SQLite database path")
    parser.add_argument("--target", type=int, default=LATEST_VERSION)
    parser.add_argument("--rollback", action="store_true")
    parser.add_argument("--allow-data-loss", action="store_true")
    args = parser.parse_args()

    args.db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(args.db)
    try:
        if args.rollback:
            ledger = rollback(
                conn,
                target_version=args.target,
                allow_data_loss=args.allow_data_loss,
            )
        else:
            ledger = migrate(conn, target_version=args.target)
    finally:
        conn.close()
    print(json.dumps({"db": str(args.db), "target": args.target, "ledger": ledger}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
