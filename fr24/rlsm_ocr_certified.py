"""Certified orchestration for the fail-closed RLSM OCR worker.

This module keeps the extraction implementation in :mod:`fr24.rlsm_ocr_strict`
but closes the multiprocessing lifecycle and run-ledger edge cases. A worker
exception, failed frame, budget cutoff, or unprocessed target always leaves an
explicit failed processing run; the pool is never joined while it is still
accepting work.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing
import sqlite3
import time
from pathlib import Path
from typing import Any

from fr24 import rlsm_ocr_strict as worker

DB = worker.DB
REPO = Path(__file__).resolve().parents[1]


def _init_worker(repo_root: str) -> None:
    """Pin the repository root inside spawn-based multiprocessing workers."""
    worker.REPO = Path(repo_root).resolve()


def _finish_run(
    conn: sqlite3.Connection,
    *,
    run_id: int,
    targets: int,
    processed: int,
    counts: dict[str, int],
    stopped_for_budget: bool,
    unexpected_error: str | None,
) -> dict[str, Any]:
    unprocessed = targets - processed
    run_status = (
        "completed"
        if unprocessed == 0 and unexpected_error is None and counts["failed"] == 0
        else "failed"
    )
    notes = {
        "contract": "fail_closed_v3",
        "ok": counts["ok"],
        "partial": counts["partial"],
        "failed": counts["failed"],
        "unprocessed": unprocessed,
        "budget_exhausted": stopped_for_budget,
        "unexpected_error": unexpected_error,
    }
    conn.execute(
        """UPDATE processing_runs
           SET ended_at=?, status=?, n_inputs=?, n_processed=?, n_failed=?, notes=?
           WHERE run_id=?""",
        (
            worker._iso_now(),
            run_status,
            targets,
            processed,
            counts["failed"] + unprocessed,
            json.dumps(notes, sort_keys=True),
            run_id,
        ),
    )
    conn.commit()
    return {
        "run_id": run_id,
        "targets": targets,
        "processed": processed,
        **counts,
        "unprocessed": unprocessed,
        "status": run_status,
        "unexpected_error": unexpected_error,
    }


def run(
    *,
    db_path: Path = DB,
    repo_root: Path = REPO,
    workers: int = 4,
    budget_sec: float = 86400.0,
    limit: int = 0,
    filter_month: str | None = None,
    retry_failed: bool = False,
    reocr_boxes: bool = False,
) -> dict[str, Any]:
    db_path = db_path.resolve()
    repo_root = repo_root.resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"RLSM DB not found: {db_path}")

    worker.REPO = repo_root
    conn = worker._connect(db_path)
    targets = worker._select_targets(
        conn,
        retry_failed=retry_failed,
        reocr_boxes=reocr_boxes,
        filter_month=filter_month,
        limit=limit,
    )
    if not targets:
        conn.close()
        return {
            "run_id": None,
            "targets": 0,
            "processed": 0,
            "ok": 0,
            "partial": 0,
            "failed": 0,
            "unprocessed": 0,
            "status": "completed",
            "unexpected_error": None,
            "database": str(db_path),
            "repo_root": str(repo_root),
            "elapsed_sec": 0.0,
        }

    run_id = worker._start_run(conn, len(targets))
    started = time.monotonic()
    counts = {"ok": 0, "partial": 0, "failed": 0}
    processed = 0
    stopped_for_budget = False
    unexpected_error: str | None = None
    pool = multiprocessing.Pool(
        processes=max(1, workers),
        initializer=_init_worker,
        initargs=(str(repo_root),),
    )
    terminated = False

    try:
        for result in pool.imap_unordered(worker._process_one, targets, chunksize=1):
            worker._write_result(conn, result, run_id)
            processed += 1
            counts[result["status"]] += 1
            if processed % 50 == 0:
                print(
                    "[certified-ocr] "
                    f"{processed}/{len(targets)} ok={counts['ok']} "
                    f"partial={counts['partial']} failed={counts['failed']}",
                    flush=True,
                )
            if time.monotonic() - started > budget_sec and processed < len(targets):
                stopped_for_budget = True
                terminated = True
                pool.terminate()
                break
        if not terminated:
            pool.close()
    except Exception as exc:
        unexpected_error = f"{type(exc).__name__}: {exc}"[:500]
        terminated = True
        pool.terminate()
    finally:
        pool.join()

    result = _finish_run(
        conn,
        run_id=run_id,
        targets=len(targets),
        processed=processed,
        counts=counts,
        stopped_for_budget=stopped_for_budget,
        unexpected_error=unexpected_error,
    )
    conn.close()
    result["database"] = str(db_path)
    result["repo_root"] = str(repo_root)
    result["elapsed_sec"] = round(time.monotonic() - started, 2)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--budget-sec", type=float, default=86400.0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--filter-month", default=None)
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--reocr-boxes", action="store_true")
    parser.add_argument("--db", type=Path, default=DB)
    parser.add_argument("--repo-root", type=Path, default=REPO)
    args = parser.parse_args(argv)

    try:
        result = run(
            db_path=args.db,
            repo_root=args.repo_root,
            workers=args.workers,
            budget_sec=args.budget_sec,
            limit=args.limit,
            filter_month=args.filter_month,
            retry_failed=args.retry_failed,
            reocr_boxes=args.reocr_boxes,
        )
    except (FileNotFoundError, sqlite3.DatabaseError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
