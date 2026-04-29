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
    fetch_sar: bool = False,
    aspects: list = None,
    publish_felt: bool = False,
    felt_api_key: str = None,
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
    fetch_satellite   : if True and AOI is new, fetch Sentinel-2 + DEM via openEO
    fetch_sar         : if True, also fetch Sentinel-1 CARD-BS via ODP (implies fetch_satellite)
    aspects           : optional list of aspect names to filter ILAPs post-query
    publish_felt      : if True, publish ILAP results to a new Felt map
    felt_api_key      : Felt API key (falls back to FELT_API_KEY env var)

    Returns
    -------
    (ilap_gdf, summary, report_text)
    """
    if fetch_sar:
        fetch_satellite = True

    master_path = os.path.join(project_root, "data", "output", "final_anomaly_ranked.csv")
    memory_path = os.path.join(project_root, "data", "output", "spatial_memory.gpkg")
    reports_dir = os.path.join(project_root, "data", "output", "reports")

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
                aoi_gdf, aoi_id, project_root, master_path,
                run_query, compute_summary, include_sar=fetch_sar,
            )
        else:
            ilap_gdf, summary = _run_fresh(
                master_path, aoi_gdf, run_query, trigger_pipeline, project_root
            )

    # 4. Apply aspect filters (post-branch, before report)
    if aspects:
        from core.location import apply_aspects
        ilap_gdf = apply_aspects(ilap_gdf, aspects)
        summary = compute_summary(ilap_gdf)

    # 5. Save results CSV
    result_path = os.path.join(reports_dir, f"{aoi_id}_results.csv")
    os.makedirs(reports_dir, exist_ok=True)
    ilap_gdf.drop(columns=["geometry"], errors="ignore").to_csv(result_path, index=False)
    logger.info("Results saved to %s", result_path)

    # 6. Save to spatial memory
    save_to_memory(memory_path, aoi_id, aoi_gdf, summary, result_path, status=save_status)

    # 7. Build and save report
    report_text = build_report(lat, lon, radius_km, summary, ilap_gdf, aoi_id=aoi_id)
    save_report(report_text, reports_dir, aoi_id)

    # 8. Optionally publish to Felt
    if publish_felt:
        key = felt_api_key or os.environ.get("FELT_API_KEY", "")
        if not key:
            logger.warning("--publish-felt set but FELT_API_KEY not found; skipping.")
        elif ilap_gdf.empty:
            logger.warning("No ILAPs to publish; skipping Felt upload.")
        else:
            try:
                from core.export.felt_publisher import publish_ilaps
                map_url = publish_ilaps(ilap_gdf, lat, lon, aoi_id, key)
                report_text += f"\nFelt Map: {map_url}"
                logger.info("Felt map published: %s", map_url)
            except Exception as exc:
                logger.warning("Felt publish failed: %s", exc)

    # 9. Optional user-specified output CSV
    if output_csv:
        ilap_gdf.drop(columns=["geometry"], errors="ignore").to_csv(output_csv, index=False)
        logger.info("User output CSV saved to %s", output_csv)

    return ilap_gdf, summary, report_text


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_from_cache(matching: gpd.GeoDataFrame, compute_summary) -> tuple:
    """Return ILAP results from the best cached record (most recent)."""
    if "timestamp" in matching.columns:
        best = matching.sort_values("timestamp", ascending=False).iloc[0]
    else:
        best = matching.iloc[0]

    result_path = best.get("result_path", "")
    if result_path and os.path.exists(result_path):
        try:
            df = pd.read_csv(result_path)
        except pd.errors.EmptyDataError:
            df = pd.DataFrame()
        from shapely.geometry import Point
        geoms = [Point(r.lon, r.lat) for r in df.itertuples(index=False) if hasattr(r, "lat")]
        ilap_gdf = gpd.GeoDataFrame(df, geometry=geoms if geoms else None, crs="EPSG:4326")
        summary = compute_summary(ilap_gdf)
        logger.info("Returned full cache hit: %d ILAPs.", summary["total_ilaps"])
        return ilap_gdf, summary

    logger.warning("Cached result_path not found; treating as new query.")
    return _empty_gdf(), _empty_summary()


def _merge_partial(
    aoi_gdf: gpd.GeoDataFrame,
    matching: gpd.GeoDataFrame,
    master_path: str,
    run_query,
    compute_summary,
) -> tuple:
    """Merge cached ILAPs with fresh query on uncovered portion."""
    query_polygon = aoi_gdf.geometry.iloc[0]
    stored_union = unary_union(matching.geometry)
    uncovered = query_polygon.difference(stored_union)

    cached_frames = []
    for _, row in matching.iterrows():
        rpath = row.get("result_path", "")
        if rpath and os.path.exists(rpath):
            try:
                cached_frames.append(pd.read_csv(rpath))
            except pd.errors.EmptyDataError:
                pass

    if not uncovered.is_empty:
        uncovered_aoi = gpd.GeoDataFrame({"geometry": [uncovered]}, crs="EPSG:4326")
        try:
            new_ilap_gdf, _ = run_query(master_path, uncovered_aoi)
        except FileNotFoundError:
            logger.warning("Master dataset unavailable for partial fill.")
            new_ilap_gdf = _empty_gdf()
    else:
        new_ilap_gdf = _empty_gdf()

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
        ilap_gdf = _empty_gdf()

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
    include_sar: bool = False,
) -> tuple:
    """
    Fetch Sentinel-2 (+ optionally SAR) for the AOI, run the AOI pipeline,
    persist results to master dataset, and return ILAPs + summary.
    """
    from core.ingest.fetcher import fetch_for_aoi
    from core.pipeline.aoi_pipeline import run_aoi_pipeline
    from shapely.geometry import Point

    sat_raw_dir = os.path.join(project_root, "data", "raw", f"satellite_{aoi_id}")
    logger.info("Fetching satellite data for AOI %s (SAR=%s)...", aoi_id, include_sar)

    tif_paths = fetch_for_aoi(aoi_gdf, aoi_id, sat_raw_dir, include_sar=include_sar)

    if not tif_paths:
        logger.warning("No satellite data returned; falling back to master dataset query.")
        try:
            return run_query(master_path, aoi_gdf)
        except FileNotFoundError:
            return _empty_gdf(), _empty_summary()

    # Compute bbox for LiDAR streaming (WGS84, from AOI polygon bounds)
    minx, miny, maxx, maxy = aoi_gdf.total_bounds
    aoi_bbox = {"west": minx, "south": miny, "east": maxx, "north": maxy}

    aoi_df = run_aoi_pipeline(sat_raw_dir, aoi_id, aoi_bbox=aoi_bbox)

    if aoi_df.empty:
        logger.warning("AOI pipeline produced no output for %s.", aoi_id)
        return _empty_gdf(), _empty_summary()

    _append_to_master(aoi_df, master_path)

    # Merge with any pre-existing master dataset points in the AOI
    existing_frames = []
    try:
        existing_ilap_gdf, _ = run_query(master_path, aoi_gdf)
        if not existing_ilap_gdf.empty:
            existing_frames.append(existing_ilap_gdf.drop(columns=["geometry"], errors="ignore"))
    except FileNotFoundError:
        pass

    all_frames = [aoi_df] + existing_frames
    merged = pd.concat(all_frames, ignore_index=True)
    if "cell_id" in merged.columns:
        merged = merged.drop_duplicates(subset="cell_id", keep="last")

    geoms = [Point(r.lon, r.lat) for r in merged.itertuples(index=False) if hasattr(r, "lat")]
    ilap_gdf = gpd.GeoDataFrame(merged, geometry=geoms if geoms else None, crs="EPSG:4326")

    from core.query import filter_ilaps
    ilap_gdf = filter_ilaps(ilap_gdf)
    summary = compute_summary(ilap_gdf)

    logger.info(
        "Satellite fetch + AOI pipeline: %d ILAPs for AOI %s.", summary["total_ilaps"], aoi_id
    )
    return ilap_gdf, summary


def _append_to_master(aoi_df: pd.DataFrame, master_path: str) -> None:
    """Append AOI pipeline rows to final_anomaly_ranked.csv, deduplicating on cell_id."""
    rows = aoi_df.drop(columns=["geometry"], errors="ignore")
    if rows.empty:
        return
    try:
        os.makedirs(os.path.dirname(master_path), exist_ok=True)
        if os.path.exists(master_path):
            existing = pd.read_csv(master_path)
            combined = pd.concat([existing, rows], ignore_index=True)
            if "cell_id" in combined.columns:
                combined = combined.drop_duplicates(subset="cell_id", keep="last")
        else:
            combined = rows
        combined.to_csv(master_path, index=False)
        logger.info("Master dataset updated: %d total rows.", len(combined))
    except Exception as exc:
        logger.warning("Could not update master dataset: %s", exc)


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


def _empty_summary() -> dict:
    return {
        "total_ilaps": 0, "high_confidence_count": 0, "hydro_linked_count": 0,
        "corridor_ids": [], "corridor_count": 0,
        "mean_confidence": 0.0, "mean_physics_score": 0.0, "mean_hydro_align": 0.0,
    }


def _empty_gdf() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame({"geometry": gpd.GeoSeries(dtype="geometry")}, crs="EPSG:4326")
