from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

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
from skywatcher.ai_imagery._dual_run_common import (
    DualRunProjectionError,
    compute_campaign_id,
    compute_pins_sha256,
    sha256_json,
)
from skywatcher.ai_imagery.dual_run_projection import (
    S05_OUTPUT_IDS,
    build_candidate_lane_projection_input,
    build_legacy_lane_projection_input,
    compute_lane_evidence_id,
    project_s05_deterministic_outputs,
    write_dual_run_evidence_staging,
)
from skywatcher.ai_imagery.legacy_shadow_export import (
    build_legacy_shadow_export,
    compute_legacy_shadow_export_id,
)


def _full_execution_receipt(seed: str) -> dict[str, Any]:
    body = {
        "schema_version": "prii_execution_receipt_v1",
        "run_id": seed * 32,
        "operation_id": f"s06-test-{seed}",
        "status": "succeeded",
    }
    return {
        "receipt": body,
        "signature": {
            "key_id": "s06-test-key",
            "algorithm": "Ed25519",
            "value": "dGVzdC1zaWduYXR1cmU=",
            "payload_sha256": sha256_json(body),
        },
    }


def _receipt_reference(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": document["receipt"]["run_id"],
        "receipt_sha256": document["signature"]["payload_sha256"],
        "signature_verified": True,
    }


def _equivalence_policy() -> dict[str, Any]:
    policy = {
        "schema_version": "model_field_equivalence_policy.v1",
        "policy_id": "",
        "version": "1.0.0",
        "rules": [],
        "created_at": CREATED_AT,
    }
    payload = dict(policy)
    payload.pop("policy_id")
    policy["policy_id"] = "model-equivalence-policy-sha256-" + sha256_json(payload)
    return policy


def _campaign_with_policy(policy: dict[str, Any]) -> dict[str, Any]:
    record = campaign()
    record["pins"]["equivalence_policy_id"] = policy["policy_id"]
    record["pins"]["equivalence_policy_sha256"] = policy["policy_id"].rsplit(
        "-", 1
    )[-1]
    record["pins_sha256"] = compute_pins_sha256(record)
    record["campaign_id"] = compute_campaign_id(record)
    return record


def _legacy_export(
    *,
    campaign_record: dict[str, Any] | None = None,
    receipt_reference: dict[str, Any] | None = None,
) -> dict[str, Any]:
    envelope, collections = s05_package()
    selected_campaign = campaign_record or campaign()
    selected_receipt = receipt_reference or execution_receipt_ref("1")
    return build_legacy_shadow_export(
        campaign=selected_campaign,
        trial_id="trial-01",
        created_at=CREATED_AT,
        execution_receipt=selected_receipt,
        engine={
            "engine_id": "fr24_vision_ingest",
            "engine_revision": SKYWATCHER_REVISION,
        },
        normalized_legacy_records=legacy_normalized_records(),
        source_artifacts=selected_campaign["source_artifacts"],
        dispositions=dispositions(),
        deterministic_outputs=project_s05_deterministic_outputs(
            envelope, collections
        ),
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


def _candidate(
    *,
    campaign_record: dict[str, Any] | None = None,
    receipt_reference: dict[str, Any] | None = None,
    envelope: dict[str, Any] | None = None,
    collections: dict[str, Any] | None = None,
) -> dict[str, Any]:
    package_envelope, package_collections = s05_package()
    return build_candidate_lane_projection_input(
        campaign=campaign_record or campaign(),
        trial_id="trial-01",
        s05_envelope=envelope or package_envelope,
        s05_collections=collections or package_collections,
        execution_receipt=receipt_reference or execution_receipt_ref("2"),
        h06_job_record_id="bounded-producer-job-record-sha256-" + "8" * 64,
        h07_admission_receipt_id="producer-package-admission-sha256-" + "9" * 64,
        created_at=CREATED_AT,
    )


def _staging_bundle() -> dict[str, Any]:
    policy = _equivalence_policy()
    campaign_record = _campaign_with_policy(policy)
    legacy_full_receipt = _full_execution_receipt("1")
    candidate_full_receipt = _full_execution_receipt("2")
    legacy_reference = _receipt_reference(legacy_full_receipt)
    candidate_reference = _receipt_reference(candidate_full_receipt)
    envelope, collections = s05_package()
    legacy_export = _legacy_export(
        campaign_record=campaign_record,
        receipt_reference=legacy_reference,
    )
    legacy_lane = build_legacy_lane_projection_input(
        campaign=campaign_record,
        trial_id="trial-01",
        legacy_shadow_export=legacy_export,
        execution_receipt=legacy_reference,
        created_at=CREATED_AT,
    )
    candidate_lane = _candidate(
        campaign_record=campaign_record,
        receipt_reference=candidate_reference,
        envelope=envelope,
        collections=collections,
    )
    return {
        "campaign": campaign_record,
        "equivalence_policy": policy,
        "trial_id": "trial-01",
        "legacy_execution_receipt": legacy_full_receipt,
        "legacy_shadow_export": legacy_export,
        "legacy_lane": legacy_lane,
        "candidate_execution_receipt": candidate_full_receipt,
        "s05_envelope": envelope,
        "s05_collections": collections,
        "candidate_lane": candidate_lane,
    }


def _stage(root: Path, bundle: dict[str, Any]) -> dict[str, str]:
    return write_dual_run_evidence_staging(root=root, **bundle)


def test_s05_package_projects_exact_output_set_and_preserves_provenance() -> None:
    envelope, collections = s05_package()
    lane = _candidate()
    assert {
        item["output_id"] for item in lane["deterministic_outputs"]
    } == S05_OUTPUT_IDS
    assert lane["output_accounting"] == {
        "required": 8,
        "produced": 8,
        "failed": 0,
    }
    assert lane["input_accounting"] == {
        "inputs": 3,
        "processed": 2,
        "excluded": 1,
        "failed": 0,
    }
    field = lane["model_fields"][0]
    assert field["value"] == "N999ZY"
    assert field["provenance"]["provider_id"] == "legacy-provider"
    assert field["provenance"]["source_sha256"] == "a" * 64
    assert lane["producer_package_sha256"] == envelope["normalized_digest"]
    assert (
        collections["model_field_provenance"][0]["field_key"]
        == field["field_key"]
    )


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
    schema_path = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "thehub_h08"
        / "dual_run_lane_evidence.v1.schema.json"
    )
    campaign_schema_path = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "thehub_h08"
        / "dual_run_campaign_manifest.v1.schema.json"
    )
    lane_schema = json.loads(schema_path.read_text(encoding="utf-8"))
    campaign_schema = json.loads(campaign_schema_path.read_text(encoding="utf-8"))
    assert (
        hashlib.sha256(schema_path.read_bytes()).hexdigest()
        == "d9b75bfc2a9867da088d10ffb3e4538313f88417c65661de9f3813d1525a919b"
    )
    assert (
        hashlib.sha256(campaign_schema_path.read_bytes()).hexdigest()
        == "f97918e9742b0d815824c93817350c4bcdc5d6e68e14e749b60e24542c899e64"
    )
    Draft202012Validator.check_schema(lane_schema)
    Draft202012Validator.check_schema(campaign_schema)
    validator = Draft202012Validator(
        lane_schema, format_checker=Draft202012Validator.FORMAT_CHECKER
    )
    legacy = build_legacy_lane_projection_input(
        campaign=campaign(),
        trial_id="trial-01",
        legacy_shadow_export=_legacy_export(),
        execution_receipt=execution_receipt_ref("1"),
        created_at=CREATED_AT,
    )
    validator.validate(legacy)
    validator.validate(_candidate())
    Draft202012Validator(
        campaign_schema, format_checker=Draft202012Validator.FORMAT_CHECKER
    ).validate(campaign())


def test_staging_layout_is_reproducible_and_contains_only_relative_paths(
    tmp_path: Path,
) -> None:
    bundle = _staging_bundle()
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first = _stage(first_root, bundle)
    second = _stage(second_root, deepcopy(bundle))
    assert first == second
    first_files = {
        path.relative_to(first_root).as_posix(): path.read_bytes()
        for path in first_root.rglob("*")
        if path.is_file()
    }
    second_files = {
        path.relative_to(second_root).as_posix(): path.read_bytes()
        for path in second_root.rglob("*")
        if path.is_file()
    }
    assert first_files == second_files
    assert all(
        not path.startswith("/") and ".." not in Path(path).parts
        for path in first_files
    )
    assert "SHA256SUMS" in first_files


@pytest.mark.parametrize(
    "bad_trial_id",
    ("../../outside", "/absolute", "nested/trial", "C:/trial", ".."),
)
def test_trial_id_escape_and_multicomponent_values_are_denied_before_write(
    tmp_path: Path, bad_trial_id: str
) -> None:
    bundle = _staging_bundle()
    bundle["trial_id"] = bad_trial_id
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    with pytest.raises(DualRunProjectionError, match="trial_id|path component"):
        _stage(root, bundle)
    assert not root.exists()
    assert not outside.exists()


@pytest.mark.parametrize("field", ("key_id", "algorithm", "value", "payload_sha256"))
def test_missing_signature_material_is_denied(tmp_path: Path, field: str) -> None:
    bundle = _staging_bundle()
    del bundle["legacy_execution_receipt"]["signature"][field]
    with pytest.raises(DualRunProjectionError, match="signature material"):
        _stage(tmp_path / "stage", bundle)


def test_full_receipt_run_id_drift_is_denied(tmp_path: Path) -> None:
    bundle = _staging_bundle()
    bundle["legacy_execution_receipt"]["receipt"]["run_id"] = "f" * 32
    with pytest.raises(DualRunProjectionError, match="run_id"):
        _stage(tmp_path / "stage", bundle)


def test_full_receipt_digest_drift_is_denied(tmp_path: Path) -> None:
    bundle = _staging_bundle()
    bundle["legacy_execution_receipt"]["signature"]["payload_sha256"] = "f" * 64
    with pytest.raises(DualRunProjectionError, match="SHA-256"):
        _stage(tmp_path / "stage", bundle)


def test_swapped_legacy_and_candidate_receipts_are_denied(tmp_path: Path) -> None:
    bundle = _staging_bundle()
    bundle["legacy_execution_receipt"], bundle["candidate_execution_receipt"] = (
        bundle["candidate_execution_receipt"],
        bundle["legacy_execution_receipt"],
    )
    with pytest.raises(DualRunProjectionError, match="run_id"):
        _stage(tmp_path / "stage", bundle)


def test_cross_campaign_lane_substitution_is_denied(tmp_path: Path) -> None:
    bundle = _staging_bundle()
    candidate = deepcopy(bundle["candidate_lane"])
    candidate["campaign_id"] = "dual-run-campaign-sha256-" + "f" * 64
    candidate["lane_evidence_id"] = compute_lane_evidence_id(candidate)
    bundle["candidate_lane"] = candidate
    with pytest.raises(DualRunProjectionError, match="candidate lane"):
        _stage(tmp_path / "stage", bundle)


def test_legacy_export_substitution_is_denied(tmp_path: Path) -> None:
    bundle = _staging_bundle()
    replacement = deepcopy(bundle["legacy_shadow_export"])
    replacement["created_at"] = "2026-08-01T00:00:00Z"
    replacement["legacy_shadow_export_id"] = compute_legacy_shadow_export_id(
        replacement
    )
    bundle["legacy_shadow_export"] = replacement
    with pytest.raises(DualRunProjectionError, match="legacy lane"):
        _stage(tmp_path / "stage", bundle)


def test_s05_package_substitution_is_denied(tmp_path: Path) -> None:
    bundle = _staging_bundle()
    bundle["s05_envelope"]["created_at"] = "2026-08-01T00:00:00Z"
    with pytest.raises(DualRunProjectionError, match="candidate lane"):
        _stage(tmp_path / "stage", bundle)


def test_equivalence_policy_substitution_is_denied(tmp_path: Path) -> None:
    bundle = _staging_bundle()
    bundle["equivalence_policy"]["rules"] = [
        {"field_key": "registration", "comparator": "EXACT_CANONICAL"}
    ]
    with pytest.raises(DualRunProjectionError, match="policy identity"):
        _stage(tmp_path / "stage", bundle)


def test_campaign_and_s05_collection_input_order_is_fully_independent(
    tmp_path: Path,
) -> None:
    canonical_bundle = _staging_bundle()
    permuted_bundle = deepcopy(canonical_bundle)
    for key in (
        "source_artifacts",
        "trials",
        "required_deterministic_outputs",
        "required_model_fields",
    ):
        permuted_bundle["campaign"][key].reverse()
    for records in permuted_bundle["s05_collections"].values():
        records.reverse()

    assert (
        compute_campaign_id(permuted_bundle["campaign"])
        == canonical_bundle["campaign"]["campaign_id"]
    )
    canonical_root = tmp_path / "canonical"
    permuted_root = tmp_path / "permuted"
    assert _stage(canonical_root, canonical_bundle) == _stage(
        permuted_root, permuted_bundle
    )
    canonical_files = {
        path.relative_to(canonical_root).as_posix(): path.read_bytes()
        for path in canonical_root.rglob("*")
        if path.is_file()
    }
    permuted_files = {
        path.relative_to(permuted_root).as_posix(): path.read_bytes()
        for path in permuted_root.rglob("*")
        if path.is_file()
    }
    assert canonical_files == permuted_files


def test_static_source_contains_no_execution_or_runtime_surfaces() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "skywatcher" / "ai_imagery"
    combined = "\n".join(
        (root / name).read_text(encoding="utf-8").lower()
        for name in (
            "_dual_run_common.py",
            "legacy_shadow_export.py",
            "dual_run_projection.py",
        )
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
