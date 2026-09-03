"""Reconcile the screenshot ledger against the operator-local corpus without deleting history."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
CORPUS = REPO / "data" / "FR24_baseline"
OUTPUT = REPO / "outputs" / "rlsm_source_reconciliation.json"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".heic", ".webp"}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS source_reconciliation_receipts (
    receipt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER REFERENCES processing_runs(run_id),
    corpus_root TEXT NOT NULL,
    manifest_sha256 TEXT NOT NULL,
    disk_images INTEGER NOT NULL,
    database_rows INTEGER NOT NULL,
    active_rows INTEGER NOT NULL,
    newly_missing_rows INTEGER NOT NULL,
    already_missing_rows INTEGER NOT NULL,
    restored_rows INTEGER NOT NULL,
    stale_runs_closed INTEGER NOT NULL,
    missing_sample_json TEXT NOT NULL,
    observed_at TEXT NOT NULL
);
"""


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _manifest(repo_root: Path, corpus_root: Path) -> dict[str, Path]:
    manifest: dict[str, Path] = {}
    for path in sorted(corpus_root.rglob("*")):
        if not path.is_file() or path.suffix.casefold() not in IMAGE_EXTENSIONS:
            continue
        try:
            rel = path.relative_to(repo_root).as_posix()
        except ValueError:
            rel = (Path("data/FR24_baseline") / path.relative_to(corpus_root)).as_posix()
        manifest[rel] = path
    return manifest


def _close_stale_runs(conn: sqlite3.Connection, current_run_id: int) -> int:
    rows = conn.execute(
        "SELECT run_id, run_kind, notes FROM processing_runs "
        "WHERE status='in_progress' AND run_id<>? ORDER BY run_id",
        (current_run_id,),
    ).fetchall()
    observed_at = _iso_now()
    for run_id, run_kind, prior_notes in rows:
        notes = json.dumps(
            {
                "reconciled_from_status": "in_progress",
                "reason": "stale_before_operator_certification",
                "run_kind": run_kind,
                "previous_notes": prior_notes,
            },
            sort_keys=True,
        )
        conn.execute(
            "UPDATE processing_runs SET status='failed', ended_at=?, "
            "n_failed=CASE WHEN COALESCE(n_failed,0)>0 THEN n_failed ELSE 1 END, "
            "notes=? WHERE run_id=?",
            (observed_at, notes, run_id),
        )
    return len(rows)


def reconcile(
    *,
    db_path: Path = DB,
    repo_root: Path = REPO,
    corpus_root: Path = CORPUS,
    output_path: Path = OUTPUT,
) -> dict[str, Any]:
    db_path = db_path.resolve()
    repo_root = repo_root.resolve()
    corpus_root = corpus_root.absolute()
    if not db_path.exists():
        raise FileNotFoundError(f"RLSM DB not found: {db_path}")
    if not corpus_root.exists():
        raise FileNotFoundError(f"RLSM corpus not found: {corpus_root}")

    disk = _manifest(repo_root, corpus_root)
    manifest_sha256 = hashlib.sha256(
        "\n".join(sorted(disk)).encode("utf-8")
    ).hexdigest()

    conn = sqlite3.connect(str(db_path), timeout=60.0)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 60000")
    conn.executescript(SCHEMA_SQL)
    cursor = conn.execute(
        """INSERT INTO processing_runs
           (run_kind, started_at, status, n_inputs, n_processed, n_failed, notes)
           VALUES ('source_reconciliation', ?, 'in_progress', 0, 0, 0, ?)""",
        (_iso_now(), json.dumps({"manifest_sha256": manifest_sha256}, sort_keys=True)),
    )
    run_id = int(cursor.lastrowid)
    conn.commit()

    stale_runs_closed = _close_stale_runs(conn, run_id)
    rows = conn.execute(
        "SELECT screenshot_id, rel_path, ingest_status FROM screenshots ORDER BY screenshot_id"
    ).fetchall()
    disk_paths = set(disk)
    newly_missing = 0
    already_missing = 0
    restored = 0
    missing_sample: list[dict[str, Any]] = []

    for screenshot_id, rel_path_raw, ingest_status_raw in rows:
        rel_path = str(rel_path_raw)
        ingest_status = str(ingest_status_raw or "")
        present = rel_path in disk_paths
        if present and ingest_status == "missing_source":
            conn.execute(
                "UPDATE screenshots SET ingest_status='ok', ingest_error=NULL "
                "WHERE screenshot_id=?",
                (screenshot_id,),
            )
            restored += 1
        elif not present:
            if ingest_status == "ok":
                conn.execute(
                    "UPDATE screenshots SET ingest_status='missing_source', "
                    "ingest_error='source image absent during source reconciliation' "
                    "WHERE screenshot_id=?",
                    (screenshot_id,),
                )
                newly_missing += 1
            else:
                already_missing += 1
            if len(missing_sample) < 50:
                missing_sample.append(
                    {
                        "screenshot_id": int(screenshot_id),
                        "rel_path": rel_path,
                        "previous_ingest_status": ingest_status,
                    }
                )

    active_rows = int(
        conn.execute("SELECT COUNT(*) FROM screenshots WHERE ingest_status='ok'").fetchone()[0]
    )
    explicit_missing_rows = int(
        conn.execute(
            "SELECT COUNT(*) FROM screenshots WHERE ingest_status='missing_source'"
        ).fetchone()[0]
    )
    observed_at = _iso_now()
    result: dict[str, Any] = {
        "run_id": run_id,
        "database": str(db_path),
        "repo_root": str(repo_root),
        "corpus_root": str(corpus_root),
        "manifest_sha256": manifest_sha256,
        "disk_images": len(disk),
        "database_rows": len(rows),
        "active_rows": active_rows,
        "newly_missing_rows": newly_missing,
        "already_missing_rows": already_missing,
        "explicit_missing_rows": explicit_missing_rows,
        "restored_rows": restored,
        "stale_runs_closed": stale_runs_closed,
        "missing_sample": missing_sample,
        "status": "completed",
    }
    conn.execute(
        """INSERT INTO source_reconciliation_receipts
           (run_id, corpus_root, manifest_sha256, disk_images, database_rows,
            active_rows, newly_missing_rows, already_missing_rows, restored_rows,
            stale_runs_closed, missing_sample_json, observed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            run_id,
            str(corpus_root),
            manifest_sha256,
            len(disk),
            len(rows),
            active_rows,
            newly_missing,
            already_missing,
            restored,
            stale_runs_closed,
            json.dumps(missing_sample, sort_keys=True),
            observed_at,
        ),
    )
    conn.execute(
        """UPDATE processing_runs SET ended_at=?, status='completed', n_inputs=?,
                  n_processed=?, n_failed=?, notes=? WHERE run_id=?""",
        (
            observed_at,
            len(rows),
            active_rows,
            explicit_missing_rows,
            json.dumps(result, sort_keys=True),
            run_id,
        ),
    )
    conn.commit()
    conn.close()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DB)
    parser.add_argument("--repo-root", type=Path, default=REPO)
    parser.add_argument("--corpus-root", type=Path, default=CORPUS)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    try:
        result = reconcile(
            db_path=args.db,
            repo_root=args.repo_root,
            corpus_root=args.corpus_root,
            output_path=args.output,
        )
    except (FileNotFoundError, sqlite3.DatabaseError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
