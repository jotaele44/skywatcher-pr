"""
Step 3 – Full Pipeline Integration
====================================
Reads the physics-constrained features CSV and runs the remaining
mid-pipeline stages:

    • CRS re-validation
    • raster gradient computation
    • grid snapping
    • corridor graph construction (on a spatial sample)
    • corridor validation
    • infrastructure overlay masking

Overwrites: data/output/unified_features_enriched.csv
"""

import sys
import os
import logging
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.ingest.crs import ensure_crs_columns, validate_latlon_range
from core.ingest.raster_features import compute_raster_gradient
from core.ingest.grid_align import assign_cell_id, snap_to_grid
from core.graph.build_corridor_graph import build_corridor_graph, get_graph_metrics
from core.validation.validate_corridors import validate_corridors, report_validation
from core.masking.infrastructure_overlay import apply_infrastructure_mask

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger(__name__)

INPUT_FILE  = os.path.join('data', 'output', 'unified_features_enriched.csv')
OUTPUT_FILE = os.path.join('data', 'output', 'unified_features_enriched.csv')

# Maximum number of points to use when constructing the corridor graph
GRAPH_SAMPLE_SIZE = 500


def run_full_pipeline() -> pd.DataFrame:
    logger.info("=" * 60)
    logger.info("STEP 3: FULL PIPELINE")
    logger.info("=" * 60)

    if not os.path.exists(INPUT_FILE):
        logger.error(f"Input file not found: '{INPUT_FILE}'")
        sys.exit(1)

    df = pd.read_csv(INPUT_FILE)
    logger.info(f"Loaded {len(df)} rows from '{INPUT_FILE}'")

    # Re-validate CRS
    df = ensure_crs_columns(df)
    df = validate_latlon_range(df)

    # Ensure cell_id is present
    if 'cell_id' not in df.columns:
        df = assign_cell_id(df)

    # Raster gradient
    df = compute_raster_gradient(df)

    # Snap coordinates to grid
    df = snap_to_grid(df)

    # Build corridor graph on a spatial sample
    sample_size = min(GRAPH_SAMPLE_SIZE, len(df))
    sample_df = df.sample(n=sample_size, random_state=42).reset_index(drop=True)
    G = build_corridor_graph(sample_df, max_distance_deg=0.5)
    metrics = get_graph_metrics(G)
    logger.info(f"Corridor graph metrics: {metrics}")

    # Corridor validation
    validation_results = validate_corridors(df)
    report_validation(validation_results)

    # Infrastructure mask
    df = apply_infrastructure_mask(df)

    df.to_csv(OUTPUT_FILE, index=False)
    logger.info(f"Saved full-pipeline output: '{OUTPUT_FILE}' ({len(df)} rows)")
    return df


if __name__ == '__main__':
    run_full_pipeline()
