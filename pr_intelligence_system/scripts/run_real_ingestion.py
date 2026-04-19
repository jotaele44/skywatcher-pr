"""
Step 1 – Real Data Ingestion
============================
Execution order:
  1. Run all satellite data fetchers (Copernicus DEM, Sentinel-1, Sentinel-2,
     VIIRS/FIRMS, NOAA GOES) — each degrades gracefully on network failure.
  2. Scan data/raw/ for local files and dispatch them to appropriate loaders.
  3. If BOTH fetchers and file scan return nothing → generate synthetic fallback.
  4. Unify → CRS normalise → raster statistics → grid alignment.

Output: data/output/unified_features_enriched.csv
"""

import sys
import os
import logging
import numpy as np
import pandas as pd

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.ingest.detect import scan_directory
from core.ingest.dispatcher import dispatch_file
from core.ingest.unify import unify_dataframes
from core.ingest.crs import ensure_crs_columns
from core.ingest.raster_features import extract_raster_statistics
from core.ingest.grid_align import assign_cell_id
from core.ingest.registry import print_registry_summary
from core.ingest.fetchers import run_all_fetchers

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger(__name__)

RAW_DATA_DIR = os.path.join('data', 'raw')
OUTPUT_DIR   = os.path.join('data', 'output')
OUTPUT_FILE  = os.path.join(OUTPUT_DIR, 'unified_features_enriched.csv')


def generate_synthetic_data(n_points: int = 500) -> pd.DataFrame:
    """Generate synthetic Puerto Rico geospatial point data for demonstration.

    Coordinates are constrained to the PR + EEZ bounding box so that the
    infrastructure overlay, hydrology, and clustering steps produce meaningful
    PR-specific outputs even when satellite fetchers are unavailable.

    Called only when both satellite fetchers AND local file scan yield nothing.
    """
    logger.info(f"Generating {n_points} synthetic demonstration points")
    rng = np.random.RandomState(42)

    # Puerto Rico + surrounding EEZ bounding box
    lat_min, lat_max = 17.8,  18.6
    lon_min, lon_max = -67.5, -65.0

    timestamps = pd.date_range('2024-01-01', periods=n_points, freq='1h')

    # Synthetic elevation: PR terrain peaks ~1338 m (Cerro de Punta)
    # Use a bimodal mix: coastal lowlands + interior highlands
    elev_coastal  = rng.uniform(0.0, 80.0, n_points // 2)
    elev_interior = rng.uniform(200.0, 1000.0, n_points - n_points // 2)
    raster_value  = np.concatenate([elev_coastal, elev_interior])
    rng.shuffle(raster_value)

    df = pd.DataFrame({
        'lat':           rng.uniform(lat_min, lat_max, n_points),
        'lon':           rng.uniform(lon_min, lon_max, n_points),
        'value':         rng.normal(0.0, 1.0, n_points),
        'intensity':     rng.uniform(0.0, 100.0, n_points),
        'timestamp':     timestamps.strftime('%Y-%m-%d %H:%M:%S'),
        'raster_value':  raster_value,
        'source_file':   'synthetic_demo',
        'source_format': 'synthetic',
    })
    return df


def run_ingestion() -> pd.DataFrame:
    logger.info("=" * 60)
    logger.info("STEP 1: REAL DATA INGESTION")
    logger.info("=" * 60)

    os.makedirs(RAW_DATA_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR,   exist_ok=True)

    all_dataframes = []

    # ── Stage 1: Satellite data fetchers ──────────────────────────────────────
    logger.info("Running satellite data fetchers...")
    try:
        fetcher_dfs = run_all_fetchers()
        non_empty   = [df for df in fetcher_dfs if df is not None and len(df) > 0]
        all_dataframes.extend(non_empty)
        logger.info(
            f"Fetchers complete: {len(non_empty)}/{len(fetcher_dfs)} returned data "
            f"({sum(len(df) for df in non_empty)} total rows)"
        )
    except Exception as exc:
        logger.warning(f"Satellite fetcher stage failed unexpectedly: {exc}")

    # ── Stage 2: Local filesystem scan ────────────────────────────────────────
    # Exclude the fetcher_cache subdirectory — those files are already loaded
    # in memory by the fetcher stage above and must not be double-counted.
    FETCHER_CACHE_SUBDIR = os.path.join(RAW_DATA_DIR, 'fetcher_cache')
    raw_file_list = scan_directory(RAW_DATA_DIR)
    file_list = [
        (fp, fmt) for fp, fmt in raw_file_list
        if not fp.startswith(os.path.abspath(FETCHER_CACHE_SUBDIR))
        and not os.path.abspath(fp).startswith(os.path.abspath(FETCHER_CACHE_SUBDIR))
    ]
    if file_list:
        logger.info(f"Found {len(file_list)} local file(s) in '{RAW_DATA_DIR}'")
        for filepath, fmt in file_list:
            try:
                dfs = dispatch_file(filepath)
                all_dataframes.extend(dfs)
            except Exception as exc:
                logger.warning(f"Skipping {filepath}: {exc}")
    else:
        logger.info(f"No local data files found in '{RAW_DATA_DIR}'")

    # ── Stage 3: Synthetic fallback (only if everything else yielded nothing) ─
    if not all_dataframes:
        logger.info("No data from fetchers or local files – using synthetic fallback")
        all_dataframes.append(generate_synthetic_data(500))

    # ── Stage 4: Unify ────────────────────────────────────────────────────────
    unified_df = unify_dataframes(all_dataframes)

    # ── Stage 5: CRS normalisation ────────────────────────────────────────────
    unified_df = ensure_crs_columns(unified_df)

    # ── Stage 6: Raster feature extraction ───────────────────────────────────
    unified_df = extract_raster_statistics(unified_df)

    # ── Stage 7: Grid cell assignment ─────────────────────────────────────────
    unified_df = assign_cell_id(unified_df)

    # Persist
    unified_df.to_csv(OUTPUT_FILE, index=False)
    logger.info(
        f"Saved unified features: '{OUTPUT_FILE}' "
        f"({len(unified_df)} rows × {len(unified_df.columns)} columns)"
    )

    print_registry_summary()
    return unified_df


if __name__ == '__main__':
    run_ingestion()
