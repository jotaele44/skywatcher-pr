#!/usr/bin/env python3
"""Stage the SATIM L5 tile-seam / shadow candidates CSV.

L5 (`fr24.calibration.l5_tile_seam_shadow_calibration`) discriminates satellite/
aerial imagery artifacts (tile seams) from real ground features, scoring rows of
per-candidate feature values:

    straight_boundary_score, radiometric_discontinuity_score,
    cloud_mask_intersection, shadow_mask_intersection, dem_hillshade_alignment,
    multi_date_persistence, infrastructure_alignment

This is a DIFFERENT domain from the FR24 screenshot corpus. As of this writing
the repo contains no satellite/aerial candidates and no producer that extracts
these features from raw imagery, so there is nothing genuine to feed L5.

Rather than fabricate feature scores, this builder emits a header-only candidates
CSV so L5 runs and reports ``MISSING`` honestly. When real candidates exist
(marked satellite/aerial features with the columns above), pass them via
``--source`` and they are copied through unchanged.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

DEFAULT_OUTPUT = "data/satim/l5_candidates.csv"

CANDIDATE_FIELDS = [
    "candidate_id",
    "straight_boundary_score",
    "radiometric_discontinuity_score",
    "cloud_mask_intersection",
    "shadow_mask_intersection",
    "dem_hillshade_alignment",
    "multi_date_persistence",
    "infrastructure_alignment",
]


def build(source: str | None, output: str) -> int:
    rows = []
    if source:
        with Path(source).open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))

    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CANDIDATE_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", default=None, help="optional real candidates CSV to pass through")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    count = build(args.source, args.output)
    if count == 0:
        print(f"no genuine L5 candidates available -> wrote header-only {args.output} (L5 will report MISSING)")
    else:
        print(f"wrote {count} candidates -> {args.output}")


if __name__ == "__main__":
    main()
