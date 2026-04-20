import logging
import os
import subprocess
import sys

import geopandas as gpd
import pandas as pd
from shapely.ops import unary_union

logger = logging.getLogger(__name__)


def run_query_engine(
    lat: float,
    lon: float,
    radius_km: float,
    project_root: str,
    output_csv: str = None,
    trigger_pipeline: bool = False,
    fetch_satellite: bool = False,
) -> tuple:
    """
    Orchestrate AOI creation, memory check, query execution, and reporting.

    Parameters
    ----------
    lat, lon          : WGS84 query coordinates
    radius_km         : query radius in kilometres
    project_root      : absolute path to pr_intelligence_system/
    output_csv        : if provided, save ILAP rows (no geometry) to this path
    trigger_pipeline  : if True and master dataset is missing, run run_all.py
    fetch_satellite   : if True and AOI is new, fetch Sentinel-2 data via openEO
                        and run the AOI-scoped pipeline before querying

    Returns
    -------
    (ilap_gdf, summary, report_text)
    """
    # Resolve paths
    master_path = os.path.join(project_root, "data", "output", "final_anomaly_ranked.csv")
    memory_path = os.path.join(project_root, "data", "output", "spatial_memory.gpkg")
    reports_dir = os.path.join(project_root, "data", "output", "reports")

    # Deferred imports (keep module-level imports minimal)
    from core.aoi import create_aoi
    from core.memory import check_coverage, generate_aoi_id, load_memory, save_to_memory
    from core.query import compute_summary, filter_ilaps, load_master_dataset, run_query, spatial_filter
    from reporting.report import build_report, save_report

    # 1. Build AOI
    aoi_gdf = create_aoi(lat, lon, radius_km)
    aoi_id = generate_aoi_id(lat, lon, radius_km)
    logger.info("Query AOI ID: %s", aoi_id)

    # 2. Load memory and check coverage
    memory_gdf = load_memory(memory_path)
    coverage, matching = check_coverage(aoi_gdf, memory_gdf)

    # 3. Branch on coverage status
    ilap_gdf: gpd.GeoDataFrame
    summary: dict
    save_status = "complete"

    if coverage == "full":
        ilap_gdf, summary = _load_from_cache(matching, compute_summary)

    elif coverage == "partial":
        ilap_gdf, summary, save_status = _merge_partial(
            aoi_gdf, matching, master_path, run_query, compute_summary
        )

    else:  # "new"
        if fetch_satellite:
            ilap_gdf, summary = _run_with_satellite_fetch(
                aoi_gdf, aoi_id, project_root, master_path, run_query, compute_summary
            )
        else:
            ilap_gdf, summary = _run_fresh(
                master_path, aoi_gdf, run_query, trigger_pipeline, project_root
            )

    # 4. Save results CSV
    result_path = os.path.join(reports_dir, f"{aoi_id}_results.csv")
    os.makedirs(reports_dir, exist_ok=True)
    if not ilap_gdf.empty:
        export = ilap_gdf.drop(columns=["geometry"], errors="ignore")
        export.to_csv(result_path, index=False)
    else:
        pd.DataFrame().to_csv(result_path, index=False)
    logger.info("Results saved to %s", result_path)

    # 5. Save to spatial memory
    save_to_memory(memory_path, aoi_id, aoi_gdf, summary, result_path, status=save_status)

    # 6. Generate report
    report_text = build_report(lat, lon, radius_km, summary, ilap_gdf, aoi_id=aoi_id)
    save_report(report_text, reports_dir, aoi_id)

    # 7. Optional user-specified output CSV
    if output_csv:
        export = ilap_gdf.drop(columns=["geometry"], errors="ignore")
        export.to_csv(output_csv, index=False)
        logger.info("User output CSV saved to %s", output_csv)

    return ilap_gdf, summary, report_text


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_from_cache(matching: gpd.GeoDataFrame, compute_summary) -> tuple:
    """Return ILAP results from the best cached record (most recent)."""
    # Sort by timestamp descending if available
    if "timestamp" in matching.columns:
        best = matching.sort_values("timestamp", ascending=False).iloc[0]
    else:
        best = matching.iloc[0]

    result_path = best.get("result_path", "")
    if result_path and os.path.exists(result_path):
        df = pd.read_csv(result_path)
        from shapely.geometry import Point
        import geopandas as gpd
        geoms = [Point(r.lon, r.lat) for r in df.itertuples(index=False) if hasattr(r, "lat")]
        ilap_gdf = gpd.GeoDataFrame(df, geometry=geoms if geoms else None, crs="EPSG:4326")
        summary = compute_summary(ilap_gdf)
        logger.info("Returned full cache hit: %d ILAPs.", summary["total_ilaps"])
        return ilap_gdf, summary

    logger.warning("Cached result_path not found; treating as new query.")
    return gpd.GeoDataFrame(crs="EPSG:4326"), {
        "total_ilaps": 0, "high_confidence_count": 0, "hydro_linked_count": 0,
        "corridor_ids": [], "corridor_count": 0,
        "mean_confidence": 0.0, "mean_physics_score": 0.0, "mean_hydro_align": 0.0,
    }


def _merge_partial(
    aoi_gdf: gpd.GeoDataFrame,
    matching: gpd.GeoDataFrame,
    master_path: str,
    run_query,
    compute_summary,
) -> tuple:
    """Merge cached ILAPs with fresh query on uncovered portion."""
    from shapely.ops import unary_union
    import geopandas as gpd
    import pandas as pd

    query_polygon = aoi_gdf.geometry.iloc[0]
    stored_union = unary_union(matching.geometry)
    uncovered = query_polygon.difference(stored_union)

    # Load cached rows
    cached_frames = []
    for _, row in matching.iterrows():
        rpath = row.get("result_path", "")
        if rpath and os.path.exists(rpath):
            cached_frames.append(pd.read_csv(rpath))

    if not uncovered.is_empty:
        uncovered_aoi = gpd.GeoDataFrame(
            {"geometry": [uncovered]}, crs="EPSG:4326"
        )
        try:
            new_ilap_gdf, _ = run_query(master_path, uncovered_aoi)
        except FileNotFoundError:
            logger.warning("Master dataset unavailable for partial fill.")
            new_ilap_gdf = gpd.GeoDataFrame(crs="EPSG:4326")
    else:
        new_ilap_gdf = gpd.GeoDataFrame(crs="EPSG:4326")

    # Merge
    all_frames = cached_frames + (
        [new_ilap_gdf.drop(columns=["geometry"], errors="ignore")] if not new_ilap_gdf.empty else []
    )
    if all_frames:
        merged_df = pd.concat(all_frames, ignore_index=True)
        if "cell_id" in merged_df.columns:
            merged_df = merged_df.drop_duplicates(subset="cell_id")
        from shapely.geometry import Point
        geoms = [Point(r.lon, r.lat) for r in merged_df.itertuples(index=False) if hasattr(r, "lat")]
        ilap_gdf = gpd.GeoDataFrame(merged_df, geometry=geoms if geoms else None, crs="EPSG:4326")
    else:
        ilap_gdf = gpd.GeoDataFrame(crs="EPSG:4326")

    summary = compute_summary(ilap_gdf)
    logger.info("Partial merge: %d ILAPs total.", summary["total_ilaps"])
    return ilap_gdf, summary, "partial"


def _run_fresh(
    master_path: str,
    aoi_gdf: gpd.GeoDataFrame,
    run_query,
    trigger_pipeline: bool,
    project_root: str,
) -> tuple:
    """Run a fresh query, optionally triggering the pipeline if needed."""
    try:
        ilap_gdf, summary = run_query(master_path, aoi_gdf)
        logger.info("Fresh query: %d ILAPs found.", summary["total_ilaps"])
        return ilap_gdf, summary
    except FileNotFoundError as exc:
        if trigger_pipeline:
            logger.warning("Master dataset missing; triggering pipeline...")
            _trigger_pipeline(project_root)
            ilap_gdf, summary = run_query(master_path, aoi_gdf)
            return ilap_gdf, summary
        raise RuntimeError(
            f"{exc}\nSet trigger_pipeline=True or run the pipeline manually."
        ) from exc


def _run_with_satellite_fetch(
    aoi_gdf: gpd.GeoDataFrame,
    aoi_id: str,
    project_root: str,
    master_path: str,
    run_query,
    compute_summary,
) -> tuple:
    """
    Fetch Sentinel-2 data via openEO for the AOI, run the AOI-scoped pipeline,
    then merge results with any existing master dataset data in the AOI.
    """
    from core.ingest.fetcher import fetch_for_aoi
    from core.pipeline.aoi_pipeline import run_aoi_pipeline
    from shapely.geometry import Point

    sat_raw_dir = os.path.join(project_root, "data", "raw", f"satellite_{aoi_id}")
    logger.info("Fetching satellite data for AOI %s...", aoi_id)

    tif_paths = fetch_for_aoi(aoi_gdf, aoi_id, sat_raw_dir)

    if not tif_paths:
        logger.warning("No satellite data returned; falling back to master dataset query.")
        try:
            return run_query(master_path, aoi_gdf)
        except FileNotFoundError:
            empty_summary = {
                "total_ilaps": 0, "high_confidence_count": 0, "hydro_linked_count": 0,
                "corridor_ids": [], "corridor_count": 0,
                "mean_confidence": 0.0, "mean_physics_score": 0.0, "mean_hydro_align": 0.0,
            }
            return gpd.GeoDataFrame(crs="EPSG:4326"), empty_summary

    aoi_df = run_aoi_pipeline(sat_raw_dir, aoi_id)

    if aoi_df.empty:
        logger.warning("AOI pipeline produced no output for %s.", aoi_id)
        empty_summary = {
            "total_ilaps": 0, "high_confidence_count": 0, "hydro_linked_count": 0,
            "corridor_ids": [], "corridor_count": 0,
            "mean_confidence": 0.0, "mean_physics_score": 0.0, "mean_hydro_align": 0.0,
        }
        return gpd.GeoDataFrame(crs="EPSG:4326"), empty_summary

    # Also pull in any existing master dataset points within AOI and merge
    existing_frames = []
    try:
        existing_ilap_gdf, _ = run_query(master_path, aoi_gdf)
        if not existing_ilap_gdf.empty:
            existing_frames.append(
                existing_ilap_gdf.drop(columns=["geometry"], errors="ignore")
            )
    except FileNotFoundError:
        pass

    all_frames = [aoi_df] + existing_frames
    merged = pd.concat(all_frames, ignore_index=True)
    if "cell_id" in merged.columns:
        merged = merged.drop_duplicates(subset="cell_id", keep="last")

    geoms = [Point(r.lon, r.lat) for r in merged.itertuples(index=False) if hasattr(r, "lat")]
    ilap_gdf = gpd.GeoDataFrame(merged, geometry=geoms if geoms else None, crs="EPSG:4326")

    # Filter to ILAPs only for summary
    from core.query import filter_ilaps
    ilap_gdf = filter_ilaps(ilap_gdf)
    summary = compute_summary(ilap_gdf)

    logger.info(
        "Satellite fetch + AOI pipeline: %d ILAPs found for AOI %s.",
        summary["total_ilaps"], aoi_id,
    )
    return ilap_gdf, summary


def _trigger_pipeline(project_root: str) -> None:
    run_all = os.path.join(project_root, "run_all.py")
    result = subprocess.run(
        [sys.executable, run_all],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Pipeline failed (exit {result.returncode}):\n{result.stderr}"
        )
    logger.info("Pipeline completed successfully.")
