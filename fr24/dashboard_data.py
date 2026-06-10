"""
FR24 DASHBOARD DATA EXPORTER

Converts the FR24 dashboard review queue CSV into a browser-loadable JSON
file consumed by dashboard.html. The dashboard renders these rows in a
read-only review queue with allowed-label-only state transitions. This
exporter does not confirm events.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import List

DASHBOARD_DATA_VERSION = "fr24_dashboard_data_v0.1.0"
LOCAL_STATE_SCHEMA_VERSION = "fr24_review_queue_local_state_v1"
LOCAL_STATE_POLICY = "local_overlay_only_candidate_rows_immutable"

PROHIBITED_LABELS = {
    "confirmed",
    "confirmed_aircraft_event",
    "confirmed_anomaly",
    "confirmed_route",
    "verified_event",
    "validated_aircraft_event",
}

ALLOWED_QUEUE_STATUSES = (
    "dashboard_review_open",
    "dashboard_review_deferred",
    "dashboard_review_rejected",
    "dashboard_review_accepted_after_manual_review",
)


def read_csv(path: Path) -> List[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    return list(csv.DictReader(path.open(encoding="utf-8")))


def read_summary(path: Path) -> dict:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def has_prohibited_label(row: dict) -> bool:
    for key in ("confirmation_status", "dedup_status", "selection_status", "review_status", "queue_status"):
        value = (row.get(key) or "").strip().lower()
        if value in PROHIBITED_LABELS:
            return True
    return False


def normalize_row(row: dict) -> dict:
    out = dict(row)
    out["confirmation_status"] = "not_confirmed"
    for key in ("priority_score", "priority_tier", "conflict_count"):
        if key in out and out[key] not in (None, ""):
            try:
                out[key] = int(out[key])
            except (TypeError, ValueError):
                pass
    return out


def run(queue_csv: Path, summary_json: Path, output_json: Path) -> dict:
    rows = read_csv(queue_csv)
    kept: List[dict] = []
    dropped = 0
    for row in rows:
        if has_prohibited_label(row):
            dropped += 1
            continue
        kept.append(normalize_row(row))

    upstream_summary = read_summary(summary_json)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dashboard_data_version": DASHBOARD_DATA_VERSION,
        "policy": "candidate_only_no_auto_confirmation",
        "allowed_queue_statuses": list(ALLOWED_QUEUE_STATUSES),
        "local_state_schema_version": LOCAL_STATE_SCHEMA_VERSION,
        "local_state_policy": LOCAL_STATE_POLICY,
        "row_count": len(kept),
        "prohibited_label_dropped": dropped,
        "tier_counts": dict(Counter(r.get("priority_tier") for r in kept)),
        "source_counts": dict(Counter(r.get("queue_source", "") for r in kept)),
        "upstream_summary": upstream_summary,
        "rows": kept,
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return {
        "queue_csv": str(queue_csv),
        "summary_json": str(summary_json),
        "output_json": str(output_json),
        "row_count": len(kept),
        "prohibited_label_dropped": dropped,
        "tier_counts": dict(Counter(r.get("priority_tier") for r in kept)),
        "source_counts": dict(Counter(r.get("queue_source", "") for r in kept)),
        "dashboard_data_version": DASHBOARD_DATA_VERSION,
        "policy": "candidate_only_no_auto_confirmation",
        "allowed_queue_statuses": list(ALLOWED_QUEUE_STATUSES),
        "local_state_schema_version": LOCAL_STATE_SCHEMA_VERSION,
        "local_state_policy": LOCAL_STATE_POLICY,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Export FR24 dashboard review queue as JSON for the browser dashboard")
    parser.add_argument("--queue-csv", default="data/_manifests/fr24_audit/fr24_dashboard_review_queue.csv")
    parser.add_argument("--summary-json", default="data/_manifests/fr24_audit/fr24_dashboard_queue_summary.json")
    parser.add_argument("--output-json", default="fr24_dashboard_review_queue.json")
    args = parser.parse_args()
    summary = run(Path(args.queue_csv), Path(args.summary_json), Path(args.output_json))
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
