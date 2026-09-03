#!/usr/bin/env python3
"""INITIALIZE THE SKYWATCHER FR24 DATABASE (schema only; no operational data)

Deterministic, idempotent initializer/validator for the Skywatcher FR24 SQLite
database. Applies the versioned schema from schemas/database_schema.sql.

Usage:
    python scripts/init_database.py [--db PATH] [--validate]

DB-path precedence: --db PATH > $SKYWATCHER_DB > ./data/skywatcher.db

This script creates ONLY the schema. It never ingests screenshots, never copies
rows, and never produces a populated operational database.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make the src-layout package importable when run as a standalone script.
_REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (_REPO_ROOT, _REPO_ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from skywatcher.fr24 import database as db  # noqa: E402
from skywatcher.fr24 import database_migrations as migrations  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Initialize/validate the Skywatcher FR24 DB.")
    parser.add_argument("--db", default=None, help="DB path (default: $SKYWATCHER_DB or ./data/skywatcher.db)")
    parser.add_argument("--validate", action="store_true", help="Validate schema only; do not write.")
    args = parser.parse_args(argv)

    db_path = db.resolve_db_path(args.db)

    try:
        result = migrations.initialize_database(db_path, validate_only=args.validate)
    except db.DatabaseError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    mode = "validate" if args.validate else "init"
    print(f"[{mode}] db={result.db_path} schema_version={result.schema_version}")
    if not args.validate and result.applied:
        print(f"[init] applied migrations: {result.applied}")
    if result.problems:
        for p in result.problems:
            print(f"  - problem: {p}", file=sys.stderr)
        return 1
    print(f"[{mode}] OK ({len(db.EXPECTED_TABLES)} expected tables present)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
