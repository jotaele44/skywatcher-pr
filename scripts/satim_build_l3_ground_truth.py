#!/usr/bin/env python3
"""Build a SATIM L3 ground-truth CSV from the FR24 native track corpus.

L3 (`fr24.calibration.l3_ocr_scoring`) scores per-screenshot OCR predictions
against per-screenshot ground truth, keyed by ``image_path``, with exact-match
field comparison. The repo has no hand-transcribed per-screenshot labels, but it
does have FR24's own native per-flight exports in ``data/ground_truth/<TAIL>/*.csv``
(``Timestamp,UTC,Callsign,Position,Altitude,Speed,Direction``) -- an INDEPENDENT
record of the real flights (see data/ground_truth/_HARVEST_METHOD.md).

This builder uses that corpus as the best-available PROXY ground truth:

  * For each OCR sighting whose tail has a ground-truth folder, it finds the
    track point nearest in time (within --tolerance-s) and records that point's
    ``Altitude`` as the truth ``altitude_ft``.
  * ``callsign`` is left BLANK on purpose: the sighting's tail was used to pick
    the folder, so scoring OCR callsign against it would be circular. (L3 skips
    blank truth fields, so only altitude_ft is scored.)

CAVEATS (surface these when reading the L3 report):
  * This is real-world track altitude, not the value displayed on-screen, so
    L3's exact-match comparison against OCR altitude will be conservative
    (timing offset + rounding). A DEGRADED/PARTIAL L3 here reflects proxy
    semantics, not necessarily OCR failure.
  * Only tails with a ground-truth folder contribute rows.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

DEFAULT_SIGHTINGS = "outputs/ocr_events/full_sightings.jsonl"
DEFAULT_GT_ROOT = "data/ground_truth"
DEFAULT_OUTPUT = "data/fr24/ground_truth/satim_l3_ground_truth.csv"

OUTPUT_FIELDS = [
    "image_path",
    "callsign",
    "altitude_ft",
    "aircraft_type",
    "origin_code",
    "destination_code",
    "nearest_location",
]


def load_gt_tracks(gt_root: str) -> Dict[str, List[Tuple[int, str]]]:
    """tail (upper) -> sorted list of (epoch, altitude_str)."""
    tracks: Dict[str, List[Tuple[int, str]]] = {}
    root = Path(gt_root)
    for tail_dir in root.iterdir():
        if not tail_dir.is_dir():
            continue
        tail = tail_dir.name.upper()
        points: List[Tuple[int, str]] = []
        for csv_path in tail_dir.glob("*.csv"):
            try:
                with csv_path.open(newline="", encoding="utf-8") as handle:
                    for row in csv.DictReader(handle):
                        ts = row.get("Timestamp")
                        alt = row.get("Altitude")
                        if ts is None or alt in (None, ""):
                            continue
                        try:
                            points.append((int(float(ts)), str(alt).strip()))
                        except ValueError:
                            continue
            except Exception:
                continue
        if points:
            points.sort(key=lambda p: p[0])
            tracks[tail] = points
    return tracks


def nearest_altitude(points: List[Tuple[int, str]], epoch: int, tol: int) -> str | None:
    best = None
    best_d = None
    for ts, alt in points:  # linear scan; corpus is small
        d = abs(ts - epoch)
        if best_d is None or d < best_d:
            best_d, best = d, alt
    if best_d is not None and best_d <= tol:
        return best
    return None


def to_epoch(ts_utc: str) -> int | None:
    try:
        return int(datetime.fromisoformat(ts_utc).timestamp())
    except Exception:
        return None


def build(sightings: str, gt_root: str, output: str, tolerance_s: int) -> Tuple[int, int]:
    tracks = load_gt_tracks(gt_root)
    rows = []
    considered = 0
    with Path(sightings).open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            s = json.loads(line)
            tail = (s.get("tail") or "").upper()
            if tail not in tracks:
                continue
            epoch = to_epoch(s.get("ts_utc") or "")
            if epoch is None:
                continue
            considered += 1
            alt = nearest_altitude(tracks[tail], epoch, tolerance_s)
            if alt is None:
                continue
            rows.append(
                {
                    "image_path": s.get("path", ""),
                    "callsign": "",  # intentionally blank (see module docstring)
                    "altitude_ft": alt,
                    "aircraft_type": "",
                    "origin_code": "",
                    "destination_code": "",
                    "nearest_location": "",
                }
            )

    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows), considered


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sightings", default=DEFAULT_SIGHTINGS)
    parser.add_argument("--gt-root", default=DEFAULT_GT_ROOT)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--tolerance-s", type=int, default=300, help="max seconds between screenshot and track point")
    args = parser.parse_args()
    written, considered = build(args.sightings, args.gt_root, args.output, args.tolerance_s)
    print(f"tails-with-GT sightings considered: {considered}; truth rows written: {written} -> {args.output}")


if __name__ == "__main__":
    main()
