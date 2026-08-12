"""DEPRECATED SHIM — consolidated into ``fr24.satim_engine``.

Historically ``fr24.satim_engine_core`` was a *slimmer duplicate* of the SATIM
engine that omitted the artifact-assessment / provider-profile / confidence-ledger
enrichment. That meant a run's output differed depending on which entrypoint an
operator invoked (`fr24.satim_engine` vs `fr24.satim_engine_core`) — a silent
correctness hazard.

This module is now a thin re-export of the single canonical implementation in
``fr24.satim_engine`` so both entrypoints produce identical, fully-enriched
output. **New code should import ``fr24.satim_engine`` directly.**

See docs/SATIM_ENGINE_PROTOCOL_INTERFACE.md and the audit note in
docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md.
"""

from __future__ import annotations

from fr24.satim_engine import (  # noqa: F401  (re-export: canonical engine API)
    SATIMEngineManifest,
    autodetect_inputs,
    build_arg_parser,
    build_provenance,
    degraded_layer,
    find_manifest,
    load_manifest,
    main,
    manifest_from_input,
    missing_layer,
    prepare_input_root,
    run_satim_engine,
    score_calibration_packet,
    validate_calibration_set,
)

__all__ = [
    "SATIMEngineManifest",
    "autodetect_inputs",
    "build_arg_parser",
    "build_provenance",
    "degraded_layer",
    "find_manifest",
    "load_manifest",
    "main",
    "manifest_from_input",
    "missing_layer",
    "prepare_input_root",
    "run_satim_engine",
    "score_calibration_packet",
    "validate_calibration_set",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
