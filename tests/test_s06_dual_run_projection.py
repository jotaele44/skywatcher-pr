from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from skywatcher.ai_imagery._dual_run_common import DualRunProjectionError
from skywatcher.ai_imagery.dual_run_projection import (
    S05_OUTPUT_IDS,
    build_candidate_lane_projection_input,
    build_legacy_lane_projection_input,
    project_s05_deterministic_outputs,
    write_dual_run_evidence_staging,
)
from skywatcher.ai_imagery.legacy_shadow_export import build_legacy_shadow_export
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


def _legacy_export() -> dict:
    envelope, collections = s05_package()
    return build_legacy_shadow_export(
        campaign=campaign(),
        trial_id="trial-01",
        created_at=CREATED_AT,
        execution_receipt=execution_receipt_ref("1"),
        engine={"engine_id": "fr24_vision_ingest", "engine_revision": SKYWATCHER_REVISION},
        normalized_legacy_records=legacy_normalized_records(),
        source_artifacts=campaign()["source_artifacts"],
        dispositions=dispositions(),
        deterministic_outputs=project_s05_deterministic_outputs(envelope, collections),
        model_fields=legacy_model_fields(),
        historical_artifacts=[
            {
                "logical_name": "legacy_csv",
                "sha256": "7" * 64,
                "bytes": 123,
                "media_type": "text/csv",
                "relative_path": "legacy/output.csv",
            }
        ],
    )


def _candidate() -> dict:
    envelope, collections = s05_package()
    return build_candidate_lane_projection_input(
        campaign=campaign(),
        trial_id="trial-01",
        s05_envelope=envelope,
        s05_collections=collections,
        execution_receipt=execution_receipt_ref("2"),
        h06_job_record_id="bounded-producer-job-record-sha256-" + "8" * 64,
        h07_admission_receipt_id="producer-package-admission-sha256-" + "9" * 64,
        created_at=CREATED_AT,
    )


def test_s05_package_projects_exact_output_set_and_preserves_provenance() -> None:
    envelope, collections = s05_package()
    lane = _candidate()
    assert {item["output_id"] for item in lane["deterministic_outputs"]} == S05_OUTPUT_IDS
    assert lane["output_accounting"] == {"required": 8, "produced": 8, "failed": 0}
    assert lane["input_accounting"] == {"inputs": 3, "processed": 2, "excluded": 1, "failed": 0}
    field = lane["model_fields"][0]
    assert field["value"] == "N999ZY"
    assert field["provenance"]["provider_id"] == "legacy-provider"
    assert field["provenance"]["source_sha256"] == "a" * 64
    assert lane["producer_package_sha256"] == envelope["normalized_digest"]
    assert collections["model_field_provenance"][0]["field_key"] == field["field_key"]


def test_candidate_requires_h06_h07_and_exact_source_pin_binding() -> None:
    envelope, collections = s05_package()
    for h06, h07 in (("", "h07"), ("h06", "")):
        with pytest.raises(DualRunProjectionError, match="H06 and H07"):
            build_candidate_lane_projection_input(
                campaign=campaign(),
                trial_id="trial-01",
                s05_envelope=envelope,
                s05_collections=collections,
                execution_receipt=execution_receipt_ref("2"),
                h06_job_record_id=h06,
                h07_admission_receipt_id=h07,
                created_at=CREATED_AT,
            )
    drifted = deepcopy(envelope)
    drifted["producer_revision"] = "f" * 40
    with pytest.raises(DualRunProjectionError, match="revision drift"):
        build_candidate_lane_projection_input(
            campaign=campaign(),
            trial_id="trial-01",
            s05_envelope=drifted,
            s05_collections=collections,
            execution_receipt=execution_receipt_ref("2"),
            h06_job_record_id="h06",
            h07_admission_receipt_id="h07",
            created_at=CREATED_AT,
        )
    drifted_campaign = campaign()
    drifted_campaign["pins"]["model_revision"] = "changed"
    from skywatcher.ai_imagery._dual_run_common import compute_campaign_id, compute_pins_sha256

    drifted_campaign["pins_sha256"] = compute_pins_sha256(drifted_campaign)
    drifted_campaign["campaign_id"] = compute_campaign_id(drifted_campaign)
    with pytest.raises(DualRunProjectionError, match="model_revision drift"):
        build_candidate_lane_projection_input(
            campaign=drifted_campaign,
            trial_id="trial-01",
            s05_envelope=envelope,
            s05_collections=collections,
            execution_receipt=execution_receipt_ref("2"),
            h06_job_record_id="h06",
            h07_admission_receipt_id="h07",
            created_at=CREATED_AT,
        )


def test_missing_s05_provenance_is_denied_without_invention() -> None:
    envelope, collections = s05_package()
    for key in (
        "model_run_receipt_id",
        "prompt_template_hash",
        "policy_version",
        "source_sha256",
    ):
        broken = deepcopy(collections)
        del broken["model_field_provenance"][0][key]
        from skywatcher.ai_imagery._dual_run_common import sha256_json

        envelope_broken = deepcopy(envelope)
        digest_payload = {
            "schema_version": "skywatcher_producer_package.v2",
            "producer_revision": envelope_broken["producer_revision"],
            "collections": broken,
            "accounting": envelope_broken["accounting"],
        }
        envelope_broken["normalized_digest"] = sha256_json(digest_payload)
        with pytest.raises(DualRunProjectionError, match="provenance"):
            build_candidate_lane_projection_input(
                campaign=campaign(),
                trial_id="trial-01",
                s05_envelope=envelope_broken,
                s05_collections=broken,
                execution_receipt=execution_receipt_ref("2"),
                h06_job_record_id="h06",
                h07_admission_receipt_id="h07",
                created_at=CREATED_AT,
            )


def test_legacy_and_candidate_outputs_validate_against_exact_thehub_h08_schema() -> None:
    schema_path = Path(__file__).resolve().parent / "fixtures" / "thehub_h08" / "dual_run_lane_evidence.v1.schema.json"
    campaign_schema_path = Path(__file__).resolve().parent / "fixtures" / "thehub_h08" / "dual_run_campaign_manifest.v1.schema.json"
    lane_schema = json.loads(schema_path.read_text(encoding="utf-8"))
    campaign_schema = json.loads(campaign_schema_path.read_text(encoding="utf-8"))
    assert hashlib.sha256(schema_path.read_bytes()).hexdigest() == "d9b75bfc2a9867da088d10ffb3e4538313f88417c65661de9f3813d1525a919b"
    assert hashlib.sha256(campaign_schema_path.read_bytes()).hexdigest() == "f97918e9742b0d815824c93817350c4bcdc5d6e68e14e749b60e24542c899e64"
    Draft202012Validator.check_schema(lane_schema)
    Draft202012Validator.check_schema(campaign_schema)
    validator = Draft202012Validator(lane_schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
    legacy = build_legacy_lane_projection_input(
        campaign=campaign(),
        trial_id="trial-01",
        legacy_shadow_export=_legacy_export(),
        execution_receipt=execution_receipt_ref("1"),
        created_at=CREATED_AT,
    )
    validator.validate(legacy)
    validator.validate(_candidate())
    Draft202012Validator(campaign_schema, format_checker=Draft202012Validator.FORMAT_CHECKER).validate(campaign())


def test_staging_layout_is_reproducible_and_contains_only_relative_paths(tmp_path: Path) -> None:
    envelope, collections = s05_package()
    legacy_export = _legacy_export()
    legacy_lane = build_legacy_lane_projection_input(
        campaign=campaign(),
        trial_id="trial-01",
        legacy_shadow_export=legacy_export,
        execution_receipt=execution_receipt_ref("1"),
        created_at=CREATED_AT,
    )
    candidate_lane = _candidate()
    policy = {
        "schema_version": "model_field_equivalence_policy.v1",
        "policy_id": campaign()["pins"]["equivalence_policy_id"],
        "rules": [],
        "created_at": CREATED_AT,
    }
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first = write_dual_run_evidence_staging(
        root=first_root,
        campaign=campaign(),
        equivalence_policy=policy,
        trial_id="trial-01",
        legacy_execution_receipt={"receipt": {"run_id": "1" * 32}, "signature": {"payload_sha256": "a" * 64}},
        legacy_shadow_export=legacy_export,
        legacy_lane=legacy_lane,
        candidate_execution_receipt={"receipt": {"run_id": "2" * 32}, "signature": {"payload_sha256": "b" * 64}},
        s05_envelope=envelope,
        s05_collections=collections,
        candidate_lane=candidate_lane,
    )
    second = write_dual_run_evidence_staging(
        root=second_root,
        campaign=campaign(),
        equivalence_policy=policy,
        trial_id="trial-01",
        legacy_execution_receipt={"receipt": {"run_id": "1" * 32}, "signature": {"payload_sha256": "a" * 64}},
        legacy_shadow_export=legacy_export,
        legacy_lane=legacy_lane,
        candidate_execution_receipt={"receipt": {"run_id": "2" * 32}, "signature": {"payload_sha256": "b" * 64}},
        s05_envelope=envelope,
        s05_collections=collections,
        candidate_lane=candidate_lane,
    )
    assert first == second
    first_files = {path.relative_to(first_root).as_posix(): path.read_bytes() for path in first_root.rglob("*") if path.is_file()}
    second_files = {path.relative_to(second_root).as_posix(): path.read_bytes() for path in second_root.rglob("*") if path.is_file()}
    assert first_files == second_files
    assert all(not path.startswith("/") and ".." not in Path(path).parts for path in first_files)
    assert "SHA256SUMS" in first_files


def test_static_source_contains_no_execution_or_runtime_surfaces() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "skywatcher" / "ai_imagery"
    combined = "\n".join(
        (root / name).read_text(encoding="utf-8").lower()
        for name in ("_dual_run_common.py", "legacy_shadow_export.py", "dual_run_projection.py")
    )
    forbidden = (
        "import requests",
        "import urllib",
        "import socket",
        "import anthropic",
        "import openai",
        "import sqlite3",
        "subprocess",
        "docker",
        "kubernetes",
        "database_url",
        "certify(",
        "promote_snapshot",
        "answer_query",
    )
    for token in forbidden:
        assert token not in combined
