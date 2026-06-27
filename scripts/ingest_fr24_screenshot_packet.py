#!/usr/bin/env python3
"""Ingest FR24 screenshot packets into Skywatcher test-run ledgers.

This is a conservative stub. It does not scrape FR24 or bypass security checks.
It expects analyst-provided screenshot/PDF packets and writes normalized row stubs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def build_event_stub(packet: str, event_id: str) -> dict:
    return {
        "event_id": event_id,
        "source_packet": packet,
        "source_app": "Flightradar24 over Apple Maps",
        "observed_timestamp_local": "2026-06-26 23:13 UTC-04:00",
        "observed_timestamp_utc": "2026-06-27T03:13:00Z",
        "aircraft_label": "N407PR",
        "registration": "N407PR",
        "callsign": None,
        "route_summary": "Screenshot-derived FR24 playback context over Puerto Rico.",
        "geographic_context": "Puerto Rico; Arecibo/San Sebastian/Lares/PR-370 visual sequence.",
        "page_refs": list(range(1, 14)),
        "evidence_tier": "T4",
        "confidence": "medium",
        "qa_flags": [
            "screenshot_source",
            "ui_overlay_present",
            "route_line_not_tile_seam_by_default",
            "raw_adsb_not_attached",
        ],
        "notes": "Replace with extracted metadata when raw ADS-B/FR24 export is available.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("packet", help="Path/name of analyst-provided screenshot PDF")
    parser.add_argument("--event-id", default="FR24_2026-06-26_2313UTC_N407PR_TEST01")
    parser.add_argument("--out", default="flight_event_ledger.jsonl")
    args = parser.parse_args()

    row = build_event_stub(args.packet, args.event_id)
    out_path = Path(args.out)
    out_path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
