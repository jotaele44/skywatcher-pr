#!/usr/bin/env python3
"""
Step 7 (optional): Generate interactive HTML map from pipeline output.

Reads  : data/output/final_anomaly_ranked.csv
Writes : data/output/pr_intelligence_map.html

Usage:
    python scripts/run_visualize.py
    # or via run_all.py (Step 7, auto-skipped if folium not installed)
"""

import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

INPUT_CSV   = os.path.join('data', 'output', 'final_anomaly_ranked.csv')
OUTPUT_HTML = os.path.join('data', 'output', 'pr_intelligence_map.html')


def run_visualize() -> bool:
    try:
        import pandas as pd
        from core.viz.map_builder import build_pr_map
    except ImportError as exc:
        logger.warning(f"Visualization skipped — missing dependency: {exc}")
        return False

    if not os.path.exists(INPUT_CSV):
        logger.warning(
            f"Input not found: {INPUT_CSV}\n"
            "Run the full pipeline first: python run_all.py"
        )
        return False

    logger.info(f"Loading {INPUT_CSV} …")
    try:
        df = pd.read_csv(INPUT_CSV)
    except Exception as exc:
        logger.error(f"Failed to read {INPUT_CSV}: {exc}")
        return False

    logger.info(f"Loaded {len(df)} rows × {len(df.columns)} columns")

    result = build_pr_map(df, OUTPUT_HTML)
    if result is None:
        return False

    print("")
    print("=" * 60)
    print("  MAP GENERATED SUCCESSFULLY")
    print(f"  {os.path.abspath(OUTPUT_HTML)}")
    print("=" * 60)
    print("  Open in your browser:")
    print(f"    open {OUTPUT_HTML}")
    print("=" * 60)
    return True


if __name__ == '__main__':
    ok = run_visualize()
    sys.exit(0 if ok else 1)
