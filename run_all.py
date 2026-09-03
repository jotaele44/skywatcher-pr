#!/usr/bin/env python3
"""SKYWATCHER FR24 PIPELINE ENTRYPOINT

Unified CLI for the FR24 screenshot-processing pipeline that skywatcher-pr owns.

    python run_all.py --init-db [--db PATH]
    python run_all.py --validate [--db PATH]
    python run_all.py --status   [--db PATH]
    python run_all.py --image-dir PATH [--images N] [--db PATH]   # ingest (runtime)
    python run_all.py --export-spiderweb DIR [--db PATH]          # bridge export

Configuration precedence:
    DB path       : --db PATH  >  $SKYWATCHER_DB  >  ./data/skywatcher.db
    screenshot dir: --image-dir PATH  >  $SKYWATCHER_IMAGE_DIR  >  ./inputs/screenshots

This entrypoint contains the wiring for future runtime execution. Consistent with
the repository-boundary task, screenshot processing is NOT executed here as part
of code delivery; the ingest path resolves and validates its inputs and reports
an actionable error when the screenshot directory is unavailable.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent
for _p in (_REPO_ROOT, _REPO_ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from skywatcher.fr24 import cli_support  # noqa: E402
from skywatcher.fr24 import database as db  # noqa: E402
from skywatcher.fr24 import database_migrations as migrations  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="run_all.py", description="Skywatcher FR24 pipeline.")
    p.add_argument("--db", default=None, help="DB path (default: $SKYWATCHER_DB or ./data/skywatcher.db)")
    p.add_argument("--init-db", action="store_true", help="Create/upgrade the database schema.")
    p.add_argument("--validate", action="store_true", help="Validate the database schema (no writes).")
    p.add_argument("--status", action="store_true", help="Print a read-only database status summary.")
    p.add_argument("--image-dir", default=None, help="Screenshot input directory (runtime ingest).")
    p.add_argument("--images", type=int, default=None, help="Limit number of screenshots to ingest.")
    p.add_argument("--export-spiderweb", metavar="DIR", default=None,
                   help="Emit the canonical hub package + Spiderweb bridge export to DIR.")
    return p


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    db_path = db.resolve_db_path(args.db)

    did_something = False

    if args.init_db:
        did_something = True
        try:
            result = migrations.initialize_database(db_path)
        except db.DatabaseError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        print(f"[init-db] db={result.db_path} schema_version={result.schema_version} applied={result.applied}")
        if result.problems:
            for pr in result.problems:
                print(f"  - problem: {pr}", file=sys.stderr)
            return 1

    if args.validate:
        did_something = True
        result = migrations.initialize_database(db_path, validate_only=True, create_parent=False)
        print(f"[validate] db={result.db_path} schema_version={result.schema_version} ok={result.ok}")
        if result.problems:
            for pr in result.problems:
                print(f"  - problem: {pr}", file=sys.stderr)
            return 1

    if args.status:
        did_something = True
        status = cli_support.database_status(db_path)
        print(json.dumps(status, indent=2))

    if args.export_spiderweb:
        did_something = True
        from skywatcher.fr24 import spiderweb_export
        out = spiderweb_export.export_package(db_path, args.export_spiderweb)
        print(f"[export-spiderweb] wrote package to {out}")

    if args.image_dir is not None or args.images is not None:
        did_something = True
        try:
            image_dir = cli_support.resolve_image_dir(args.image_dir)
        except cli_support.ImageDirUnavailableError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        # Runtime ingest wiring lives here. Not executed during the boundary
        # transfer task (no screenshot processing); the resolved directory is
        # validated above so operators get an actionable error early.
        print(f"[ingest] resolved image-dir={image_dir} images_limit={args.images} db={db_path}")
        print("[ingest] runtime ingest not executed in this context.")

    if not did_something:
        _build_parser().print_help()
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
