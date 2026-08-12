"""Single source of truth for the Core / SATIM / FPIM / CORRIM module boundary.

Each bucket is a set of glob patterns (relative to the repo root) describing
which files belong to it. This is a *classification* manifest, not a physical
layout requirement — some files were moved to a new canonical package during
the module reorg (see docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md), others are
classified in place because they were already cohesive.

ALLOWED_IMPORTS encodes the layering rule enforced by
tests/test_module_boundaries.py:

    core   : importable by anyone; imports only stdlib/third-party.
    satim  : imports core + stdlib/third-party. MUST NOT import fpim or corrim.
    fpim   : imports core + stdlib/third-party. MUST NOT import satim or corrim.
    corrim : imports core + satim + fpim + stdlib/third-party. The ONLY bucket
             permitted to import from both satim and fpim.
    legacy : quarantine. Not importable by core/satim/fpim/corrim — only by its
             own backward-compat shim (aircraft_intelligence.py).

MODULE_IMPORT_EXCEPTIONS records narrow, explicit, intentional exceptions to
the bucket-level rule above, keyed by file path (relative to repo root). The
one exception today: skywatcher.core.readiness_engine reads SATIM's
calibration status report (fr24/calibration/readiness_adapter.py) to fold it
into Core's own readiness aggregation contract. This is a "consume a status
artifact for aggregation" relationship, not a "combine evidentiary outputs"
relationship — CORRIM's exclusive role remains combining SATIM's and FPIM's
*analytical* outputs (imagery findings + flight-path/POI evidence) for
correlation scoring. See the ADR's Rationale section for the full reasoning.
"""

from __future__ import annotations

MODULE_BOUNDARIES: dict[str, list[str]] = {
    "core": [
        "src/skywatcher/core/**/*.py",
        "src/skywatcher/registry/**/*.py",
    ],
    "satim": [
        "src/skywatcher/satim/**/*.py",
        "satim_calibration.py",
        "satim_cut_fill.py",
        "satim_fit.py",
        "satim_geometry.py",
        "satim_ground_truth.py",
        "satim_patchwork.py",
        "satim_render_diff.py",
        "satim_road_end.py",
        "satim_tile_seam_classifier.py",
        "fr24/calibration/**/*.py",
        "fr24/satim_engine.py",
        "fr24/satim_engine_core.py",
    ],
    "fpim": [
        "src/skywatcher/fpim/**/*.py",
        # Reclassified from an earlier "correlation" (CORRIM) assignment: this
        # module matches a flight-path point against a static POI/footprint
        # gazetteer (skywatcher.registry.airspace_footprints, Core) with no
        # SATIM imagery involved — that's FPIM's POI-tracing responsibility,
        # not a SATIM+FPIM combination. See docs/MODULE_SPEC_FPIM.md.
        "src/skywatcher/correlation/**/*.py",
        "fr24/route_extractor.py",
        "fr24/track_vectorizer.py",
        "fr24/flight_fusion.py",
        "fr24/wave_validator.py",
        "fr24/endpoint_matcher.py",
    ],
    "corrim": [
        "src/skywatcher/corrim/**/*.py",
        "src/skywatcher/fusion/**/*.py",
    ],
    # FR24 screenshot-ingest ownership package (repository-boundary correction:
    # FR24 screenshot processing is owned by skywatcher-pr). It consolidates the
    # OCR/telemetry/reconstruction/database responsibilities and therefore is the
    # top consumer of SATIM- and FPIM-classified fr24 helpers; it wraps existing
    # (unclassified) fr24/* implementation modules. See
    # docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md.
    "fr24_ingest": [
        "src/skywatcher/fr24/**/*.py",
    ],
    "legacy": [
        "src/skywatcher/legacy/**/*.py",
    ],
}

# tools/satim_engine/ and tools/satim_route_findings/ are SATIM-family
# standalone CLI packages (own pyproject.toml, own tests) but are excluded
# from the boundary walk: neither imports any code from this repo (only
# stdlib/pandas/pyyaml), so they cannot violate the boundary and including
# them would only add noise. See docs/MODULE_SPEC_SATIM.md.

ALLOWED_IMPORTS: dict[str, set[str]] = {
    "core": {"core"},
    "satim": {"core", "satim"},
    "fpim": {"core", "fpim"},
    "corrim": {"core", "satim", "fpim", "corrim"},
    # fr24_ingest may consume Core utilities plus the SATIM/FPIM fr24 helpers it
    # orchestrates (OCR + flight reconstruction). Like CORRIM it is an
    # integration tier, but for ingestion rather than correlation scoring.
    "fr24_ingest": {"core", "satim", "fpim", "fr24_ingest"},
    "legacy": {"core", "satim", "fpim", "corrim", "legacy"},
}

MODULE_IMPORT_EXCEPTIONS: dict[str, set[str]] = {
    "src/skywatcher/core/readiness_engine.py": {"satim"},
}

# Pre-reorg root-level and pipeline/ modules are now thin backward-compat
# shims that only re-export from their bucket's canonical new location (see
# each shim's own docstring). They carry no logic of their own, so they are
# excluded from MODULE_BOUNDARIES's file walk — but code that imports a shim
# is really depending on that shim's target bucket, so shim dotted-module
# names are mapped here to let tests/test_module_boundaries.py catch a
# cross-boundary import made *through* a shim, not just a direct one.
SHIM_MODULE_BUCKETS: dict[str, str] = {
    "prii_readiness_engine": "core",
    "pipeline.rlsm_ontology_gate": "core",
    "pipeline.normalize_locations": "core",
    "pipeline.normalize_missions": "core",
    "pipeline.normalize_operators": "core",
    "pipeline.db_utils": "core",
    "aircraft_intelligence": "fpim",
    "gis_intelligence": "corrim",
    "ilap_airspace_bridge": "corrim",
    "aasb_airspace_bridge": "corrim",
}
