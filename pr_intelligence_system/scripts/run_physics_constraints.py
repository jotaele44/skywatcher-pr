"""
Step 2 – Physics Constraints
=============================
Reads the unified features CSV, applies coordinate normalisation,
terrain / bathymetry model, slope computation, hydrological alignment,
and computes the physics_score for every point.

Overwrites: data/output/unified_features_enriched.csv
"""

import sys
import os
import logging
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.preprocessing.normalize_coords import normalize_coordinates, add_coordinate_metadata
from core.physics.terrain_bathy_engine import apply_terrain_constraints
from core.physics.slope import compute_slope, classify_slope
from core.physics.hydrology import compute_hydrology_alignment, compute_drainage_index
from core.physics.constraint_engine import compute_physics_score, apply_physics_filters

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger(__name__)

INPUT_FILE  = os.path.join('data', 'output', 'unified_features_enriched.csv')
OUTPUT_FILE = os.path.join('data', 'output', 'unified_features_enriched.csv')


def run_physics_constraints() -> pd.DataFrame:
    logger.info("=" * 60)
    logger.info("STEP 2: PHYSICS CONSTRAINTS")
    logger.info("=" * 60)

    if not os.path.exists(INPUT_FILE):
        logger.error(f"Input file not found: '{INPUT_FILE}'")
        sys.exit(1)

    df = pd.read_csv(INPUT_FILE)
    logger.info(f"Loaded {len(df)} rows from '{INPUT_FILE}'")

    # Coordinate normalisation
    df = normalize_coordinates(df)
    df = add_coordinate_metadata(df)

    # Terrain and bathymetry constraints
    df = apply_terrain_constraints(df)

    # Slope computation and classification
    df = compute_slope(df, elevation_col='elevation_proxy')
    df = classify_slope(df)

    # Hydrological alignment and drainage index
    df = compute_hydrology_alignment(df)
    df = compute_drainage_index(df)

    # Physics score (combined constraint score)
    df = compute_physics_score(df)

    # Apply threshold filter (0.0 = retain all)
    df = apply_physics_filters(df, min_physics_score=0.0)

    df.to_csv(OUTPUT_FILE, index=False)
    logger.info(
        f"Saved physics-constrained features: '{OUTPUT_FILE}' ({len(df)} rows)"
    )
    return df


if __name__ == '__main__':
    run_physics_constraints()
