"""
Step 1 – Real Data Ingestion
============================
Scans data/raw/ for all supported file types, loads them via the dispatcher,
unifies all DataFrames, applies CRS normalisation, extracts raster statistics,
assigns grid cell IDs, and writes:

    data/output/unified_features_enriched.csv
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

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger(__name__)

RAW_DATA_DIR = os.path.join('data', 'raw')
OUTPUT_DIR   = os.path.join('data', 'output')
OUTPUT_FILE  = os.path.join(OUTPUT_DIR, 'unified_features_enriched.csv')


def generate_synthetic_data(n_points: int = 500) -> pd.DataFrame:
    """Generate synthetic geospatial point data for demonstration purposes.

    Called only when data/raw/ contains no supported files.
    """
    logger.info(f"Generating {n_points} synthetic demonstration points")
    rng = np.random.RandomState(42)

    timestamps = pd.date_range('2024-01-01', periods=n_points, freq='1h')

    df = pd.DataFrame({
        'lat':          rng.uniform(-60.0,  60.0, n_points),
        'lon':          rng.uniform(-170.0, 170.0, n_points),
        'value':        rng.normal(0.0, 1.0, n_points),
        'intensity':    rng.uniform(0.0, 100.0, n_points),
        'timestamp':    timestamps.strftime('%Y-%m-%d %H:%M:%S'),
        'raster_value': rng.uniform(-200.0, 3000.0, n_points),
        'source_file':  'synthetic_demo',
        'source_format': 'synthetic',
    })
    return df


def run_ingestion() -> pd.DataFrame:
    logger.info("=" * 60)
    logger.info("STEP 1: REAL DATA INGESTION")
    logger.info("=" * 60)

    os.makedirs(RAW_DATA_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR,   exist_ok=True)

    file_list = scan_directory(RAW_DATA_DIR)
    all_dataframes = []

    if file_list:
        logger.info(f"Found {len(file_list)} file(s) to ingest from {RAW_DATA_DIR}")
        for filepath, fmt in file_list:
            try:
                dfs = dispatch_file(filepath)
                all_dataframes.extend(dfs)
            except Exception as exc:
                logger.warning(f"Skipping {filepath}: {exc}")
    else:
        logger.info(f"No data files found in '{RAW_DATA_DIR}' – using synthetic data")
        all_dataframes.append(generate_synthetic_data(500))

    # Unify all loaded DataFrames
    unified_df = unify_dataframes(all_dataframes)

    # CRS normalisation
    unified_df = ensure_crs_columns(unified_df)

    # Raster feature extraction
    unified_df = extract_raster_statistics(unified_df)

    # Grid cell assignment
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
