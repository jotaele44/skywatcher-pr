#!/usr/bin/env python3
"""
PR Intelligence System – Master Pipeline Runner
================================================
Executes all seven pipeline steps in strict order:

    1. scripts/run_real_ingestion.py
    2. scripts/run_physics_constraints.py
    3. scripts/run_full_pipeline.py
    4. scripts/run_anomaly_attribution.py
    5. scripts/run_snapshot.py
    6. scripts/run_temporal_clustering.py
    7. scripts/run_visualize.py          (optional — skipped if folium absent)

Usage:
    python run_all.py
"""

import sys
import os
import subprocess
import time
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# ── Pipeline definition (order is mandatory) ──────────────────────────────────
PIPELINE_STEPS = [
    ("Step 1: Real Data Ingestion",    "scripts/run_real_ingestion.py"),
    ("Step 2: Physics Constraints",    "scripts/run_physics_constraints.py"),
    ("Step 3: Full Pipeline",          "scripts/run_full_pipeline.py"),
    ("Step 4: Anomaly Attribution",    "scripts/run_anomaly_attribution.py"),
    ("Step 5: Snapshot",               "scripts/run_snapshot.py"),
    ("Step 6: Temporal Clustering",    "scripts/run_temporal_clustering.py"),
]


def run_step(step_name: str, script_path: str, project_root: str) -> bool:
    """Run a single pipeline step as a subprocess.

    The script is executed with the project root as the working directory so
    that relative paths (data/output/…) resolve correctly.

    Returns True on success (exit code 0), False otherwise.
    """
    abs_script = os.path.join(project_root, script_path)

    if not os.path.isfile(abs_script):
        logger.error(f"Script not found: '{abs_script}'")
        return False

    logger.info("")
    logger.info("─" * 60)
    logger.info(f"RUNNING  : {step_name}")
    logger.info(f"SCRIPT   : {script_path}")
    logger.info("─" * 60)

    start = time.time()
    result = subprocess.run(
        [sys.executable, abs_script],
        cwd=project_root,
    )
    elapsed = time.time() - start

    if result.returncode == 0:
        logger.info(f"SUCCESS  : {step_name}  ({elapsed:.2f}s)")
        return True
    else:
        logger.error(
            f"FAILED   : {step_name}  "
            f"(exit code {result.returncode}, {elapsed:.2f}s)"
        )
        return False


def main() -> None:
    # Always run relative to this file's directory
    project_root = os.path.dirname(os.path.abspath(__file__))

    logger.info("")
    logger.info("=" * 60)
    logger.info("  PR INTELLIGENCE SYSTEM")
    logger.info("  Geospatial Intelligence Pipeline")
    logger.info("=" * 60)
    logger.info(f"Project root : {project_root}")
    logger.info(f"Python       : {sys.executable}")
    logger.info(f"Steps        : {len(PIPELINE_STEPS)}")

    results: list = []
    pipeline_start = time.time()

    for step_name, script_path in PIPELINE_STEPS:
        success = run_step(step_name, script_path, project_root)
        results.append((step_name, success))
        if not success:
            logger.error(f"\nPipeline halted after failure in: {step_name}")
            break

    # ── Step 7: optional visualization (never blocks the pipeline) ───────────
    viz_ok = False
    all_core_done = len(results) == len(PIPELINE_STEPS) and all(s for _, s in results)
    if all_core_done:
        logger.info("")
        logger.info("─" * 60)
        logger.info("RUNNING  : Step 7: Visualization (optional)")
        logger.info("─" * 60)
        try:
            sys.path.insert(0, project_root)
            from scripts.run_visualize import run_visualize  # noqa: PLC0415
            viz_ok = run_visualize()
        except ImportError:
            logger.info("Step 7 skipped — folium not installed (pip install folium branca)")
        except Exception as exc:
            logger.warning(f"Step 7 visualization failed (non-fatal): {exc}")

    total_time = time.time() - pipeline_start

    # ── Final summary ────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  PIPELINE EXECUTION RESULTS")
    print("=" * 60)
    for step_name, success in results:
        tag = "[  OK  ]" if success else "[FAILED]"
        print(f"  {tag}  {step_name}")
    if all_core_done:
        viz_tag = "[  OK  ]" if viz_ok else "[ SKIP ]"
        print(f"  {viz_tag}  Step 7: Visualization")

    all_success = all(s for _, s in results) and len(results) == len(PIPELINE_STEPS)

    print("")
    if all_success:
        print("  STATUS  : ALL STEPS COMPLETED SUCCESSFULLY")
        print("")
        print("  Output files generated:")
        print("    data/output/unified_features_enriched.csv")
        print("    data/output/final_anomaly_ranked.csv")
        print("    data/output/snapshots/snapshot_<timestamp>.csv")
        if viz_ok:
            print("    data/output/pr_intelligence_map.html")
    else:
        print("  STATUS  : PIPELINE FAILED – see log above for details")

    print(f"\n  Total time : {total_time:.2f}s")
    print("=" * 60)

    sys.exit(0 if all_success else 1)


if __name__ == '__main__':
    main()
