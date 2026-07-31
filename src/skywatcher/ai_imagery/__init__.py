"""Provider-neutral, offline ADR 0006 domain preparation utilities."""

from .dual_run_projection import (
    S05_FILE_MAP,
    S05_OUTPUT_IDS,
    build_candidate_lane_projection_input,
    build_legacy_lane_projection_input,
    compute_lane_evidence_id,
    project_s05_deterministic_outputs,
    project_s05_model_fields,
    write_dual_run_evidence_staging,
)
from .legacy_shadow_export import (
    build_legacy_shadow_export,
    canonical_legacy_shadow_export_bytes,
    compute_legacy_shadow_export_id,
    normalize_legacy_csv_checkpoint_and_logs,
)

__all__ = [
    "S05_FILE_MAP",
    "S05_OUTPUT_IDS",
    "build_candidate_lane_projection_input",
    "build_legacy_lane_projection_input",
    "build_legacy_shadow_export",
    "canonical_legacy_shadow_export_bytes",
    "compute_lane_evidence_id",
    "compute_legacy_shadow_export_id",
    "normalize_legacy_csv_checkpoint_and_logs",
    "project_s05_deterministic_outputs",
    "project_s05_model_fields",
    "write_dual_run_evidence_staging",
]
