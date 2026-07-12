"""Thin runnable SATIM Phase-2 calibration driver.

Turns the three proven Phase-2 contracts into one shippable, offline command:

    AOI detection fixture
        -> detect_raster_candidates            (raster candidate extraction)
        -> patch_candidate_with_gis_scores     (GIS overlay scoring)
        -> validate_candidate_across_dates     (multi-date persistence)
        -> satim.visual_ledger.v1 CSV

This driver **reuses** the existing Phase-2 functions verbatim; it does not
reimplement any scoring logic. It performs **no** image IO and **no** network
access: it consumes *precomputed* detections / GIS metrics / multi-date
comparison records supplied by an AOI fixture (the same fixture shape the
Phase-2 contract tests already exercise). No synthetic airspace/observation
rows are produced — this is calibration-candidate output, tagged with the
``satim.visual_ledger.v1`` schema version, not a production airspace export.

A production run substitutes a real detection/GIS/imagery backend for the
fixture loader; the contract (this driver's input mapping shape and the CSV
columns below) stays stable.

Fixture shape (JSON)::

    {
      "aois": [
        {
          "aoi_id": "PR_TILE_SEAM_CONTROL",
          "source_image_id": "IMG_...",
          "source_uri": "fixtures://...",
          "capture_datetime_utc": "2024-01-15T00:00:00Z",
          "imagery_epoch": "2024-01",
          "imagery_provider": "fixture_provider",
          "municipality": "Unknown",
          "detections": [ { "geometry": {...}, "boundary_length_px": 80,
                            "straightness": 0.9, "radiometric_delta": 0.7,
                            "classification": "probable_tile_seam" }, ... ],
          "gis_metrics": { "road_overlap_fraction": 0.8, ... },   # optional
          "overlay_scores": { "road_alignment": 0.8, ... },        # optional
          "multidate_comparisons": [ { "imagery_epoch": "2022-01",
                            "capture_datetime_utc": "2022-01-01T00:00:00Z",
                            "geometry_match_score": 0.9,
                            "radiometric_match_score": 0.8 }, ... ]
        }
      ]
    }

``gis_metrics`` (raw spatial metrics) are normalized via
``overlay_score_patch_from_metrics``; ``overlay_scores`` (already-normalized GIS
score fields) are applied directly. If both are present they are merged with
``overlay_scores`` taking precedence.

CLI::

    python3 -m fr24.calibration.run_phase2 --input fixture.json --output ledger.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

from .satim_candidate_extraction import SCHEMA_VERSION
from .satim_gis_overlay import (
    GisOverlayConfig,
    overlay_score_patch_from_metrics,
    patch_candidate_with_gis_scores,
)
from .satim_multidate_validation import (
    MultiDateValidationConfig,
    validate_candidate_across_dates,
)
from .satim_raster_candidate_extraction import (
    RasterExtractionConfig,
    detect_raster_candidates,
)

# CSV column order for the emitted satim.visual_ledger.v1 rows. The core ledger
# fields come first; the four Phase-2 multi-date review columns are appended so
# the driver's output is a single self-describing artifact. Nested structures
# (geometry, feature_scores, list fields) are JSON-encoded per cell.
LEDGER_COLUMNS = (
    "schema_version",
    "visual_id",
    "source_image_id",
    "source_uri",
    "capture_datetime_utc",
    "imagery_provider",
    "imagery_epoch",
    "aoi_id",
    "municipality",
    "candidate_kind",
    "classification",
    "confidence",
    "review_state",
    "geometry",
    "feature_scores",
    "contradiction_flags",
    "cross_source_refs",
    "created_at_utc",
    "updated_at_utc",
    # Phase-2 multi-date validation review columns:
    "multidate_epoch_class",
    "multidate_persistence",
    "multidate_decision",
    "multidate_classification_hint",
)

_JSON_COLUMNS = {"geometry", "feature_scores", "contradiction_flags", "cross_source_refs"}


def _resolve_overlay_scores(block: Mapping[str, Any]) -> dict[str, float]:
    """Build the normalized GIS overlay score patch for one AOI block.

    ``gis_metrics`` are normalized through the existing metric adapter;
    ``overlay_scores`` (already normalized) override any overlapping field.
    """
    overlay: dict[str, float] = {}
    metrics = block.get("gis_metrics")
    if metrics:
        overlay.update(overlay_score_patch_from_metrics(metrics))
    direct = block.get("overlay_scores")
    if direct:
        overlay.update({key: float(value) for key, value in direct.items()})
    return overlay


def process_aoi_block(
    block: Mapping[str, Any],
    *,
    raster_config: RasterExtractionConfig | None = None,
    overlay_config: GisOverlayConfig | None = None,
    multidate_config: MultiDateValidationConfig | None = None,
) -> list[dict[str, Any]]:
    """Run the full Phase-2 chain for one AOI block and return ledger rows.

    Each emitted row is a ``satim.visual_ledger.v1`` candidate augmented with the
    four ``multidate_*`` review columns. The multi-date validation patch is
    applied on top of the GIS-patched candidate so contradiction flags and the
    ``needs_review`` state accumulate rather than clobber one another.
    """
    detections = list(block.get("detections") or [])
    candidates = detect_raster_candidates(
        detections,
        source_image_id=str(block["source_image_id"]),
        source_uri=str(block["source_uri"]),
        capture_datetime_utc=str(block["capture_datetime_utc"]),
        aoi_id=str(block["aoi_id"]),
        config=raster_config,
    )

    overlay_scores = _resolve_overlay_scores(block)
    comparisons = list(block.get("multidate_comparisons") or [])

    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        # AOI-level provenance the raster extractor does not carry through.
        for key in ("imagery_provider", "imagery_epoch", "municipality"):
            if not candidate.get(key) and block.get(key) is not None:
                candidate[key] = block[key]

        patched = patch_candidate_with_gis_scores(
            candidate, overlay_scores, config=overlay_config
        )
        validation = validate_candidate_across_dates(
            patched, comparisons, config=multidate_config
        )

        feature_scores = dict(patched.get("feature_scores") or {})
        feature_scores["multi_date_persistence"] = validation["multi_date_persistence"]

        row = dict(patched)
        row["feature_scores"] = feature_scores
        row["contradiction_flags"] = validation["contradiction_flags"]
        row["review_state"] = validation["review_state"]
        row["multidate_epoch_class"] = validation["epoch_class"]
        row["multidate_persistence"] = validation["multi_date_persistence"]
        row["multidate_decision"] = validation["decision"]
        row["multidate_classification_hint"] = validation["classification_hint"]
        rows.append(row)
    return rows


def run_driver(
    aois: Iterable[Mapping[str, Any]],
    *,
    raster_config: RasterExtractionConfig | None = None,
    overlay_config: GisOverlayConfig | None = None,
    multidate_config: MultiDateValidationConfig | None = None,
) -> list[dict[str, Any]]:
    """Process every AOI block and return the concatenated ledger rows."""
    rows: list[dict[str, Any]] = []
    for block in aois:
        rows.extend(
            process_aoi_block(
                block,
                raster_config=raster_config,
                overlay_config=overlay_config,
                multidate_config=multidate_config,
            )
        )
    return rows


def load_fixture(path: Path) -> list[dict[str, Any]]:
    """Load AOI blocks from a JSON fixture.

    Accepts either ``{"aois": [...]}`` or a bare top-level list of AOI blocks.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, Mapping):
        aois = data.get("aois")
    else:
        aois = data
    if not isinstance(aois, list):
        raise ValueError(f"{path}: expected an 'aois' list or a top-level list of AOI blocks")
    return aois


def _cell(column: str, value: Any) -> str:
    if column in _JSON_COLUMNS:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    if value is None:
        return ""
    return str(value)


def write_ledger_csv(rows: Iterable[Mapping[str, Any]], output: Path) -> int:
    """Write ledger rows to *output* as a satim.visual_ledger.v1 CSV.

    Returns the number of data rows written.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(LEDGER_COLUMNS)
        for row in rows:
            writer.writerow([_cell(col, row.get(col)) for col in LEDGER_COLUMNS])
            count += 1
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the SATIM Phase-2 calibration chain over an AOI fixture")
    parser.add_argument("--input", required=True, help="Path to the AOI detection fixture (JSON)")
    parser.add_argument("--output", required=True, help="Path for the emitted visual-ledger CSV")
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"PHASE2 DRIVER FAILED\n- input fixture does not exist: {input_path}", file=sys.stderr)
        return 1

    try:
        aois = load_fixture(input_path)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"PHASE2 DRIVER FAILED\n- {exc}", file=sys.stderr)
        return 1

    rows = run_driver(aois)
    written = write_ledger_csv(rows, Path(args.output))
    print(
        f"SATIM Phase-2 driver: {len(aois)} AOI block(s) -> {written} "
        f"{SCHEMA_VERSION} row(s) -> {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
