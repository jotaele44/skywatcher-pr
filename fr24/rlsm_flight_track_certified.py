"""Certified pixel-first flight-track extraction for the RLSM corpus."""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from fr24.rlsm_flight_track import HEURISTIC_CONFIDENCE, _classify_screenshot
from fr24.track_vectorizer_strict import vectorize_image_receipt

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
METHOD = "pixel_first_track_v2"

RECEIPT_SCHEMA = """
CREATE TABLE IF NOT EXISTS track_extraction_receipts (
    receipt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    screenshot_id INTEGER NOT NULL REFERENCES screenshots(screenshot_id),
    run_id INTEGER REFERENCES processing_runs(run_id),
    method TEXT NOT NULL,
    source_path TEXT,
    cv_status TEXT NOT NULL,
    cv_error TEXT,
    candidate_count INTEGER NOT NULL DEFAULT 0,
    extractor_mode TEXT NOT NULL,
    heuristic_fallback INTEGER NOT NULL DEFAULT 0,
    observed_at TEXT NOT NULL,
    UNIQUE(screenshot_id, method)
);
CREATE INDEX IF NOT EXISTS ix_track_receipt_status
    ON track_extraction_receipts(cv_status);
"""


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(RECEIPT_SCHEMA)
    conn.commit()


def _resolve_image(rel_path: str, image_root: Path | None) -> Path | None:
    candidates = [REPO / rel_path]
    if image_root is not None:
        candidates.extend((image_root / rel_path, image_root / Path(rel_path).name))
        prefix = "data/FR24_baseline/"
        if rel_path.startswith(prefix):
            candidates.append(image_root / rel_path[len(prefix):])
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _write_receipt(
    conn: sqlite3.Connection,
    *,
    sid: int,
    run_id: int,
    source_path: str | None,
    cv_status: str,
    cv_error: str | None,
    candidate_count: int,
    extractor_mode: str,
    heuristic_fallback: bool,
) -> None:
    conn.execute(
        """INSERT INTO track_extraction_receipts
           (screenshot_id, run_id, method, source_path, cv_status, cv_error,
            candidate_count, extractor_mode, heuristic_fallback, observed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(screenshot_id, method) DO UPDATE SET
               run_id=excluded.run_id,
               source_path=excluded.source_path,
               cv_status=excluded.cv_status,
               cv_error=excluded.cv_error,
               candidate_count=excluded.candidate_count,
               extractor_mode=excluded.extractor_mode,
               heuristic_fallback=excluded.heuristic_fallback,
               observed_at=excluded.observed_at""",
        (
            sid,
            run_id,
            METHOD,
            source_path,
            cv_status,
            cv_error,
            candidate_count,
            extractor_mode,
            int(heuristic_fallback),
            _iso_now(),
        ),
    )


def _insert_cv_feature(
    conn: sqlite3.Connection,
    *,
    sid: int,
    run_id: int,
    features: Any,
    has_hover: int,
) -> None:
    bx, by, bw, bh = features.bbox
    conn.execute(
        """INSERT INTO flight_track_features
           (screenshot_id, run_id, path_shape, has_loop, has_orbit, has_hover,
            has_gap, follows_coast, near_airport, track_length_px,
            bbox_x, bbox_y, bbox_w, bbox_h, confidence, observed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?, ?, ?, ?, ?)""",
        (
            sid,
            run_id,
            features.path_shape,
            features.has_loop,
            features.has_orbit,
            has_hover,
            features.has_gap,
            features.track_length_px,
            bx,
            by,
            bw,
            bh,
            features.confidence,
            _iso_now(),
        ),
    )


def _insert_heuristic_feature(
    conn: sqlite3.Connection,
    *,
    sid: int,
    run_id: int,
    path_shape: str,
    has_hover: int,
) -> None:
    conn.execute(
        """INSERT INTO flight_track_features
           (screenshot_id, run_id, path_shape, has_loop, has_orbit, has_hover,
            has_gap, follows_coast, near_airport, confidence, observed_at)
           VALUES (?, ?, ?, 0, 0, ?, 0, 0, 0, ?, ?)""",
        (sid, run_id, path_shape, has_hover, HEURISTIC_CONFIDENCE, _iso_now()),
    )


def run(
    budget_sec: float = 86400.0,
    limit: int = 0,
    image_root: Path | None = REPO,
    db_path: Path = DB,
) -> dict[str, Any]:
    if not db_path.exists():
        raise FileNotFoundError(f"RLSM DB not found: {db_path}")
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 60000")
    ensure_schema(conn)

    sql = """SELECT s.screenshot_id, s.rel_path
             FROM screenshots s
             WHERE s.ingest_status='ok'
               AND (
                   NOT EXISTS (
                       SELECT 1 FROM flight_track_features t
                       WHERE t.screenshot_id=s.screenshot_id
                   )
                   OR NOT EXISTS (
                       SELECT 1 FROM track_extraction_receipts r
                       WHERE r.screenshot_id=s.screenshot_id AND r.method=?
                   )
                   OR EXISTS (
                       SELECT 1 FROM track_extraction_receipts r
                       WHERE r.screenshot_id=s.screenshot_id AND r.method=?
                         AND r.cv_status='failed'
                   )
               )
             ORDER BY s.screenshot_id"""
    params: tuple[Any, ...] = (METHOD, METHOD)
    if limit:
        sql += f" LIMIT {int(limit)}"
    targets = conn.execute(sql, params).fetchall()
    cursor = conn.execute(
        """INSERT INTO processing_runs
           (run_kind, started_at, status, n_inputs, n_processed, n_failed, notes)
           VALUES ('flight_track_certified', ?, 'in_progress', ?, 0, 0, ?)""",
        (_iso_now(), len(targets), json.dumps({"method": METHOD})),
    )
    run_id = int(cursor.lastrowid)
    conn.commit()

    started = time.monotonic()
    processed = failed = cv_count = no_track_count = heuristic_count = 0
    classifications: dict[str, int] = {}
    failure_samples: list[dict[str, Any]] = []

    for sid_raw, rel_path_raw in targets:
        if time.monotonic() - started > budget_sec:
            break
        sid, rel_path = int(sid_raw), str(rel_path_raw)
        observations = conn.execute(
            "SELECT speed_kt, heading_deg FROM aircraft_observations WHERE screenshot_id=?",
            (sid,),
        ).fetchall()
        heuristic_shape, has_hover = _classify_screenshot(observations)
        image_path = _resolve_image(rel_path, image_root)
        if image_path is None:
            receipt_status = "failed"
            receipt_error = "source_image_missing"
            candidate_count = 0
            extractor_mode = "unavailable"
            features = None
        else:
            receipt = vectorize_image_receipt(str(image_path))
            receipt_status = receipt.status
            receipt_error = receipt.error
            candidate_count = receipt.candidate_count
            extractor_mode = receipt.extractor_mode
            features = receipt.features

        with conn:
            conn.execute("DELETE FROM flight_track_features WHERE screenshot_id=?", (sid,))
            if features is not None:
                _insert_cv_feature(
                    conn,
                    sid=sid,
                    run_id=run_id,
                    features=features,
                    has_hover=has_hover,
                )
                path_shape = features.path_shape
                cv_count += 1
                fallback = False
            else:
                _insert_heuristic_feature(
                    conn,
                    sid=sid,
                    run_id=run_id,
                    path_shape=heuristic_shape,
                    has_hover=has_hover,
                )
                path_shape = heuristic_shape
                heuristic_count += 1
                fallback = True
                if receipt_status == "no_track_detected":
                    no_track_count += 1
            _write_receipt(
                conn,
                sid=sid,
                run_id=run_id,
                source_path=str(image_path) if image_path else None,
                cv_status=receipt_status,
                cv_error=receipt_error,
                candidate_count=candidate_count,
                extractor_mode=extractor_mode,
                heuristic_fallback=fallback,
            )
        processed += 1
        classifications[path_shape] = classifications.get(path_shape, 0) + 1
        if receipt_status == "failed":
            failed += 1
            if len(failure_samples) < 25:
                failure_samples.append(
                    {
                        "screenshot_id": sid,
                        "rel_path": rel_path,
                        "error": receipt_error,
                    }
                )

    unprocessed = len(targets) - processed
    status = "completed" if failed == 0 and unprocessed == 0 else "failed"
    notes = {
        "method": METHOD,
        "cv_classified": cv_count,
        "no_track_detected": no_track_count,
        "heuristic_fallback": heuristic_count,
        "classifications": classifications,
        "unprocessed": unprocessed,
        "failure_samples": failure_samples,
    }
    conn.execute(
        """UPDATE processing_runs
           SET ended_at=?, status=?, n_inputs=?, n_processed=?, n_failed=?, notes=?
           WHERE run_id=?""",
        (
            _iso_now(),
            status,
            len(targets),
            processed,
            failed + unprocessed,
            json.dumps(notes, sort_keys=True),
            run_id,
        ),
    )
    conn.commit()
    conn.close()
    return {
        "run_id": run_id,
        "targets": len(targets),
        "processed": processed,
        "failed": failed,
        "unprocessed": unprocessed,
        "cv_classified": cv_count,
        "no_track_detected": no_track_count,
        "heuristic_fallback": heuristic_count,
        "classifications": classifications,
        "status": status,
        "elapsed_sec": round(time.monotonic() - started, 2),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--budget-sec", type=float, default=86400.0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--image-root", type=Path, default=REPO)
    parser.add_argument("--db", type=Path, default=DB)
    args = parser.parse_args(argv)
    try:
        result = run(
            budget_sec=args.budget_sec,
            limit=args.limit,
            image_root=args.image_root,
            db_path=args.db,
        )
    except (FileNotFoundError, sqlite3.DatabaseError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
