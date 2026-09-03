"""Run legacy structured extractors against one explicit SQLite database."""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from fr24 import rlsm_extractors as legacy

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _start_run(conn: sqlite3.Connection, run_kind: str) -> int:
    cursor = conn.execute(
        """INSERT INTO processing_runs
           (run_kind, started_at, status, n_inputs, n_processed, n_failed, notes)
           VALUES (?, ?, 'in_progress', 0, 0, 0, ?)""",
        (run_kind, _iso_now(), json.dumps({"contract": "explicit_db_v1"})),
    )
    conn.commit()
    return int(cursor.lastrowid)


def _finish_run(
    conn: sqlite3.Connection,
    *,
    run_id: int,
    status: str,
    inputs: int,
    processed: int,
    failed: int,
    notes: dict[str, Any],
) -> None:
    conn.execute(
        """UPDATE processing_runs SET ended_at=?, status=?, n_inputs=?,
                  n_processed=?, n_failed=?, notes=? WHERE run_id=?""",
        (
            _iso_now(),
            status,
            inputs,
            processed,
            failed,
            json.dumps(notes, sort_keys=True),
            run_id,
        ),
    )
    conn.commit()


def run(
    *,
    kind: str,
    db_path: Path = DB,
    repo_root: Path = REPO,
    limit: int = 0,
) -> dict[str, Any]:
    db_path = db_path.resolve()
    repo_root = repo_root.resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"RLSM DB not found: {db_path}")

    legacy.DB = db_path
    legacy.REPO = repo_root
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 60000")
    conn.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS ix_air_dedup
           ON aircraft_observations(screenshot_id, registration, source_zone)
           WHERE registration IS NOT NULL AND TRIM(registration) != ''"""
    )
    conn.commit()

    if kind == "aircraft":
        table = "aircraft_observations"
        run_kind = "aircraft_extract_certified"
    elif kind == "labeled_poi":
        table = "labeled_pins"
        run_kind = "labeled_poi_certified"
    elif kind == "review_queue":
        table = "manual_review_queue"
        run_kind = "review_queue_certified"
    else:
        conn.close()
        raise ValueError(f"unsupported extractor kind: {kind}")

    before = _count(conn, table)
    run_id = _start_run(conn, run_kind)
    try:
        if kind == "aircraft":
            result = legacy.extract_aircraft(conn, run_id, limit)
            expected_delta = int(result.get("emitted", 0))
        elif kind == "labeled_poi":
            result = legacy.extract_labeled_pins(conn, run_id, limit, reset=False)
            expected_delta = int(result.get("emitted", 0))
        else:
            result = legacy.build_review_queues(conn)
            expected_delta = None
    except Exception as exc:
        _finish_run(
            conn,
            run_id=run_id,
            status="failed",
            inputs=0,
            processed=0,
            failed=1,
            notes={"error": f"{type(exc).__name__}: {exc}"[:500]},
        )
        conn.close()
        raise

    after = _count(conn, table)
    persisted_delta = after - before
    mismatched = expected_delta is not None and persisted_delta != expected_delta
    reported_failures = int(result.get("failed", 0))
    status = "failed" if mismatched or reported_failures else "completed"
    notes = {
        "database": str(db_path),
        "repo_root": str(repo_root),
        "table": table,
        "before": before,
        "after": after,
        "persisted_delta": persisted_delta,
        "expected_delta": expected_delta,
        "result": result,
        "counter_mismatch": mismatched,
    }
    _finish_run(
        conn,
        run_id=run_id,
        status=status,
        inputs=int(result.get("targets", 0)),
        processed=max(0, persisted_delta) if expected_delta is not None else int(result.get("inserted", 0)),
        failed=reported_failures + int(mismatched),
        notes=notes,
    )
    conn.close()
    return {**notes, "run_id": run_id, "status": status}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=("aircraft", "labeled_poi", "review_queue"), required=True)
    parser.add_argument("--db", type=Path, default=DB)
    parser.add_argument("--repo-root", type=Path, default=REPO)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)
    try:
        result = run(
            kind=args.kind,
            db_path=args.db,
            repo_root=args.repo_root,
            limit=max(0, args.limit),
        )
    except (FileNotFoundError, sqlite3.DatabaseError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
