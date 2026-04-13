"""
Step 6 – Temporal Clustering & Final Ranking
=============================================
Reads the persistence-enriched features CSV, runs DBSCAN spatial
clustering, computes per-cluster statistics, fuses all scored signals
into a final_score, enforces required output columns, and writes:

    data/output/final_anomaly_ranked.csv

Required output columns:
    lat, lon, cell_id, physics_score, slope, hydro_align,
    classification, confidence, persistence, cluster, final_score
"""

import sys
import os
import logging
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.clustering.spatial_cluster import run_dbscan_clustering, compute_cluster_statistics

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger(__name__)

INPUT_FILE  = os.path.join('data', 'output', 'unified_features_enriched.csv')
OUTPUT_FILE = os.path.join('data', 'output', 'final_anomaly_ranked.csv')

REQUIRED_OUTPUT_COLUMNS = [
    'lat',
    'lon',
    'cell_id',
    'physics_score',
    'slope',
    'hydro_align',
    'classification',
    'confidence',
    'persistence',
    'cluster',
    'final_score',
]

COLUMN_DEFAULTS = {
    'lat':            0.0,
    'lon':            0.0,
    'cell_id':        'UNKNOWN',
    'physics_score':  0.0,
    'slope':          0.0,
    'hydro_align':    0.0,
    'classification': 'unknown',
    'confidence':     0.0,
    'persistence':    1,
    'cluster':        -1,
    'final_score':    0.0,
}


def compute_final_score(df: pd.DataFrame) -> pd.DataFrame:
    """Fuse scored signals into a single final_score ∈ [0, 1].

    Signal weights (re-normalised if a column is absent):
        physics_score          30 %
        confidence             25 %
        composite_score        20 %
        persistence (norm.)    15 %
        spatial_anomaly_score  10 %
    """
    df = df.copy()

    signal_weights = {
        'physics_score':        0.30,
        'confidence':           0.25,
        'composite_score':      0.20,
        'persistence':          0.15,
        'spatial_anomaly_score': 0.10,
    }

    available: dict = {}
    for col, weight in signal_weights.items():
        if col in df.columns:
            values = df[col].fillna(0.0).values.astype(float)
            if col == 'persistence':
                # Normalise persistence to [0, 1]
                p_max = float(values.max())
                values = values / p_max if p_max > 0.0 else values
            available[col] = (values, weight)

    if not available:
        logger.warning("No score columns found – final_score set to 0.5")
        df['final_score'] = 0.5
        return df

    total_weight = sum(w for _, w in available.values())
    final_score  = np.zeros(len(df), dtype=float)

    for col, (values, weight) in available.items():
        final_score += (weight / total_weight) * values

    df['final_score'] = np.clip(final_score, 0.0, 1.0)
    logger.info(
        f"Final score: mean={df['final_score'].mean():.4f}, "
        f"max={df['final_score'].max():.4f}, "
        f"signals={list(available.keys())}"
    )
    return df


def ensure_required_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add any missing required output columns with sensible defaults."""
    df = df.copy()
    for col, default in COLUMN_DEFAULTS.items():
        if col not in df.columns:
            logger.warning(f"Required output column '{col}' missing – filling default={default!r}")
            df[col] = default
    return df


def run_temporal_clustering() -> pd.DataFrame:
    logger.info("=" * 60)
    logger.info("STEP 6: TEMPORAL CLUSTERING & FINAL RANKING")
    logger.info("=" * 60)

    if not os.path.exists(INPUT_FILE):
        logger.error(f"Input file not found: '{INPUT_FILE}'")
        sys.exit(1)

    df = pd.read_csv(INPUT_FILE)
    logger.info(f"Loaded {len(df)} rows from '{INPUT_FILE}'")

    # DBSCAN spatial clustering
    df = run_dbscan_clustering(df, eps_degrees=0.5, min_samples=3)

    # Per-cluster statistics
    df = compute_cluster_statistics(df)

    # Final score fusion
    df = compute_final_score(df)

    # Ensure all required output columns exist
    df = ensure_required_columns(df)

    # Sort by final_score descending (highest-priority first)
    df = df.sort_values('final_score', ascending=False).reset_index(drop=True)

    # Write final output
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    df.to_csv(OUTPUT_FILE, index=False)
    logger.info(f"Saved final ranked output: '{OUTPUT_FILE}' ({len(df)} rows)")

    # Summary
    print("\n=== FINAL ANOMALY RANKING SUMMARY ===")
    print(f"  Total observations : {len(df)}")

    if 'classification' in df.columns:
        print("\n  Classification breakdown:")
        for label, count in df['classification'].value_counts().items():
            print(f"    {label:<18}: {count}")

    if 'cluster' in df.columns:
        n_clusters = int((df['cluster'] >= 0).astype(bool).groupby(df['cluster']).ngroups
                         if (df['cluster'] >= 0).any() else 0)
        n_noise    = int((df['cluster'] == -1).sum())
        unique_clusters = df.loc[df['cluster'] >= 0, 'cluster'].nunique()
        print(f"\n  Unique clusters    : {unique_clusters}")
        print(f"  Noise points       : {n_noise}")

    output_cols = [c for c in REQUIRED_OUTPUT_COLUMNS if c in df.columns]
    print(f"\n  Top 10 observations by final_score:")
    print(df[output_cols].head(10).to_string(index=False))

    return df


if __name__ == '__main__':
    run_temporal_clustering()
