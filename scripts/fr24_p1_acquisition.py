#!/usr/bin/env python3
"""CLI for the P1 coverage-ledger acquisition receipt workflow.

Network discovery is intentionally out of scope here. Use an authenticated FR24
history surface to discover dated flight IDs, record them here, then hand the
result to scripts/fr24_harvest.py for one-at-a-time playback capture.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from skywatcher.fr24.acquisition_receipts import (  # noqa: E402
    AcquisitionReceiptError,
    export_harvest_carryover,
    load_manifest,
    next_discovery_target,
    record_blocked_auth,
    record_discovery,
    status_summary,
)

DEFAULT_MANIFEST = REPO / "data" / "flight_acquisition" / "p1_2026-09-25.json"
DEFAULT_CARRYOVER = REPO / "data" / "ground_truth" / "_harvest_carryover_p1_2026-09-25.csv"


def _parse_flight(value: str) -> dict[str, str]:
    try:
        day, flight_id = value.split(":", 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("flight must be YYYY-MM-DD:FR24_ID") from exc
    return {"date": day, "flight_id": flight_id}


def main() -> None:
    parser = argparse.ArgumentParser(description="P1 flight acquisition receipt controller")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status")
    sub.add_parser("next-discovery")

    discovered = sub.add_parser("record-discovery")
    discovered.add_argument("acquisition_id")
    discovered.add_argument("--source", required=True)
    discovered.add_argument("--flight", action="append", type=_parse_flight, default=[])

    blocked = sub.add_parser("block-auth")
    blocked.add_argument("acquisition_id")
    blocked.add_argument("--reason", required=True)

    export = sub.add_parser("export-harvest")
    export.add_argument("--output", type=Path, default=DEFAULT_CARRYOVER)

    args = parser.parse_args()
    try:
        if args.command == "status":
            print(json.dumps(status_summary(load_manifest(args.manifest)), indent=2))
            return

        if args.command == "next-discovery":
            target = next_discovery_target(load_manifest(args.manifest))
            if target is None:
                print("STOP: no unresolved discovery targets", file=sys.stderr)
                raise SystemExit(4)
            print(json.dumps(target, indent=2))
            return

        if args.command == "record-discovery":
            target = record_discovery(
                args.manifest,
                args.acquisition_id,
                args.flight,
                source=args.source,
            )
            print(json.dumps(target, indent=2))
            return

        if args.command == "block-auth":
            target = record_blocked_auth(
                args.manifest,
                args.acquisition_id,
                reason=args.reason,
            )
            print(json.dumps(target, indent=2))
            return

        if args.command == "export-harvest":
            count = export_harvest_carryover(load_manifest(args.manifest), args.output)
            print(f"wrote {count} discovered flights -> {args.output}")
            print("next: python scripts/fr24_harvest.py status")
            print("then: python scripts/fr24_harvest.py next")
            return

        raise SystemExit(2)
    except AcquisitionReceiptError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
