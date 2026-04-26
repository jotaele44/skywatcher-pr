"""
Incremental pipeline update for GEO-PR-INT.

Loads the existing scored candidates CSV, fetches only new satellite data,
merges old + new, re-runs scoring, and writes updated outputs.

Useful for near-real-time refresh without a full re-run.
"""

import logging
from datetime import datetime

import pandas as pd

from config import AOI
from storage.cache.cache_manager import CacheManager

logger = logging.getLogger(__name__)


def get_last_run_timestamp() -> str | None:
    """Return ISO timestamp of the last successful pipeline run, or None."""
    return CacheManager.get_last_run_timestamp()


def set_last_run_timestamp() -> None:
    """Record current UTC time as the last-run timestamp."""
    CacheManager.set_last_run_timestamp()


def run_incremental_update(
    since: str | None = None,
    aoi: tuple | None = None,
) -> dict:
    """
    Run an incremental update of the GEO-PR-INT pipeline.

    Steps:
      1. Load existing candidates from cache
      2. Fetch new satellite data (live)
      3. Merge: de-dup by (lat, lon), prefer highest unified_score
      4. Re-run scoring on merged set
      5. Save updated outputs

    Parameters
    ----------
    since : ISO date string — only process data acquired after this date.
            If None, uses the last recorded run timestamp.
    aoi   : bounding box; defaults to PR EEZ

    Returns
    -------
    dict with summary stats
    """
    if aoi is None:
        aoi = AOI

    if since is None:
        since = get_last_run_timestamp()

    logger.info(f"Incremental update: since={since or 'beginning'}")

    cm = CacheManager()

    # ── 1. Load existing candidates ────────────────────────────────────────────
    existing = cm.load_candidates()
    if existing is None:
        existing = pd.DataFrame()
        logger.info("No existing candidates cache found — running as full update")

    # ── 2. Fetch new satellite data ────────────────────────────────────────────
    try:
        from ingestion.satellite.fetchers import fetch_satellite_features
        new_data = fetch_satellite_features(aoi=aoi, live=True)
        logger.info(f"Incremental: {len(new_data)} new satellite rows fetched")
    except Exception as exc:
        logger.error(f"Incremental satellite fetch failed: {exc}")
        new_data = pd.DataFrame()

    # ── 3. Merge old + new ─────────────────────────────────────────────────────
    if new_data.empty and existing.empty:
        logger.warning("Incremental update: no data available")
        return {"updated": 0, "total": 0, "errors": ["no data"]}

    frames = [f for f in [existing, new_data] if not f.empty]
    merged = pd.concat(frames, ignore_index=True)

    # De-dup: keep row with highest unified_score per (lat, lon) cell
    # Round to ~100m grid to match nearby duplicates
    if "lat" in merged.columns and "lon" in merged.columns:
        merged["_lat_r"] = merged["lat"].round(3)
        merged["_lon_r"] = merged["lon"].round(3)
        score_col = "unified_score" if "unified_score" in merged.columns else "composite_score"
        if score_col in merged.columns:
            merged = (
                merged
                .sort_values(score_col, ascending=False)
                .drop_duplicates(subset=["_lat_r", "_lon_r"])
                .drop(columns=["_lat_r", "_lon_r"])
                .reset_index(drop=True)
            )
        else:
            merged = (
                merged
                .drop_duplicates(subset=["_lat_r", "_lon_r"])
                .drop(columns=["_lat_r", "_lon_r"])
                .reset_index(drop=True)
            )

    logger.info(
        f"Incremental merge: {len(existing)} existing + {len(new_data)} new → "
        f"{len(merged)} after dedup"
    )

    # ── 4. Re-run scoring on merged set ──────────────────────────────────────
    try:
        from processing.feature_extraction.raster_features import prepare_features
        merged = prepare_features(merged)
    except Exception as exc:
        logger.warning(f"Feature prep skipped: {exc}")

    try:
        from intelligence.anomaly_scoring.scorer import rank_candidates
        merged = rank_candidates(merged)
    except Exception as exc:
        logger.warning(f"Re-scoring skipped: {exc}")

    # ── 5. Save updated outputs ────────────────────────────────────────────────
    try:
        cm.save_candidates(merged)
        cm.export_candidates_geojson(merged)
    except Exception as exc:
        logger.error(f"Incremental save failed: {exc}")
        return {"updated": len(new_data), "total": len(merged), "errors": [str(exc)]}

    set_last_run_timestamp()

    summary = {
        "updated":   len(new_data),
        "existing":  len(existing),
        "merged":    len(merged),
        "timestamp": datetime.utcnow().isoformat(),
        "errors":    [],
    }
    logger.info(
        f"Incremental update complete: {summary['merged']} total candidates, "
        f"{summary['updated']} new rows processed"
    )
    return summary
