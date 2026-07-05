#!/usr/bin/env python3
"""FR24 CSV-quota targeting (strategy #6).

The 25/day FR24 harvest quota compounds when each capture ground-truths work
we already have: a flight with an existing screenshot wave gives the affine
geocoder (strategy #1) and the track vectorizer (strategy #4) exact
timestamped coordinates to calibrate against, instead of adding an isolated
track. This suggester joins the temporal waves against the harvest carryover
queue and re-ranks it:

  1. priority tails about to age out of the Gold window stay FIRST
     (scripts/fr24_harvest.py's own bump rule, reused verbatim);
  2. wave-backed flights (registration identity, >=2 observations) next —
     more wave observations rank higher, then older capture dates;
  3. everything else keeps oldest-first order.

Output is carryover-shaped (date,tail,flight_id first, extra rationale
columns after) so scripts/fr24_harvest.py's load_queue() consumes it
unchanged, plus a printed top-25 for the day's quota.

Usage:
    python3 scripts/suggest_harvest_targets.py \
        [--waves outputs/fr24_temporal_waves.csv] \
        [--carryover data/ground_truth/_harvest_carryover_YYYYMMDD.csv] \
        [--out outputs/harvest_suggestions.csv]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from fr24_harvest import (  # noqa: E402
    DAILY_QUOTA,
    EXPIRY_BUMP_DAYS,
    PRIORITY_TAILS,
    _days_to_expiry,
    latest_carryover,
)

DEFAULT_WAVES = REPO / "outputs" / "fr24_temporal_waves.csv"
DEFAULT_OUT = REPO / "outputs" / "harvest_suggestions.csv"

MIN_WAVE_OBS = 2
REGISTRATION_RE = re.compile(r"^N[0-9][0-9A-Z]{1,4}$")

OUT_FIELDS = [
    "date", "tail", "flight_id",           # carryover shape, load_queue-compatible
    "rank", "wave_obs_count", "wave_earliest_iso", "wave_latest_iso",
    "suggest_reason",
]


def load_wave_index(waves_csv: Path) -> Dict[str, dict]:
    """tail -> strongest wave (registration identity, >=MIN_WAVE_OBS frames)."""
    index: Dict[str, dict] = {}
    if not waves_csv.exists() or waves_csv.stat().st_size == 0:
        return index
    with waves_csv.open(newline="") as fh:
        for row in csv.DictReader(fh):
            identity = (row.get("wave_aircraft_identity") or "").strip().upper()
            if not REGISTRATION_RE.match(identity):
                continue
            try:
                obs_count = int(float(row.get("wave_obs_count") or 0))
            except (TypeError, ValueError):
                continue
            if obs_count < MIN_WAVE_OBS:
                continue
            current = index.get(identity)
            if current is None or obs_count > current["obs_count"]:
                index[identity] = {
                    "obs_count": obs_count,
                    "earliest": (row.get("wave_earliest_iso") or "").strip(),
                    "latest": (row.get("wave_latest_iso") or "").strip(),
                }
    return index


def _near_expiry_priority(entry: dict) -> bool:
    """fr24_harvest.prioritize_queue's bump rule, entry-level."""
    if (entry.get("tail") or "").upper() not in PRIORITY_TAILS:
        return False
    days = _days_to_expiry(entry.get("date", ""))
    return days is not None and 0 <= days <= EXPIRY_BUMP_DAYS


def rank_queue(queue: List[dict], wave_index: Dict[str, dict]) -> List[dict]:
    """Stable three-band ordering; every entry gains rank + rationale fields."""
    def band(entry: dict) -> int:
        if _near_expiry_priority(entry):
            return 0
        if (entry.get("tail") or "").upper() in wave_index:
            return 1
        return 2

    def sort_key(entry: dict):
        entry_band = band(entry)
        tail = (entry.get("tail") or "").upper()
        wave = wave_index.get(tail)
        obs = wave["obs_count"] if (entry_band == 1 and wave) else 0
        return (entry_band, -obs, entry.get("date", ""), tail)

    ranked = []
    for rank, entry in enumerate(sorted(queue, key=sort_key), 1):
        tail = (entry.get("tail") or "").upper()
        wave = wave_index.get(tail)
        out = {
            "date": entry.get("date", ""),
            "tail": entry.get("tail", ""),
            "flight_id": entry.get("flight_id", ""),
            "rank": rank,
            "wave_obs_count": wave["obs_count"] if wave else 0,
            "wave_earliest_iso": wave["earliest"] if wave else "",
            "wave_latest_iso": wave["latest"] if wave else "",
        }
        if _near_expiry_priority(entry):
            out["suggest_reason"] = (
                f"priority tail expiring from Gold window in <= {EXPIRY_BUMP_DAYS}d"
            )
        elif wave:
            out["suggest_reason"] = (
                f"screenshot wave with {wave['obs_count']} obs — CSV ground-truths"
                " affine geocoder + track vectorizer"
            )
        else:
            out["suggest_reason"] = "no wave backing; oldest-first order kept"
        ranked.append(out)
    return ranked


def read_carryover(path: Path) -> List[dict]:
    with path.open(newline="") as fh:
        return [
            {
                "date": (row.get("date") or "").strip(),
                "tail": (row.get("tail") or "").strip(),
                "flight_id": (row.get("flight_id") or "").strip(),
            }
            for row in csv.DictReader(fh)
            if (row.get("flight_id") or "").strip()
        ]


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Rank the harvest carryover queue by screenshot-wave backing."
    )
    ap.add_argument("--waves", default=str(DEFAULT_WAVES),
                    help="Waves CSV from fr24/ocr_analysis_vector.py")
    ap.add_argument("--carryover", default=None,
                    help="Carryover CSV (default: newest _harvest_carryover_*.csv)")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args(argv)

    carryover = Path(args.carryover) if args.carryover else None
    if carryover is None:
        found = latest_carryover()
        if not found:
            print("FAIL — no carryover queue found (data/ground_truth/_harvest_carryover_*.csv)")
            return 1
        carryover = Path(found)
    if not carryover.exists():
        print(f"FAIL — carryover CSV not found: {carryover}")
        return 1

    wave_index = load_wave_index(Path(args.waves))
    queue = read_carryover(carryover)
    ranked = rank_queue(queue, wave_index)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUT_FIELDS)
        writer.writeheader()
        for entry in ranked:
            writer.writerow(entry)

    wave_backed = sum(1 for e in ranked if e["wave_obs_count"])
    print(json.dumps({
        "carryover": str(carryover),
        "queue_entries": len(ranked),
        "wave_backed": wave_backed,
        "out": str(out_path),
    }, indent=2))
    print(f"\nToday's quota ({DAILY_QUOTA}):")
    for entry in ranked[:DAILY_QUOTA]:
        print(f"  {entry['rank']:>3}. {entry['date']} {entry['tail'] or '?':<8}"
              f" {entry['flight_id']:<9} {entry['suggest_reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
