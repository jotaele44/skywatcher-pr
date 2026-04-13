"""
Step 4 – Anomaly Attribution
==============================
Reads the full-pipeline features CSV and performs:

    • rule-based classification (anomaly / infrastructure / natural / noise)
    • confidence scoring
    • spatial anomaly scoring (LOF)
    • composite attribution scoring
    • infrastructure zone reclassification
    • anomaly ranking

Overwrites: data/output/unified_features_enriched.csv
"""

import sys
import os
import logging
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.attribution.anomaly_attribution import (
    classify_observations,
    compute_confidence,
    rank_anomalies,
)
from core.attribution.advanced_attribution import (
    compute_spatial_anomaly_score,
    compute_composite_attribution_score,
)
from core.masking.infrastructure_overlay import adjust_classification_for_infrastructure

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger(__name__)

INPUT_FILE  = os.path.join('data', 'output', 'unified_features_enriched.csv')
OUTPUT_FILE = os.path.join('data', 'output', 'unified_features_enriched.csv')


def run_anomaly_attribution() -> pd.DataFrame:
    logger.info("=" * 60)
    logger.info("STEP 4: ANOMALY ATTRIBUTION")
    logger.info("=" * 60)

    if not os.path.exists(INPUT_FILE):
        logger.error(f"Input file not found: '{INPUT_FILE}'")
        sys.exit(1)

    df = pd.read_csv(INPUT_FILE)
    logger.info(f"Loaded {len(df)} rows from '{INPUT_FILE}'")

    # Rule-based classification
    df = classify_observations(df)

    # Confidence scoring
    df = compute_confidence(df)

    # Spatial anomaly score (LOF)
    df = compute_spatial_anomaly_score(df)

    # Composite attribution score
    df = compute_composite_attribution_score(df)

    # Reclassify anomalies inside infrastructure zones
    df = adjust_classification_for_infrastructure(df)

    # Rank all observations by physics_score + confidence
    df = rank_anomalies(df)

    df.to_csv(OUTPUT_FILE, index=False)
    logger.info(f"Saved attribution output: '{OUTPUT_FILE}' ({len(df)} rows)")

    # Summary
    print("\n=== ATTRIBUTION SUMMARY ===")
    print(df['classification'].value_counts().to_string())

    top_anomalies = df[df['classification'] == 'anomaly'].head(10)
    if len(top_anomalies) > 0:
        display_cols = [
            c for c in ['lat', 'lon', 'physics_score', 'confidence', 'classification']
            if c in top_anomalies.columns
        ]
        print(f"\nTop {len(top_anomalies)} anomalies by physics_score:")
        print(top_anomalies[display_cols].to_string(index=False))

    return df


if __name__ == '__main__':
    run_anomaly_attribution()
