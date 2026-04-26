"""
Full pipeline orchestrator for GEO-PR-INT.

Runs all 13 steps from raw ingestion through unified scoring and output.
Each step is wrapped in try/except so a single failure never aborts the run.

Returns a PipelineResult dataclass with all DataFrames plus run metadata.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

from config import AOI, GEO_PR_INT_ROOT, SETTINGS
from utils.logging import configure_logging

logger = logging.getLogger(__name__)

_OUTPUT = SETTINGS["output"]
_CSV_DIR = GEO_PR_INT_ROOT / _OUTPUT.get("csv_dir", "outputs/csv")
_GJ_DIR  = GEO_PR_INT_ROOT / _OUTPUT.get("geojson_dir", "outputs/geojson")


@dataclass
class PipelineResult:
    candidates_df:   pd.DataFrame = field(default_factory=pd.DataFrame)
    corridors_df:    pd.DataFrame = field(default_factory=pd.DataFrame)
    contracts_df:    pd.DataFrame = field(default_factory=pd.DataFrame)
    run_timestamp:   str = ""
    step_timings:    dict = field(default_factory=dict)
    errors:          list = field(default_factory=list)
    summary:         dict = field(default_factory=dict)


def _timed(name: str, fn, timings: dict, errors: list):
    """Run fn(), record elapsed time, catch and log exceptions."""
    t0 = time.time()
    try:
        result = fn()
        timings[name] = round(time.time() - t0, 2)
        return result
    except Exception as exc:
        elapsed = round(time.time() - t0, 2)
        timings[name] = elapsed
        errors.append(f"{name}: {exc}")
        logger.error(f"Step '{name}' failed in {elapsed}s: {exc}")
        return None


def run_full_pipeline(
    aoi: tuple | None = None,
    live_satellite: bool = False,
    force_api: bool = False,
) -> PipelineResult:
    """
    Execute the full GEO-PR-INT pipeline.

    Parameters
    ----------
    aoi            : bounding box (min_lon, min_lat, max_lon, max_lat); defaults to PR EEZ
    live_satellite : re-run the pr_intelligence_system satellite pipeline (slow)
    force_api      : bypass local contract CSV and query USASpending API directly

    Returns
    -------
    PipelineResult with all DataFrames and metadata
    """
    if aoi is None:
        aoi = AOI

    _CSV_DIR.mkdir(parents=True, exist_ok=True)
    _GJ_DIR.mkdir(parents=True, exist_ok=True)

    result = PipelineResult(run_timestamp=datetime.utcnow().isoformat())
    timings = result.step_timings
    errors  = result.errors

    logger.info("=" * 60)
    logger.info("GEO-PR-INT full pipeline started")
    logger.info(f"AOI: {aoi}  |  live={live_satellite}  |  force_api={force_api}")
    logger.info("=" * 60)

    # ── Step 1: Load ILAP candidates ──────────────────────────────────────────
    from ingestion.satellite.fetchers import fetch_satellite_features
    candidates = _timed(
        "1_satellite_ingestion",
        lambda: fetch_satellite_features(aoi=aoi, live=live_satellite),
        timings, errors,
    ) or pd.DataFrame()

    if candidates.empty:
        logger.warning("Step 1: No ILAP candidates loaded — pipeline will produce empty outputs")

    # ── Step 2: Load contracts ────────────────────────────────────────────────
    from ingestion.contracts.loader import load_contracts
    contracts = _timed(
        "2_contract_ingestion",
        lambda: load_contracts(force_api=force_api),
        timings, errors,
    ) or pd.DataFrame()

    result.contracts_df = contracts
    logger.info(f"Step 2: {len(contracts)} contracts loaded")

    # ── Step 3: Load hydro features ───────────────────────────────────────────
    from ingestion.hydro.hydrography import load_hydro_features
    hydro = _timed(
        "3_hydro_ingestion",
        lambda: load_hydro_features(aoi=aoi),
        timings, errors,
    ) or pd.DataFrame()

    logger.info(f"Step 3: {len(hydro)} hydro nodes loaded")

    # ── Step 4: Load OSM dead-ends ────────────────────────────────────────────
    from ingestion.osm.road_network import fetch_dead_ends
    dead_ends = _timed(
        "4_osm_ingestion",
        lambda: fetch_dead_ends(aoi=aoi),
        timings, errors,
    ) or pd.DataFrame()

    logger.info(f"Step 4: {len(dead_ends)} OSM dead-end nodes loaded")

    if candidates.empty:
        logger.warning("Skipping processing steps — no candidates")
        _write_outputs(result, candidates, contracts)
        return result

    # ── Step 5: Normalise entities ────────────────────────────────────────────
    from processing.normalization.entity_normalizer import enrich_contracts_with_norms
    contracts = _timed(
        "5_entity_normalisation",
        lambda: enrich_contracts_with_norms(contracts),
        timings, errors,
    ) or contracts

    # ── Step 6: Extract raster features ──────────────────────────────────────
    from processing.feature_extraction.raster_features import prepare_features
    candidates = _timed(
        "6_feature_extraction",
        lambda: prepare_features(candidates),
        timings, errors,
    ) or candidates

    logger.info(f"Step 6: features extracted, {len(candidates)} candidates")

    # ── Step 7: Detect linear corridors ──────────────────────────────────────
    from processing.geometry_detection.linear_detector import run_geometry_detection
    candidates = _timed(
        "7_geometry_detection",
        lambda: run_geometry_detection(candidates),
        timings, errors,
    ) or candidates

    n_corr = int(candidates.get("linear_corridor", pd.Series(False)).sum()) if "linear_corridor" in candidates.columns else 0
    logger.info(f"Step 7: {n_corr} linear corridor candidates identified")

    # ── Step 8: NDVI scoring ──────────────────────────────────────────────────
    from processing.ndvi_analysis.ndvi_detector import run_ndvi_detection
    candidates = _timed(
        "8_ndvi_detection",
        lambda: run_ndvi_detection(candidates),
        timings, errors,
    ) or candidates

    # ── Step 9: Link contracts spatially ──────────────────────────────────────
    from intelligence.contract_linking.linker import ContractLinker
    linker = ContractLinker()
    candidates = _timed(
        "9_contract_linking",
        lambda: linker.link(candidates, contracts),
        timings, errors,
    ) or candidates

    from intelligence.contract_linking.linker import summarise_contract_links
    link_summary = summarise_contract_links(candidates)
    logger.info(
        f"Step 9: {link_summary.get('total_matched', 0)} candidates linked to contracts "
        f"(${link_summary.get('total_dollars_linked', 0):,.0f} total)"
    )

    # ── Step 10: Hydro proximity ──────────────────────────────────────────────
    from intelligence.hydro_linking.hydro_linker import HydroLinker
    hlinker = HydroLinker()
    candidates = _timed(
        "10_hydro_linking",
        lambda: hlinker.link(candidates, hydro),
        timings, errors,
    ) or candidates

    # ── Step 11: Compute unified scores ───────────────────────────────────────
    from intelligence.anomaly_scoring.scorer import rank_candidates, score_summary
    candidates = _timed(
        "11_scoring",
        lambda: rank_candidates(candidates),
        timings, errors,
    ) or candidates

    result.summary = score_summary(candidates) if "unified_score" in candidates.columns else {}
    logger.info(
        f"Step 11: scoring complete — "
        f"CRITICAL={result.summary.get('critical_count', 0)}, "
        f"HIGH={result.summary.get('high_count', 0)}, "
        f"mean={result.summary.get('mean_score', 0):.1f}"
    )

    # ── Step 12: Build corridor records ───────────────────────────────────────
    from intelligence.corridor_engine.corridor_builder import (
        build_corridors, corridors_to_dataframe, corridors_to_geojson,
    )
    corridor_records = _timed(
        "12_corridor_building",
        lambda: build_corridors(candidates),
        timings, errors,
    ) or []

    corridors_df = corridors_to_dataframe(corridor_records)
    result.corridors_df = corridors_df
    logger.info(f"Step 12: {len(corridor_records)} corridors built")

    if corridor_records:
        try:
            corridors_to_geojson(
                corridor_records,
                candidates,
                _GJ_DIR / "corridors.geojson",
            )
        except Exception as exc:
            logger.warning(f"Corridor GeoJSON export failed: {exc}")

    result.candidates_df = candidates

    # ── Step 13: Write outputs ────────────────────────────────────────────────
    _timed(
        "13_write_outputs",
        lambda: _write_outputs(result, candidates, contracts),
        timings, errors,
    )

    # ── Summary ───────────────────────────────────────────────────────────────
    total_s = sum(timings.values())
    logger.info("=" * 60)
    logger.info(f"Pipeline complete in {total_s:.1f}s")
    logger.info(f"  Candidates: {len(candidates)}")
    logger.info(f"  Corridors:  {len(corridor_records)}")
    logger.info(f"  Contracts:  {len(contracts)}")
    if errors:
        logger.warning(f"  Errors ({len(errors)}): {'; '.join(errors)}")
    logger.info("=" * 60)

    from storage.cache.cache_manager import CacheManager
    CacheManager.set_last_run_timestamp()

    result.summary.update({
        "total_candidates": len(candidates),
        "total_corridors":  len(corridor_records),
        "total_contracts":  len(contracts),
        "total_seconds":    round(total_s, 1),
        "error_count":      len(errors),
    })

    return result


def _write_outputs(
    result: PipelineResult,
    candidates: pd.DataFrame,
    contracts: pd.DataFrame,
) -> None:
    """Write CSVs and GeoJSON outputs to disk."""
    from storage.cache.cache_manager import CacheManager
    cm = CacheManager()

    if not candidates.empty:
        cm.save_candidates(candidates)
        try:
            cm.export_candidates_geojson(candidates)
        except Exception as exc:
            logger.warning(f"Candidates GeoJSON export failed: {exc}")

    if not result.corridors_df.empty:
        cm.save_corridors(result.corridors_df)
        try:
            cm.export_corridors_geojson(result.corridors_df)
        except Exception as exc:
            logger.warning(f"Corridors GeoJSON export failed: {exc}")

    if not contracts.empty:
        cm.save_contracts(contracts)

    # Optional PostGIS write
    try:
        from storage.postgis.writer import write_candidates, write_corridors, write_contracts
        from storage.postgis.schema import get_engine
        engine = get_engine()
        if engine is not None:
            if not candidates.empty:
                n = write_candidates(candidates, engine)
                logger.info(f"PostGIS: {n} candidate rows written")
            if not result.corridors_df.empty:
                write_corridors(result.corridors_df, engine)
            if not contracts.empty:
                write_contracts(contracts, engine)
    except Exception as exc:
        logger.debug(f"PostGIS write skipped: {exc}")
