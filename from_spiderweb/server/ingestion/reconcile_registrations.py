"""
Reconcile aircraft registrations to recover ones that were missed.

Compares three sources of registrations:

  * the FR24 export CSV  (what vision extraction captured)
  * the priis.db events  (what actually reached the app)
  * a known/expected list you supply (e.g. copied from FR24's own alerts)

and reports two kinds of gap:

  * ingest gaps — present in the FR24 CSV but missing from the DB. These are
    recoverable by re-running ingest (ingest now persists registration with
    ON CONFLICT DO UPDATE, so it backfills).
  * true misses — on your known list but absent from both the CSV and the DB.
    These were never captured; re-scan the screenshots (fr24_vision_ingest
    --retry-errors) and/or check FR24 directly.

Both are written to outputs/registration_recovery_queue.csv. True misses also
raise "expected but missing" alerts.

Usage (from repo root):
    python3 server/ingestion/reconcile_registrations.py \
        --known known_regs.csv [--csv outputs/fr24_selected_export.csv] \
        [--db server/priis.db] [--no-alerts]
"""
from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from server.ingestion.registration_alerts import _insert_alert, seen_registrations  # noqa: E402
from server.ingestion.registration_common import (  # noqa: E402
    load_known_registrations,
    normalize_registration,
)
from server.notifications.notifier import send_alert  # noqa: E402

DB_DEFAULT = _ROOT / "server" / "priis.db"
CSV_DEFAULT = _ROOT / "outputs" / "fr24_selected_export.csv"
QUEUE_DEFAULT = _ROOT / "outputs" / "registration_recovery_queue.csv"

QUEUE_FIELDS = ["registration", "registration_normalized", "category", "image_path", "note"]


def csv_registrations(csv_path: Path) -> Dict[str, Dict[str, str]]:
    """Map normalized registration → a representative {registration, image_path} row."""
    out: Dict[str, Dict[str, str]] = {}
    if not csv_path.exists():
        return out
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            reg = (row.get("registration") or "").strip()
            norm = normalize_registration(reg)
            if norm and norm not in out:
                out[norm] = {
                    "registration": reg,
                    "image_path": (row.get("image_path") or "").strip(),
                }
    return out


def reconcile(
    conn: sqlite3.Connection,
    csv_path: Path,
    known_path: Path,
    queue_path: Path,
    *,
    raise_alerts: bool = True,
    now: Optional[datetime] = None,
    env: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    now = now or datetime.utcnow()
    today = now.strftime("%Y-%m-%d")

    csv_map = csv_registrations(csv_path)
    db_norms = set(seen_registrations(conn).keys())
    known = load_known_registrations(known_path)

    queue_rows: List[Dict[str, str]] = []

    # Ingest gaps: in the CSV, not in the DB.
    ingest_gaps = sorted(set(csv_map) - db_norms)
    for norm in ingest_gaps:
        info = csv_map[norm]
        queue_rows.append({
            "registration": info["registration"],
            "registration_normalized": norm,
            "category": "ingest_gap",
            "image_path": info["image_path"],
            "note": "Present in FR24 CSV but not in DB — re-run ingest_data.py to backfill.",
        })

    # True misses: on the known list, in neither the CSV nor the DB.
    captured = set(csv_map) | db_norms
    true_misses = [n for n in known if n not in captured]
    new_alerts: List[Dict[str, Any]] = []
    for norm in true_misses:
        queue_rows.append({
            "registration": norm,
            "registration_normalized": norm,
            "category": "known_miss",
            "image_path": "",
            "note": "On known list but never captured — re-scan screenshots "
                    "(fr24_vision_ingest --retry-errors) or check FR24.",
        })
        if raise_alerts:
            alert = {
                "id": f"REG-MISS-{norm}-{today}",
                "at": now.isoformat(),
                "kind": "aircraft",
                "title": f"Expected aircraft {norm} missing from captured data",
                "tier": "T1",
                "investigation": None,
                "registration": norm,
            }
            if _insert_alert(conn, alert):
                new_alerts.append(alert)

    conn.commit()

    queue_path.parent.mkdir(parents=True, exist_ok=True)
    with open(queue_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=QUEUE_FIELDS)
        writer.writeheader()
        writer.writerows(queue_rows)

    notified = 0
    if raise_alerts:
        for alert in new_alerts:
            if send_alert(alert, env=env):
                notified += 1

    return {
        "csv_registrations": len(csv_map),
        "db_registrations": len(db_norms),
        "known_registrations": len(known),
        "ingest_gaps": len(ingest_gaps),
        "true_misses": len(true_misses),
        "new_alerts": len(new_alerts),
        "notified": notified,
        "queue_path": str(queue_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcile registrations and queue recoveries")
    parser.add_argument("--known", required=True, help="Known/expected registrations file (CSV or text)")
    parser.add_argument("--csv", default=str(CSV_DEFAULT), help="FR24 export CSV")
    parser.add_argument("--db", default=str(DB_DEFAULT), help="Path to priis.db")
    parser.add_argument("--queue", default=str(QUEUE_DEFAULT), help="Recovery queue output CSV")
    parser.add_argument("--no-alerts", action="store_true", help="Do not raise/notify alerts")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        summary = reconcile(
            conn, Path(args.csv), Path(args.known), Path(args.queue),
            raise_alerts=not args.no_alerts,
        )
    finally:
        conn.close()
    print(summary)


if __name__ == "__main__":
    main()
