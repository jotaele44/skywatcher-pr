"""Provider-neutral, offline ADR 0006 domain preparation utilities."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, ValidationError


def _validate_contract(
    record: Mapping[str, Any], relative_path: str, label: str
) -> dict[str, Any]:
    path = Path(__file__).resolve().parents[3] / relative_path
    try:
        schema = json.loads(path.read_bytes())
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(
            schema, format_checker=Draft202012Validator.FORMAT_CHECKER
        ).validate(record)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        from .dual_run_admission import DualRunAdmissionError

        raise DualRunAdmissionError(
            f"{label} does not match the exact pinned schema"
        ) from exc
    return dict(record)


from .dual_run_admission import (  # noqa: E402
    DualRunAdmissionError,
    ReceiptVerificationResolver,
    compute_s06_trial_admission,
    observe_s06_package,
    record_trial_admission_receipt,
)
from .dual_run_handoff import (  # noqa: E402
    build_h08_operator_handoff,
    compute_handoff_request_sha256,
    compute_operator_authorization_id,
    compute_rollback_evidence_id,
    validate_operator_authorization,
)
from .dual_run_projection import (  # noqa: E402
    S05_FILE_MAP,
    S05_OUTPUT_IDS,
    build_candidate_lane_projection_input,
    build_legacy_lane_projection_input,
    compute_lane_evidence_id,
    project_s05_deterministic_outputs,
    project_s05_model_fields,
    write_dual_run_evidence_staging,
)
from .legacy_shadow_export import (  # noqa: E402
    build_legacy_shadow_export,
    canonical_legacy_shadow_export_bytes,
    compute_legacy_shadow_export_id,
    normalize_legacy_csv_checkpoint_and_logs,
)

__all__ = [
    "DualRunAdmissionError",
    "ReceiptVerificationResolver",
    "S05_FILE_MAP",
    "S05_OUTPUT_IDS",
    "build_candidate_lane_projection_input",
    "build_h08_operator_handoff",
    "build_legacy_lane_projection_input",
    "build_legacy_shadow_export",
    "canonical_legacy_shadow_export_bytes",
    "compute_handoff_request_sha256",
    "compute_lane_evidence_id",
    "compute_legacy_shadow_export_id",
    "compute_operator_authorization_id",
    "compute_rollback_evidence_id",
    "compute_s06_trial_admission",
    "normalize_legacy_csv_checkpoint_and_logs",
    "observe_s06_package",
    "project_s05_deterministic_outputs",
    "project_s05_model_fields",
    "record_trial_admission_receipt",
    "validate_operator_authorization",
    "write_dual_run_evidence_staging",
]
