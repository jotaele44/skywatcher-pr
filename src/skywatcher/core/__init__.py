"""Skywatcher Core: orchestration, runtime contracts, and shared static registries.

Core owns pieces that are shared across (or orchestrate) the SATIM, FPIM, and
CORRIM boundaries: readiness/ontology gating, normalization helpers, and
reference registries (known operators, airspace footprints, geometry math,
visual-detection constants). Core may be imported by any bucket; it must not
import from satim, fpim, corrim, or legacy. See
docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md.
"""
