#!/usr/bin/env python3
"""Sync per-screenshot affine calibration from the RLSM store into the
operational FR24 DB.

Every legacy observation is stamped with the fixed-bounds guess
(coordinate_method='fixed_pr_bounds', confidence 0.65, ~1500 m error), which
keeps build_producer_package.py below its `located` floor (0.8) forever. The
RLSM store, meanwhile, carries per-image anchors (geo_anchors + backfilled
labeled_pins). This bridge joins the two by sha256 and, wherever a screenshot
has >=2 usable anchors, refits its coordinates:

  1. invert the original fixed_pr_bounds mapping (using the RLSM-recorded image
     dimensions) to recover the pixel position the legacy lat/lon came from;
  2. apply the per-screenshot affine to that pixel;
  3. UPDATE latitude/longitude/coordinate_method/coordinate_confidence/
     estimated_error_m with the residual-driven values.

Only rows still on the fixed guess (coordinate_method NULL/''/'unknown'/
'fixed_pr_bounds') are touched — better methods are never clobbered. Fits with
a median anchor residual above --max-residual-deg are skipped, mirroring
scripts/rlsm_geocode_unlabeled.py.

Usage (operator, where both DBs exist):
    python3 scripts/sync_rlsm_calibration.py \
        --rlsm-db data/rlsm/rlsm_screenshot_analysis.sqlite \
        --operational-db data/operational/fr24.db
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import List, Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from fr24.rlsm_anchors import anchors_for_screenshot, build_geo_lookup  # noqa: E402
from integration.geo_calibration import (  # noqa: E402
    GeoCalibration,
    invert_fixed_pr_bounds,
)

UPDATABLE_METHODS = {None, "", "unknown", "fixed_pr_bounds"}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Refit operational screenshot coordinates from RLSM per-image anchors."
    )
    ap.add_argument("--rlsm-db", required=True, help="RLSM sqlite (data/rlsm/...)")
    ap.add_argument("--operational-db", required=True, help="Operational FR24 sqlite")
    ap.add_argument("--max-residual-deg", type=float, default=0.05,
                    help="Skip fits whose median anchor residual exceeds this (default 0.05)")
    ap.add_argument("--places-geojson", default=None,
                    help="Override data/places.geojson for the label vocabulary")
    ap.add_argument("--dry-run", action="store_true",
                    help="Report what would change without writing")
    args = ap.parse_args(argv)

    rlsm_path = Path(args.rlsm_db)
    op_path = Path(args.operational_db)
    for path, label in ((rlsm_path, "RLSM DB"), (op_path, "operational DB")):
        if not path.exists():
            print(f"FAIL — {label} not found: {path}")
            return 1

    rlsm = sqlite3.connect(str(rlsm_path))
    op = sqlite3.connect(str(op_path))
    op.row_factory = sqlite3.Row

    rlsm_by_sha = {
        sha: (sid, w, h)
        for sid, sha, w, h in rlsm.execute(
            "SELECT screenshot_id, sha256, width, height FROM screenshots"
            " WHERE sha256 IS NOT NULL"
        )
    }
    geo_lookup = build_geo_lookup(
        rlsm, Path(args.places_geojson) if args.places_geojson else None
    )

    stats = {
        "operational_rows": 0,
        "updated": 0,
        "skipped_no_sha_match": 0,
        "skipped_method_protected": 0,
        "skipped_no_coords": 0,
        "skipped_no_dimensions": 0,
        "skipped_few_anchors": 0,
        "skipped_degenerate_fit": 0,
        "skipped_high_residual": 0,
    }
    updates = []
    for row in op.execute(
        "SELECT screenshot_id, sha256, latitude, longitude, coordinate_method"
        " FROM screenshots"
    ):
        stats["operational_rows"] += 1
        sha = row["sha256"]
        if not sha or sha not in rlsm_by_sha:
            stats["skipped_no_sha_match"] += 1
            continue
        if row["coordinate_method"] not in UPDATABLE_METHODS:
            stats["skipped_method_protected"] += 1
            continue
        if row["latitude"] is None or row["longitude"] is None:
            stats["skipped_no_coords"] += 1
            continue
        rlsm_sid, img_w, img_h = rlsm_by_sha[sha]
        if not img_w or not img_h:
            stats["skipped_no_dimensions"] += 1
            continue
        anchors = anchors_for_screenshot(rlsm, rlsm_sid, geo_lookup)
        if len(anchors) < 2:
            stats["skipped_few_anchors"] += 1
            continue
        cal = GeoCalibration(mode="per_screenshot_affine", anchors=anchors)
        if cal.affine is None:
            stats["skipped_degenerate_fit"] += 1
            continue
        if cal.affine_residual_deg > args.max_residual_deg:
            stats["skipped_high_residual"] += 1
            continue
        px, py = invert_fixed_pr_bounds(
            float(row["latitude"]), float(row["longitude"]), img_w, img_h
        )
        result = cal.pixel_to_coord(px, py, img_w, img_h)
        updates.append((
            result.lat, result.lon, result.coordinate_method,
            result.coordinate_confidence, result.estimated_error_m,
            row["screenshot_id"],
        ))
        stats["updated"] += 1

    if updates and not args.dry_run:
        op.executemany(
            "UPDATE screenshots SET latitude = ?, longitude = ?,"
            " coordinate_method = ?, coordinate_confidence = ?,"
            " estimated_error_m = ? WHERE screenshot_id = ?",
            updates,
        )
        op.commit()

    rlsm.close()
    op.close()
    print(json.dumps({"dry_run": bool(args.dry_run), **stats}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
