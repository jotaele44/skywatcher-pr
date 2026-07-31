from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from skywatcher.ai_imagery._dual_run_common import DualRunProjectionError
from skywatcher.ai_imagery.dual_run_projection import project_s05_deterministic_outputs
from skywatcher.ai_imagery.legacy_shadow_export import (
    build_legacy_shadow_export,
    canonical_legacy_shadow_export_bytes,
    normalize_legacy_csv_checkpoint_and_logs,
)
from s06_support import (
    CREATED_AT,
    SKYWATCHER_REVISION,
    campaign,
    dispositions,
    execution_receipt_ref,
    legacy_model_fields,
    legacy_normalized_records,
    s05_package,
)


def _export() -> dict:
    envelope, collections = s05_package()
    outputs = project_s05_deterministic_outputs(envelope, collections)
    return build_legacy_shadow_export(
        campaign=campaign(),
        trial_id="trial-01",
        created_at=CREATED_AT,
        execution_receipt=execution_receipt_ref("1"),
        engine={"engine_id": "fr24_vision_ingest", "engine_revision": SKYWATCHER_REVISION},
        normalized_legacy_records=legacy_normalized_records(),
        source_artifacts=campaign()["source_artifacts"],
        dispositions=dispositions(),
        deterministic_outputs=outputs,
        model_fields=legacy_model_fields(),
        historical_artifacts=[
            {
                "logical_name": "legacy_csv",
                "sha256": "7" * 64,
                "bytes": 123,
                "media_type": "text/csv",
                "relative_path": "legacy/output.csv",
            },
            {
                "logical_name": "legacy_checkpoint",
                "sha256": "8" * 64,
                "bytes": 32,
                "media_type": "application/json",
                "relative_path": "legacy/checkpoint.json",
            },
        ],
    )


def test_legacy_export_identity_is_deterministic_and_order_independent() -> None:
    first = _export()
    # Campaign identity itself is order-sensitive; collection normalization is tested
    # within one fixed campaign identity.
    rows = legacy_normalized_records()
    normalized = normalize_legacy_csv_checkpoint_and_logs(
        csv_rows=list(reversed(rows["csv_rows"])),
        checkpoint_entries=list(reversed(rows["checkpoint_entries"])),
        log_records=list(reversed(rows["log_records"])),
    )
    envelope, collections = s05_package()
    second = build_legacy_shadow_export(
        campaign=campaign(),
        trial_id="trial-01",
        created_at=CREATED_AT,
        execution_receipt=execution_receipt_ref("1"),
        engine={"engine_id": "fr24_vision_ingest", "engine_revision": SKYWATCHER_REVISION},
        normalized_legacy_records=normalized,
        source_artifacts=list(reversed(campaign()["source_artifacts"])),
        dispositions=list(reversed(dispositions())),
        deterministic_outputs=list(reversed(project_s05_deterministic_outputs(envelope, collections))),
        model_fields=list(reversed(legacy_model_fields())),
        historical_artifacts=list(reversed(_export()["historical_artifacts"])),
    )
    assert first == second
    assert canonical_legacy_shadow_export_bytes(first) == canonical_legacy_shadow_export_bytes(second)


def test_legacy_csv_fields_are_preserved_without_relabeling() -> None:
    normalized = normalize_legacy_csv_checkpoint_and_logs(
        csv_rows=legacy_normalized_records()["csv_rows"],
        checkpoint_entries=legacy_normalized_records()["checkpoint_entries"],
        log_records=legacy_normalized_records()["log_records"],
    )
    row = normalized["csv_rows"][0]
    assert row["registration"] == "N999ZY"
    assert row["image_path"] == "inputs/a.heic"
    combined = repr(normalized).lower()
    assert "provider-neutral" not in combined
    assert "ocr" not in combined


def test_missing_model_prompt_policy_or_source_provenance_is_denied() -> None:
    for key in (
        "model_run_receipt_id",
        "source_artifact_id",
        "source_sha256",
        "provider_id",
        "model_id",
        "model_revision",
        "prompt_template_hash",
        "policy_version",
        "access_context_hash",
        "extraction_schema_version",
    ):
        fields = legacy_model_fields()
        del fields[0]["provenance"][key]
        with pytest.raises(DualRunProjectionError, match="provenance"):
            build_legacy_shadow_export(
                campaign=campaign(),
                trial_id="trial-01",
                created_at=CREATED_AT,
                execution_receipt=execution_receipt_ref("1"),
                engine={"engine_id": "fr24_vision_ingest", "engine_revision": SKYWATCHER_REVISION},
                normalized_legacy_records=legacy_normalized_records(),
                source_artifacts=campaign()["source_artifacts"],
                dispositions=dispositions(),
                deterministic_outputs=_export()["deterministic_outputs"],
                model_fields=fields,
                historical_artifacts=_export()["historical_artifacts"],
            )


def test_absolute_paths_traversal_and_secret_values_are_denied() -> None:
    for bad_path in ("/tmp/output.csv", "../output.csv", "C:/output.csv"):
        history = deepcopy(_export()["historical_artifacts"])
        history[0]["relative_path"] = bad_path
        with pytest.raises(DualRunProjectionError, match="path|root|Windows"):
            build_legacy_shadow_export(
                campaign=campaign(),
                trial_id="trial-01",
                created_at=CREATED_AT,
                execution_receipt=execution_receipt_ref("1"),
                engine={"engine_id": "fr24_vision_ingest", "engine_revision": SKYWATCHER_REVISION},
                normalized_legacy_records=legacy_normalized_records(),
                source_artifacts=campaign()["source_artifacts"],
                dispositions=dispositions(),
                deterministic_outputs=_export()["deterministic_outputs"],
                model_fields=legacy_model_fields(),
                historical_artifacts=history,
            )
    records = legacy_normalized_records()
    records["log_records"][0]["message"] = "ANTHROPIC_API_KEY=not-allowed"
    with pytest.raises(DualRunProjectionError, match="secret-shaped"):
        build_legacy_shadow_export(
            campaign=campaign(),
            trial_id="trial-01",
            created_at=CREATED_AT,
            execution_receipt=execution_receipt_ref("1"),
            engine={"engine_id": "fr24_vision_ingest", "engine_revision": SKYWATCHER_REVISION},
            normalized_legacy_records=records,
            source_artifacts=campaign()["source_artifacts"],
            dispositions=dispositions(),
            deterministic_outputs=_export()["deterministic_outputs"],
            model_fields=legacy_model_fields(),
            historical_artifacts=_export()["historical_artifacts"],
        )


def test_incomplete_or_overlapping_accounting_is_denied() -> None:
    incomplete = dispositions()[:-1]
    with pytest.raises(DualRunProjectionError, match="exact source set"):
        build_legacy_shadow_export(
            campaign=campaign(),
            trial_id="trial-01",
            created_at=CREATED_AT,
            execution_receipt=execution_receipt_ref("1"),
            engine={"engine_id": "fr24_vision_ingest", "engine_revision": SKYWATCHER_REVISION},
            normalized_legacy_records=legacy_normalized_records(),
            source_artifacts=campaign()["source_artifacts"],
            dispositions=incomplete,
            deterministic_outputs=_export()["deterministic_outputs"],
            model_fields=legacy_model_fields(),
            historical_artifacts=_export()["historical_artifacts"],
        )
    overlapping = dispositions() + [deepcopy(dispositions()[0])]
    with pytest.raises(DualRunProjectionError, match="duplicate"):
        build_legacy_shadow_export(
            campaign=campaign(),
            trial_id="trial-01",
            created_at=CREATED_AT,
            execution_receipt=execution_receipt_ref("1"),
            engine={"engine_id": "fr24_vision_ingest", "engine_revision": SKYWATCHER_REVISION},
            normalized_legacy_records=legacy_normalized_records(),
            source_artifacts=campaign()["source_artifacts"],
            dispositions=overlapping,
            deterministic_outputs=_export()["deterministic_outputs"],
            model_fields=legacy_model_fields(),
            historical_artifacts=_export()["historical_artifacts"],
        )


def test_legacy_export_retains_engine_receipt_and_nonproduction_flags() -> None:
    export = _export()
    assert export["engine"] == {
        "engine_id": "fr24_vision_ingest",
        "engine_revision": SKYWATCHER_REVISION,
    }
    assert export["execution_receipt"] == {
        "run_id": "1" * 32,
        "receipt_sha256": "1" * 64,
    }
    assert export["production_mutation_allowed"] is False
    assert export["certified_state_created"] is False
    assert export["active_snapshot_promoted"] is False
    assert export["retirement_authorized"] is False


def test_unverified_execution_receipt_reference_is_denied() -> None:
    receipt = execution_receipt_ref("1")
    receipt["signature_verified"] = False
    with pytest.raises(DualRunProjectionError, match="verified upstream"):
        build_legacy_shadow_export(
            campaign=campaign(),
            trial_id="trial-01",
            created_at=CREATED_AT,
            execution_receipt=receipt,
            engine={
                "engine_id": "fr24_vision_ingest",
                "engine_revision": SKYWATCHER_REVISION,
            },
            normalized_legacy_records=legacy_normalized_records(),
            source_artifacts=campaign()["source_artifacts"],
            dispositions=dispositions(),
            deterministic_outputs=_export()["deterministic_outputs"],
            model_fields=legacy_model_fields(),
            historical_artifacts=_export()["historical_artifacts"],
        )


def test_legacy_schema_is_frozen_and_valid() -> None:
    schema_path = Path(__file__).resolve().parents[1] / "schemas" / "ai_imagery" / "legacy_shadow_export.v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(schema_path.read_bytes()).hexdigest()
    assert digest == "ca8c878d2263b8e685e7ee58daeb0384dc2e92fa8149230929156592332683f3"
    freeze = (schema_path.parent / "FROZEN.sha256").read_text(encoding="utf-8")
    assert f"{digest}  legacy_shadow_export.v1.schema.json" in freeze
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(
        schema, format_checker=Draft202012Validator.FORMAT_CHECKER
    ).validate(_export())
