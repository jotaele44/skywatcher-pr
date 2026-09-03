#!/usr/bin/env python3
"""
Build/enrich per-craft profiles from the RLSM corpus.

For every registration in the RLSM database, consolidate identity, home base,
preferred landing zones, empirical schedule, recurring routes, and newly-surfaced
patterns into a schema-valid CraftProfile — persisted to the ``craft_profiles``
table and to ``profiles/craft/<reg>.json``. Idempotent and incremental: re-running
recomputes aggregates and diffs against the previous snapshot to surface new
patterns.

The RLSM database is real operator data and is gitignored; this exits cleanly
with a message when it is absent (e.g. in CI).

CLI:
    python3 scripts/build_craft_profiles.py
    python3 scripts/build_craft_profiles.py --db path/to.sqlite --craft N5854Z
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from skywatcher.core.db_utils import configure_connection  # noqa: E402
from skywatcher.fpim.craft_profile import (  # noqa: E402
    DEFAULT_DB,
    DEFAULT_PROFILE_DIR,
    CraftProfileBuilder,
    ensure_tables,
    upsert_profile,
    write_json,
    write_snapshot,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(DEFAULT_DB), help="RLSM SQLite path")
    ap.add_argument("--out", default=str(DEFAULT_PROFILE_DIR), help="JSON output dir")
    ap.add_argument("--craft", default=None, help="Build a single registration only")
    ap.add_argument("--no-json", action="store_true", help="Skip JSON export")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"[build_craft_profiles] RLSM database not found: {db_path}\n"
              f"  This DB is real operator data and is gitignored. Run the RLSM\n"
              f"  ingest pipeline first, or pass --db to an existing database.")
        return 0

    conn = sqlite3.connect(str(db_path))
    configure_connection(conn)
    ensure_tables(conn)

    builder = CraftProfileBuilder(db_path=db_path)
    regs = [args.craft] if args.craft else builder.registrations(conn)
    if not regs:
        print("[build_craft_profiles] no registrations in corpus; nothing to build.")
        conn.close()
        return 0

    baseline = builder._source_baseline(conn)
    built = 0
    out_dir = Path(args.out)
    for reg in regs:
        profile = builder.build_one(conn, reg, baseline)
        upsert_profile(conn, profile)
        if not args.no_json:
            write_json(profile, out_dir)
        write_snapshot(conn, profile)  # snapshot AFTER diff, for the next run
        built += 1
    conn.commit()
    conn.close()

    print(json.dumps({
        "db": str(db_path),
        "registrations_built": built,
        "source_baseline": baseline,
        "json_dir": None if args.no_json else str(out_dir),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
