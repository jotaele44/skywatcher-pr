#!/usr/bin/env python3
"""POLL LIVE AIRCRAFT STATE VECTORS (OpenSky Network) AND PERSIST THEM

Automated replacement for the manual, quota-limited FR24 browser-export step
(scripts/fr24_harvest.py's 25 CSV/day cap). Fetches current state vectors
over the Puerto Rico AOI from the OpenSky Network and writes them to the
adsb_state_vectors table (see schemas/adsb_state_vectors.sql).

This does NOT replace the FR24 screenshot/OCR corpus or its reconstructed
flights/track_points tables — those remain the historical source. It adds a
live, automated feed alongside them.

Usage:
    python scripts/adsb_poll.py [--db PATH] [--bbox W S E N] [--provider opensky]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (_REPO_ROOT, _REPO_ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from adsb import config  # noqa: E402
from adsb.providers import ProviderError, get_provider  # noqa: E402
from adsb.sink import persist_batch  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        default=None,
        help="SQLite DB path (default: SKYWATCHER_DB env / data/skywatcher.db)",
    )
    parser.add_argument(
        "--provider", default="opensky", help="ADS-B provider name (default: opensky)"
    )
    parser.add_argument(
        "--bbox",
        nargs=4,
        type=float,
        metavar=("WEST", "SOUTH", "EAST", "NORTH"),
        default=config.DEFAULT_BBOX,
        help="bbox to poll (default: Puerto Rico AOI envelope)",
    )
    args = parser.parse_args(argv)

    try:
        provider = get_provider(args.provider)
        states = provider.fetch_states(list(args.bbox))
    except ProviderError as exc:
        print(f"adsb_poll: fetch failed: {exc}", file=sys.stderr)
        return 1

    result = persist_batch(states, db_path=args.db, source_ref=f"adsb-poll:{args.provider}")
    if not result["persisted"]:
        print(f"adsb_poll: persist failed: {result['errors']}", file=sys.stderr)
        return 1

    print(f"adsb_poll: wrote {result['n_written']} state vectors (batch_id={result['batch_id']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
