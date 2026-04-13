"""
Step 5 – Snapshot & Temporal Persistence
==========================================
Reads the attributed features CSV, computes per-cell persistence scores
by comparing against all previously saved snapshots, saves a new
timestamped snapshot, and writes back the enriched DataFrame.

Overwrites: data/output/unified_features_enriched.csv
Appends:    data/output/snapshots/snapshot_<timestamp>.csv
"""

import sys
import os
import logging
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.temporal.persistence_engine import compute_persistence, save_snapshot

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger(__name__)

INPUT_FILE   = os.path.join('data', 'output', 'unified_features_enriched.csv')
OUTPUT_FILE  = os.path.join('data', 'output', 'unified_features_enriched.csv')
SNAPSHOT_DIR = os.path.join('data', 'output', 'snapshots')


def run_snapshot() -> pd.DataFrame:
    logger.info("=" * 60)
    logger.info("STEP 5: SNAPSHOT & TEMPORAL PERSISTENCE")
    logger.info("=" * 60)

    if not os.path.exists(INPUT_FILE):
        logger.error(f"Input file not found: '{INPUT_FILE}'")
        sys.exit(1)

    df = pd.read_csv(INPUT_FILE)
    logger.info(f"Loaded {len(df)} rows from '{INPUT_FILE}'")

    # Compute persistence from historical snapshots
    df = compute_persistence(df, snapshot_dir=SNAPSHOT_DIR)

    # Persist updated DataFrame before saving snapshot (snapshot preserves persistence)
    df.to_csv(OUTPUT_FILE, index=False)
    logger.info(f"Saved persistence-enriched features: '{OUTPUT_FILE}' ({len(df)} rows)")

    # Save current state as a new snapshot
    snapshot_path = save_snapshot(df, snapshot_dir=SNAPSHOT_DIR)

    # Summary
    print("\n=== SNAPSHOT SUMMARY ===")
    print(f"  Observations     : {len(df)}")
    print(f"  Snapshot file    : {snapshot_path}")
    if 'persistence' in df.columns:
        print(f"  Persistence min  : {df['persistence'].min()}")
        print(f"  Persistence max  : {df['persistence'].max()}")
        print(f"  Persistence mean : {df['persistence'].mean():.2f}")

    return df


if __name__ == '__main__':
    run_snapshot()
