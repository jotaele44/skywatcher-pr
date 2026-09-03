from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from s07_support import (
    NOW,
    Resolver,
    authorization,
    build_s06_package,
    campaign,
    compact,
    policy,
    rollback,
)
from skywatcher.ai_imagery._dual_run_common import (
    DualRunProjectionError,
    sha256_json,
)
from skywatcher.ai_imagery.dual_run_admission import (
    DualRunAdmissionError,
    compute_s06_trial_admission,
)
from skywatcher.ai_imagery.dual_run_handoff import (
    build_h08_operator_handoff,
    compute_rollback_evidence_id,
)


def _bundle(root: Path):
    camp, pol = campaign(), policy()
    roots: dict[str, Path] = {}
    admissions = []
    for trial_id in ("trial-1", "trial-2"):
        trial_root = root / trial_id
        build_s06_package(trial_root, camp, trial_id)
        roots[trial_id] = trial_root
        admissions.append(
            compute_s06_trial_admission(
                package_root=trial_root,
                expected_campaign=camp,
                trial_id=trial_id,
                receipt_verification_resolver=Resolver(),
                created_at=NOW,
            )
        )
    rb, rb_full = rollback(camp)
    auth = authorization(camp, pol, admissions, rb)
    return camp, pol, roots, admissions, rb, rb_full, auth


def _build(destination: Path, bundle, resolver: Resolver | None = None):
    camp, pol, roots, admissions, rb, rb_full, auth = bundle
    return build_h08_operator_handoff(
        destination_root=destination,
        campaign=camp,
        equivalence_policy=pol,
        trial_admissions=admissions,
        trial_package_roots=roots,
        rollback_evidence=rb,
        rollback_full_receipt=rb_full,
        rollback_verification_resolver=resolver or Resolver(),
        operator_authorization=auth,
        created_at=NOW,
    )


def _rebind_rollback(bundle: list[Any]) -> None:
    bundle[4]["rollback_evidence_id"] = compute_rollback_evidence_id(bundle[4])
    bundle[6] = authorization(bundle[0], bundle[1], bundle[3], bundle[4])


def _rebind_admission(admission: dict[str, Any]) -> None:
    body = dict(admission)
    body.pop("trial_admission_id")
    admission["trial_admission_id"] = "s07-trial-admission-sha256-" + sha256_json(body)


def _files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _schema(root: Path, name: str) -> dict[str, Any]:
    return json.loads((root / name).read_text(encoding="utf-8"))


def _pinned_h08_validate_dual_run_records(
    campaign_value: dict[str, Any],
    policy_value: dict[str, Any],
    lanes: list[dict[str, Any]],
    rollback_value: dict[str, Any],
    fixture_root: Path,
) -> None:
    checker = Draft202012Validator.FORMAT_CHECKER
    contracts = (
        (campaign_value, "dual_run_campaign_manifest.v1.schema.json"),
        (policy_value, "model_field_equivalence_policy.v1.schema.json"),
        (rollback_value, "rollback_drill_evidence.v1.schema.json"),
    )
    for value, name in contracts:
        Draft202012Validator(
            _schema(fixture_root, name), format_checker=checker
        ).validate(value)
    lane_schema = _schema(fixture_root, "dual_run_lane_evidence.v1.schema.json")
    pins = campaign_value["pins"]
    assert pins["equivalence_policy_id"] == policy_value["policy_id"]
    assert pins["equivalence_policy_sha256"] == policy_value["policy_id"].rsplit(
        "-", 1
    )[-1]
    expected_trials = {item["trial_id"] for item in campaign_value["trials"]}
    expected_inputs = len(campaign_value["source_artifacts"])
    expected_outputs = len(campaign_value["required_deterministic_outputs"])
    run_ids: set[str] = set()
    receipt_hashes: set[str] = set()
    trial_lanes: dict[str, set[str]] = {}
    for lane in lanes:
        Draft202012Validator(lane_schema, format_checker=checker).validate(lane)
        assert lane["campaign_id"] == campaign_value["campaign_id"]
        assert lane["source_set_sha256"] == campaign_value["source_set_sha256"]
        assert lane["pins_sha256"] == campaign_value["pins_sha256"]
        inputs = lane["input_accounting"]
        assert inputs["inputs"] == expected_inputs
        assert inputs["inputs"] == (
            inputs["processed"] + inputs["excluded"] + inputs["failed"]
        )
        outputs = lane["output_accounting"]
        assert outputs["required"] == expected_outputs
        assert outputs["required"] == outputs["produced"] + outputs["failed"]
        assert outputs["produced"] == len(lane["deterministic_outputs"])
        assert lane["schema_violations"] == 0
        assert lane["missing_required_provenance"] == 0
        receipt = lane["execution_receipt"]
        assert receipt["signature_verified"] is True
        assert receipt["run_id"] not in run_ids
        assert receipt["receipt_sha256"] not in receipt_hashes
        run_ids.add(receipt["run_id"])
        receipt_hashes.add(receipt["receipt_sha256"])
        trial_lanes.setdefault(lane["trial_id"], set()).add(lane["lane"])
        if lane["lane"] == "ADR0006_CANDIDATE":
            assert lane["h06_job_record_id"]
            assert lane["h07_admission_receipt_id"]
        else:
            assert lane["lane"] == "LEGACY_SHADOW"
            assert lane["legacy_shadow_export_id"]
    assert set(trial_lanes) == expected_trials
    assert all(
        kinds == {"LEGACY_SHADOW", "ADR0006_CANDIDATE"}
        for kinds in trial_lanes.values()
    )
    assert rollback_value["campaign_id"] == campaign_value["campaign_id"]
    assert not rollback_value["unexpected_writes"]
    assert rollback_value["checks"]
    assert all(value is True for value in rollback_value["checks"].values())
    rollback_receipt = rollback_value["execution_receipt"]
    assert rollback_receipt["signature_verified"] is True
    assert rollback_receipt["rollback_state"] == "succeeded"
    assert rollback_receipt["status"] in {"rolled_back", "succeeded"}


def test_determinism_exact_replay_and_changed_replay(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path / "inputs")
    first, second = tmp_path / "first", tmp_path / "second"
    manifest = _build(first, bundle)
    assert manifest == _build(second, bundle)
    assert _files(first) == _files(second)
    assert _build(first, bundle) == manifest
    changed = list(bundle)
    changed[6] = deepcopy(changed[6])
    changed[6]["reason"] = "changed"
    with pytest.raises(DualRunAdmissionError):
        _build(first, tuple(changed))


def test_exact_trial_set_is_required(tmp_path: Path) -> None:
    missing = list(_bundle(tmp_path / "missing-inputs"))
    missing[3] = missing[3][:1]
    with pytest.raises(DualRunAdmissionError, match="trial admission set"):
        _build(tmp_path / "missing", tuple(missing))
    extra = list(_bundle(tmp_path / "extra-inputs"))
    extra[2] = {**extra[2], "trial-extra": extra[2]["trial-1"]}
    with pytest.raises(DualRunAdmissionError, match="package root set"):
        _build(tmp_path / "extra", tuple(extra))


def test_policy_substitution_and_admission_policy_drift_are_denied(tmp_path: Path) -> None:
    substituted = list(_bundle(tmp_path / "substituted"))
    altered = deepcopy(substituted[1])
    altered["version"] = "2.0.0"
    body = dict(altered)
    body.pop("policy_id")
    altered["policy_id"] = "model-equivalence-policy-sha256-" + sha256_json(body)
    substituted[1] = altered
    substituted[6] = authorization(
        substituted[0], altered, substituted[3], substituted[4]
    )
    with pytest.raises(DualRunProjectionError, match="policy|campaign pin"):
        _build(tmp_path / "policy-substitution", tuple(substituted))

    drifted = list(_bundle(tmp_path / "drifted"))
    drifted[3] = deepcopy(drifted[3])
    drifted[3][0]["equivalence_policy_id"] = "model-equivalence-policy-sha256-" + "f" * 64
    drifted[3][0]["equivalence_policy_sha256"] = "f" * 64
    _rebind_admission(drifted[3][0])
    drifted[6] = authorization(drifted[0], drifted[1], drifted[3], drifted[4])
    with pytest.raises(DualRunAdmissionError, match="revalidated package|policy"):
        _build(tmp_path / "policy-drift", tuple(drifted))


@pytest.mark.parametrize("mutation", ("missing", "additional"))
def test_rollback_exact_pinned_schema_is_enforced(
    tmp_path: Path, mutation: str
) -> None:
    bundle = list(_bundle(tmp_path / mutation))
    bundle[4] = deepcopy(bundle[4])
    if mutation == "missing":
        del bundle[4]["logs"]
    else:
        bundle[4]["undeclared"] = True
    _rebind_rollback(bundle)
    with pytest.raises(DualRunAdmissionError, match="exact pinned schema"):
        _build(tmp_path / "handoff", tuple(bundle))


def test_rollback_failure_and_unexpected_writes_are_denied(tmp_path: Path) -> None:
    unexpected = list(_bundle(tmp_path / "unexpected"))
    unexpected[4] = deepcopy(unexpected[4])
    unexpected[4]["unexpected_writes"] = ["unexpected.db"]
    _rebind_rollback(unexpected)
    with pytest.raises(DualRunAdmissionError, match="unexpected writes"):
        _build(tmp_path / "unexpected-output", tuple(unexpected))

    failed = list(_bundle(tmp_path / "failed"))
    failed[4] = deepcopy(failed[4])
    failed[4]["execution_receipt"]["rollback_state"] = "failed"
    _rebind_rollback(failed)
    with pytest.raises(DualRunAdmissionError, match="did not succeed"):
        _build(tmp_path / "failed-output", tuple(failed))


def _reuse_lane_receipt(bundle: list[Any]) -> None:
    path = bundle[2]["trial-1"] / "trials/trial-1/legacy_shadow/execution_receipt.json"
    lane_full = json.loads(path.read_text(encoding="utf-8"))
    bundle[5] = lane_full
    bundle[4] = deepcopy(bundle[4])
    bundle[4]["execution_receipt"] = {
        **compact(lane_full),
        "status": "rolled_back",
        "rollback_state": "succeeded",
    }
    _rebind_rollback(bundle)


def test_global_execution_and_h09_uniqueness_includes_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_reuse = list(_bundle(tmp_path / "run-reuse"))
    _reuse_lane_receipt(run_reuse)
    with pytest.raises(DualRunAdmissionError, match="duplicate execution run ID"):
        _build(
            tmp_path / "run-output",
            tuple(run_reuse),
            Resolver(verified_at="2026-07-31T17:00:01Z"),
        )

    import skywatcher.ai_imagery.dual_run_handoff as module

    hash_reuse = list(_bundle(tmp_path / "hash-reuse"))
    hash_reuse[4] = deepcopy(hash_reuse[4])
    hash_reuse[4]["execution_receipt"]["receipt_sha256"] = (
        hash_reuse[3][0]["execution_receipts"][0]["receipt_sha256"]
    )
    _rebind_rollback(hash_reuse)
    monkeypatch.setattr(
        module,
        "bind_verified_receipt",
        lambda *args, **kwargs: Resolver(verified_at="2026-07-31T17:00:01Z").resolve(
            hash_reuse[5]
        ),
    )
    with pytest.raises(DualRunAdmissionError, match="receipt SHA-256"):
        _build(tmp_path / "hash-output", tuple(hash_reuse))

    verification_reuse = list(_bundle(tmp_path / "verification-reuse"))
    duplicate = verification_reuse[3][0]["receipt_verifications"][0]
    monkeypatch.setattr(module, "bind_verified_receipt", lambda *args, **kwargs: duplicate)
    with pytest.raises(DualRunAdmissionError, match="duplicate H09 verification"):
        _build(tmp_path / "verification-output", tuple(verification_reuse))


@pytest.mark.parametrize(
    ("decision", "action", "expires", "match"),
    [
        ("REJECT", "RELEASE_TO_H08_OFFLINE_EVALUATION", "2026-08-01T17:00:00Z", "not approved"),
        ("ABORT", "RELEASE_TO_H08_OFFLINE_EVALUATION", "2026-08-01T17:00:00Z", "aborted"),
        ("APPROVE", "EXECUTE_MODEL", "2026-08-01T17:00:00Z", "pinned schema|prohibited"),
        ("APPROVE", "RELEASE_TO_H08_OFFLINE_EVALUATION", "2026-07-31T16:30:00Z", "expired"),
    ],
)
def test_operator_decisions_scope_and_expiry(
    tmp_path: Path, decision: str, action: str, expires: str, match: str
) -> None:
    bundle = list(_bundle(tmp_path / f"{decision}-{action}"))
    bundle[6] = authorization(
        bundle[0],
        bundle[1],
        bundle[3],
        bundle[4],
        decision=decision,
        action=action,
        expires_at=expires,
    )
    with pytest.raises(DualRunAdmissionError, match=match):
        _build(tmp_path / "output", tuple(bundle))


def test_operator_exact_schema_and_presence_are_required(tmp_path: Path) -> None:
    malformed = list(_bundle(tmp_path / "malformed"))
    malformed[6] = deepcopy(malformed[6])
    malformed[6]["undeclared"] = True
    with pytest.raises(DualRunAdmissionError, match="exact pinned schema"):
        _build(tmp_path / "malformed-output", tuple(malformed))
    absent = list(_bundle(tmp_path / "absent"))
    absent[6] = None
    with pytest.raises(DualRunAdmissionError, match="authorization"):
        _build(tmp_path / "absent-output", tuple(absent))


def test_post_validation_source_mutation_is_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import skywatcher.ai_imagery.dual_run_handoff as module

    bundle = _bundle(tmp_path / "mutation")
    original = module._payload_files

    def mutate(**kwargs):
        path = bundle[2]["trial-1"] / "trials/trial-1/legacy_shadow/lane_evidence.json"
        path.write_bytes(path.read_bytes() + b" ")
        return original(**kwargs)

    monkeypatch.setattr(module, "_payload_files", mutate)
    with pytest.raises(DualRunAdmissionError, match="changed after admission"):
        _build(tmp_path / "mutation-output", bundle)


def test_atomic_failure_leaves_no_partial_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import skywatcher.ai_imagery.dual_run_handoff as module

    bundle = _bundle(tmp_path / "failure")
    destination = tmp_path / "failed-handoff"

    def fail_after_one(root: Path, files) -> None:  # noqa: ANN001
        relative, data = next(iter(sorted(files.items())))
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        raise RuntimeError("injected")

    monkeypatch.setattr(module, "_write_files", fail_after_one)
    with pytest.raises(RuntimeError, match="injected"):
        _build(destination, bundle)
    assert not destination.exists()
    assert not (tmp_path / ".failed-handoff.s07-tmp").exists()


def test_generated_handoff_passes_exact_pinned_h08_contracts(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path / "integrated")
    destination = tmp_path / "handoff"
    manifest = _build(destination, bundle)
    fixture_root = Path(__file__).resolve().parent / "fixtures/thehub_h08"
    checker = Draft202012Validator.FORMAT_CHECKER
    records = [
        (
            json.loads((destination / "campaign_manifest.json").read_text()),
            "dual_run_campaign_manifest.v1.schema.json",
        ),
        (
            json.loads((destination / "model_field_equivalence_policy.json").read_text()),
            "model_field_equivalence_policy.v1.schema.json",
        ),
        (
            json.loads((destination / "rollback_drill_evidence.json").read_text()),
            "rollback_drill_evidence.v1.schema.json",
        ),
    ]
    records.extend(
        (json.loads(path.read_text()), "dual_run_lane_evidence.v1.schema.json")
        for path in sorted(destination.glob("trials/*/*/lane_evidence.json"))
    )
    for value, name in records:
        Draft202012Validator(
            _schema(fixture_root, name), format_checker=checker
        ).validate(value)
    campaign_value, policy_value, rollback_value = (
        records[0][0],
        records[1][0],
        records[2][0],
    )
    lanes = [value for value, name in records if name == "dual_run_lane_evidence.v1.schema.json"]
    _pinned_h08_validate_dual_run_records(
        campaign_value, policy_value, lanes, rollback_value, fixture_root
    )
    assert campaign_value["pins"]["equivalence_policy_id"] == policy_value["policy_id"]
    assert manifest["trial_accounting"]["admitted"] == len(campaign_value["trials"])
    assert manifest["lane_accounting"]["verified"] == 2 * len(campaign_value["trials"])
    assert manifest["receipt_accounting"]["verified"] == 2 * len(campaign_value["trials"]) + 1
    assert hashlib.sha256(
        (fixture_root / "model_field_equivalence_policy.v1.schema.json").read_bytes()
    ).hexdigest() == "a33a21dcde4da10c24c9f467fff327aecbe43720905732cd340fda0b1767bb57"
    assert hashlib.sha256(
        (fixture_root / "rollback_drill_evidence.v1.schema.json").read_bytes()
    ).hexdigest() == "3ef0d10a1850bdc70d3db456496d615f98d2aaef5a7ace3f2d2865301aff1342"


def test_static_source_excludes_runtime_surfaces() -> None:
    root = Path(__file__).resolve().parents[1] / "src/skywatcher/ai_imagery"
    combined = "\n".join(
        (root / name).read_text(encoding="utf-8").lower()
        for name in ("dual_run_admission.py", "dual_run_handoff.py")
    )
    forbidden = (
        "import requests",
        "import urllib",
        "import socket",
        "import anthropic",
        "import openai",
        "import sqlite3",
        "import sqlalchemy",
        "import subprocess",
        "import docker",
        "import kubernetes",
    )
    assert not any(value in combined for value in forbidden)
