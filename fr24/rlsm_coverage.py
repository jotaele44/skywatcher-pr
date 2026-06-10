"""
RLSM coverage report.

Regenerable snapshot of how much of the corpus has been processed at each phase.
Writes outputs/rlsm_coverage_report.md.

CLI:
    python3 -m fr24.rlsm_coverage
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any, Tuple

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
OUTPUTS = REPO / "outputs"
OUT_MD = OUTPUTS / "rlsm_coverage_report.md"


def _q(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> Any:
    return conn.execute(sql, params).fetchall()


def build(conn: sqlite3.Connection) -> str:
    """Build and return the full markdown report."""
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # ── Inventory ──────────────────────────────────────────────────────────────
    total       = _q(conn, "SELECT COUNT(*) FROM screenshots")[0][0]
    ok          = _q(conn, "SELECT COUNT(*) FROM screenshots WHERE ingest_status='ok'")[0][0]
    corrupt     = _q(conn, "SELECT COUNT(*) FROM screenshots WHERE ingest_status='corrupt'")[0][0]
    unreadable  = _q(conn, "SELECT COUNT(*) FROM screenshots WHERE ingest_status='unreadable'")[0][0]
    dup_groups  = _q(conn, "SELECT COUNT(DISTINCT dup_group_id) FROM screenshots WHERE dup_group_id IS NOT NULL")[0][0]
    ok_pct      = (ok / total * 100) if total else 0.0

    # ── OCR ────────────────────────────────────────────────────────────────────
    ocr_ok      = _q(conn, "SELECT COUNT(*) FROM screenshots WHERE ocr_status='ok'")[0][0]
    ocr_pending = _q(conn, "SELECT COUNT(*) FROM screenshots WHERE ingest_status='ok' AND ocr_status='pending'")[0][0]
    ocr_failed  = _q(conn, "SELECT COUNT(*) FROM screenshots WHERE ocr_status='failed'")[0][0]
    n_obs       = _q(conn, "SELECT COUNT(*) FROM ocr_observations")[0][0]
    avg_obs     = round(n_obs / ocr_ok, 1) if ocr_ok else 0.0
    ocr_ok_pct  = (ocr_ok / ok * 100) if ok else 0.0

    per_month = _q(conn, """
        SELECT month_bucket,
               COUNT(*) AS total,
               SUM(CASE WHEN ocr_status='ok' THEN 1 ELSE 0 END) AS ocr_ok,
               SUM(CASE WHEN ocr_status='pending' THEN 1 ELSE 0 END) AS ocr_pending
        FROM screenshots WHERE month_bucket IS NOT NULL
        GROUP BY month_bucket ORDER BY month_bucket
    """)

    # ── Derived ────────────────────────────────────────────────────────────────
    n_labeled    = _q(conn, "SELECT COUNT(*) FROM labeled_pois")[0][0]
    n_unlabeled  = _q(conn, "SELECT COUNT(*) FROM unlabeled_poi_candidates")[0][0]
    n_aircraft   = _q(conn, "SELECT COUNT(*) FROM aircraft_observations")[0][0]
    n_tracks     = _q(conn, "SELECT COUNT(*) FROM flight_track_features")[0][0]
    identity_rows = _q(conn, "SELECT identity_status, COUNT(*) FROM aircraft_observations GROUP BY identity_status")

    # ── Review queue ───────────────────────────────────────────────────────────
    n_review     = _q(conn, "SELECT COUNT(*) FROM manual_review_queue")[0][0]
    review_kinds = _q(conn, "SELECT item_kind, severity, COUNT(*) FROM manual_review_queue GROUP BY item_kind, severity ORDER BY item_kind, severity")

    # ── Processing runs ────────────────────────────────────────────────────────
    recent_runs = _q(conn, """
        SELECT run_id, run_kind, status, n_inputs, n_processed, n_failed,
               started_at, COALESCE(ended_at,'')
        FROM processing_runs ORDER BY run_id DESC LIMIT 10
    """)

    # ── Build markdown ─────────────────────────────────────────────────────────
    lines = []

    def ln(s: str = "") -> None:
        lines.append(s)

    ln("# RLSM coverage report")
    ln()
    ln(f"Generated: {ts}")
    ln()

    ln("## Inventory")
    ln()
    ln("| Metric | Value |")
    ln("|---|---|")
    ln(f"| Total screenshots in DB | **{total:,}** |")
    ln(f"| Ingest OK | {ok:,} ({ok_pct:.2f}%) |")
    ln(f"| Ingest corrupt | {corrupt} |")
    ln(f"| Ingest unreadable / missing-on-disk | {unreadable} |")
    ln(f"| Exact-SHA dup groups | {dup_groups} |")
    ln()

    ln("## OCR progress")
    ln()
    ln("| Metric | Value |")
    ln("|---|---|")
    ln(f"| ocr_status = 'ok' | **{ocr_ok:,}** ({ocr_ok_pct:.1f}%) |")
    ln(f"| ocr_status = 'pending' | {ocr_pending} |")
    ln(f"| ocr_status = 'failed' | {ocr_failed} |")
    ln(f"| Total ocr_observations rows | {n_obs:,} |")
    ln(f"| Avg observations per processed screenshot | {avg_obs} |")
    ln()

    if per_month:
        ln("### Per-month OCR progress")
        ln()
        ln("| Month | Total | OCR'd | Pending | % done |")
        ln("|---|---|---|---|---|")
        for bucket, t, ok_m, pend_m in per_month:
            pct = (ok_m / t * 100) if t else 0.0
            ln(f"| `{bucket}` | {t} | {ok_m} | {pend_m} | {pct:.1f}% |")
        ln()

    ln("## Derived extractions")
    ln()
    ln("| Table | Rows |")
    ln("|---|---|")
    ln(f"| labeled_pois | {n_labeled:,} |")
    ln(f"| unlabeled_poi_candidates | {n_unlabeled:,} |")
    ln(f"| aircraft_observations | {n_aircraft:,} |")
    ln(f"| flight_track_features | {n_tracks} |")
    ln()

    if identity_rows:
        ln("### Aircraft identity breakdown")
        ln()
        ln("| identity_status | count |")
        ln("|---|---|")
        for status, cnt in sorted(identity_rows):
            ln(f"| {status} | {cnt:,} |")
        ln()

    ln("## Manual review queue")
    ln()
    ln(f"Total items: **{n_review:,}**")
    ln()
    if review_kinds:
        ln("| item_kind | severity | count |")
        ln("|---|---|---|")
        for kind, sev, cnt in review_kinds:
            ln(f"| {kind} | {sev} | {cnt:,} |")
    ln()

    ln("## Processing runs (recent)")
    ln()
    ln("| run_id | kind | status | n_inputs | n_processed | n_failed | started_at | ended_at |")
    ln("|---|---|---|---|---|---|---|---|")
    for run_id, kind, status, n_in, n_proc, n_fail, started, ended in recent_runs:
        ln(f"| {run_id} | {kind} | {status} | {n_in} | {n_proc} | {n_fail} | {started} | {ended} |")
    ln()

    # ── Blockers ───────────────────────────────────────────────────────────────
    ln("## Blockers / known gaps")
    ln()
    if unreadable:
        ln(f"- **{unreadable} missing-on-disk row(s)** flagged for iCloud Photos recovery (see baseline manifest `state=missing_on_disk`).")
    if corrupt:
        ln(f"- **{corrupt} corrupt file(s)** quarantined; PIL.verify() failed.")
    if ocr_pending:
        est_h = round(ocr_pending * 6 / 3600, 1)
        ln(f"- **OCR backlog**: {ocr_pending} OK screenshots still pending. At ~6 s/image single-threaded, full completion is ~{est_h} h wall time.")
    if not unreadable and not corrupt and not ocr_pending:
        ln("No blockers.")
    ln()

    # ── How to resume ──────────────────────────────────────────────────────────
    ln("## How to resume")
    ln()
    ln("All RLSM phases are resumable. Re-run any of these and they pick up from the last committed row:")
    ln()
    ln("```bash")
    ln("# Phase 1 — inventory (idempotent; already at 100%)")
    ln("python3 scripts/rlsm_inventory.py --budget-sec 35")
    ln()
    ln("# Phase 4 — full OCR (run repeatedly until pending == 0)")
    ln("python3 -m fr24.rlsm_ocr --budget-sec 35")
    ln()
    ln("# Phase 5 — derived extractors (cheap; runs against whatever is OCR'd)")
    ln("python3 -m fr24.rlsm_extractors --kind all")
    ln()
    ln("# Phase 6 — unlabeled candidate vision pass (~0.4 s/image)")
    ln("python3 -m fr24.rlsm_unlabeled --budget-sec 35")
    ln()
    ln("# Re-export CSVs / regenerate this coverage report")
    ln("python3 -m fr24.rlsm_export")
    ln("python3 -m fr24.rlsm_coverage")
    ln("```")

    return "\n".join(lines) + "\n"


def main() -> None:
    if not DB.exists():
        print(f"[rlsm_coverage] DB not found: {DB}")
        return
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB, timeout=30.0)
    md = build(conn)
    conn.close()
    OUT_MD.write_text(md, encoding="utf-8")
    print(md)
    print(f"[rlsm_coverage] written to {OUT_MD}")


if __name__ == "__main__":
    main()
