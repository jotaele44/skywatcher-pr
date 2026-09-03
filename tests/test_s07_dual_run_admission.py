from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from s07_support import NOW, Resolver, build_s06_package, campaign
from skywatcher.ai_imagery._dual_run_common import (
    canonical_json_bytes,
    sha256_bytes,
)
from skywatcher.ai_imagery.dual_run_admission import (
    DualRunAdmissionError,
    compute_s06_trial_admission,
    record_trial_admission_receipt,
)


def _admit(root: Path, resolver: Resolver | None = None):
    return compute_s06_trial_admission(
        package_root=root,
        expected_campaign=campaign(),
        trial_id="trial-1",
        receipt_verification_resolver=resolver or Resolver(),
        created_at=NOW,
    )


def test_admission_is_content_addressed_and_immutable(tmp_path: Path) -> None:
    root = tmp_path / "trial"
    build_s06_package(root, campaign(), "trial-1")
    receipt = _admit(root)
    assert receipt["status"] == "ADMITTED"
    assert receipt["dual_run_executed"] is False
    assert receipt["h08_evaluation_executed"] is False
    path = record_trial_admission_receipt(tmp_path / "registry", receipt)
    assert path == record_trial_admission_receipt(tmp_path / "registry", receipt)
    changed = deepcopy(receipt)
    changed["created_at"] = "2026-08-01T00:00:00Z"
    with pytest.raises(DualRunAdmissionError, match="identity"):
        record_trial_admission_receipt(tmp_path / "registry", changed)


def test_missing_and_unexpected_files_are_denied(tmp_path: Path) -> None:
    root = tmp_path / "trial"
    build_s06_package(root, campaign(), "trial-1")
    (root / "campaign_manifest.json").unlink()
    with pytest.raises(DualRunAdmissionError, match="file set"):
        _admit(root)

    root = tmp_path / "trial-extra"
    build_s06_package(root, campaign(), "trial-1")
    (root / "unexpected.json").write_bytes(canonical_json_bytes({"x": 1}))
    with pytest.raises(DualRunAdmissionError, match="file set"):
        _admit(root)


def test_digest_drift_is_denied(tmp_path: Path) -> None:
    root = tmp_path / "trial"
    build_s06_package(root, campaign(), "trial-1")
    path = root / "campaign_manifest.json"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(DualRunAdmissionError, match="digest"):
        _admit(root)


def test_campaign_policy_and_lane_substitution_are_denied(tmp_path: Path) -> None:
    root = tmp_path / "campaign"
    build_s06_package(root, campaign(), "trial-1")
    with pytest.raises(DualRunAdmissionError, match="campaign identity|expected campaign"):
        altered = campaign()
        altered["created_at"] = "2026-08-01T00:00:00Z"
        _ = compute_s06_trial_admission(
            package_root=root,
            expected_campaign=altered,
            trial_id="trial-1",
            receipt_verification_resolver=Resolver(),
            created_at=NOW,
        )

    root = tmp_path / "lane"
    build_s06_package(root, campaign(), "trial-1")
    lane_path = root / "trials/trial-1/legacy_shadow/lane_evidence.json"
    lane = json.loads(lane_path.read_text())
    lane["legacy_shadow_export_id"] = "legacy-shadow-export-sha256-" + "f" * 64
    data = canonical_json_bytes(lane)
    lane_path.write_bytes(data)
    lines = (root / "SHA256SUMS").read_text().splitlines()
    relative = "trials/trial-1/legacy_shadow/lane_evidence.json"
    lines = [
        f"{sha256_bytes(data)}  {relative}" if line.endswith("  " + relative) else line
        for line in lines
    ]
    (root / "SHA256SUMS").write_text(
        "\n".join(sorted(lines, key=lambda line: line.split("  ", 1)[1])) + "\n"
    )
    with pytest.raises(DualRunAdmissionError, match="identity|bind"):
        _admit(root)


def test_h09_missing_false_drifted_and_swapped_receipts_are_denied(
    tmp_path: Path,
) -> None:
    root = tmp_path / "false"
    build_s06_package(root, campaign(), "trial-1")
    with pytest.raises(DualRunAdmissionError, match="verification failed"):
        _admit(root, Resolver(fail=True))

    root = tmp_path / "drift"
    build_s06_package(root, campaign(), "trial-1")
    with pytest.raises(DualRunAdmissionError, match="binding drift"):
        _admit(root, Resolver(drift_run=True))

    root = tmp_path / "swapped"
    build_s06_package(root, campaign(), "trial-1")
    left = root / "trials/trial-1/legacy_shadow/execution_receipt.json"
    right = root / "trials/trial-1/adr0006_candidate/execution_receipt.json"
    left_bytes, right_bytes = left.read_bytes(), right.read_bytes()
    left.write_bytes(right_bytes)
    right.write_bytes(left_bytes)
    relative_left = left.relative_to(root).as_posix()
    relative_right = right.relative_to(root).as_posix()
    lines = (root / "SHA256SUMS").read_text().splitlines()
    replacements = {
        relative_left: sha256_bytes(right_bytes),
        relative_right: sha256_bytes(left_bytes),
    }
    lines = [
        f"{replacements.get(line.split('  ', 1)[1], line.split('  ', 1)[0])}  {line.split('  ', 1)[1]}"
        for line in lines
    ]
    (root / "SHA256SUMS").write_text(
        "\n".join(sorted(lines, key=lambda line: line.split("  ", 1)[1])) + "\n"
    )
    with pytest.raises(DualRunAdmissionError, match="compact receipt reference drift"):
        _admit(root)


def test_path_traversal_absolute_and_symlink_are_denied(tmp_path: Path) -> None:
    root = tmp_path / "trial"
    build_s06_package(root, campaign(), "trial-1")
    target = root / "campaign_manifest.json"
    target.unlink()
    target.symlink_to(root / "model_field_equivalence_policy.json")
    with pytest.raises(DualRunAdmissionError, match="symlink"):
        _admit(root)

    with pytest.raises(DualRunAdmissionError):
        compute_s06_trial_admission(
            package_root=root,
            expected_campaign=campaign(),
            trial_id="../../outside",
            receipt_verification_resolver=Resolver(),
            created_at=NOW,
        )


def _rewrite_json_and_sums(root: Path, relative: str, value: object) -> None:
    data = canonical_json_bytes(value)
    (root / relative).write_bytes(data)
    lines = (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    rewritten = []
    for line in lines:
        _, path = line.split("  ", 1)
        digest = sha256_bytes(data) if path == relative else line.split("  ", 1)[0]
        rewritten.append(f"{digest}  {path}")
    (root / "SHA256SUMS").write_text(
        "\n".join(sorted(rewritten, key=lambda item: item.split("  ", 1)[1])) + "\n",
        encoding="utf-8",
    )


def test_policy_export_and_candidate_package_substitution_are_denied(
    tmp_path: Path,
) -> None:
    root = tmp_path / "policy"
    build_s06_package(root, campaign(), "trial-1")
    relative = "model_field_equivalence_policy.json"
    value = json.loads((root / relative).read_text(encoding="utf-8"))
    value["version"] = "changed"
    _rewrite_json_and_sums(root, relative, value)
    with pytest.raises(DualRunAdmissionError, match="policy identity"):
        _admit(root)

    root = tmp_path / "export"
    build_s06_package(root, campaign(), "trial-1")
    relative = "trials/trial-1/legacy_shadow/legacy_shadow_export.json"
    value = json.loads((root / relative).read_text(encoding="utf-8"))
    value["created_at"] = "2026-08-01T00:00:00Z"
    _rewrite_json_and_sums(root, relative, value)
    with pytest.raises(DualRunAdmissionError, match="export identity"):
        _admit(root)

    root = tmp_path / "package"
    build_s06_package(root, campaign(), "trial-1")
    relative = (
        "trials/trial-1/adr0006_candidate/producer_package/provisional_signals.json"
    )
    value = json.loads((root / relative).read_text(encoding="utf-8"))
    value[0]["signal_id"] = "substituted-signal"
    _rewrite_json_and_sums(root, relative, value)
    with pytest.raises(DualRunAdmissionError, match="normalized digest"):
        _admit(root)


def test_missing_h09_verification_is_denied(tmp_path: Path) -> None:
    class MissingResolver:
        def resolve(self, full):  # noqa: ANN001, ANN201 - protocol failure fixture
            raise LookupError("not found")

    root = tmp_path / "missing-h09"
    build_s06_package(root, campaign(), "trial-1")
    with pytest.raises(DualRunAdmissionError, match="unavailable"):
        _admit(root, MissingResolver())  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_trial_id", ("/absolute", "C:/trial", "nested/trial", ".."))
def test_absolute_multicomponent_and_parent_trial_ids_are_denied(
    tmp_path: Path, bad_trial_id: str
) -> None:
    root = tmp_path / "trial-id"
    build_s06_package(root, campaign(), "trial-1")
    with pytest.raises(DualRunAdmissionError, match="trial_id"):
        compute_s06_trial_admission(
            package_root=root,
            expected_campaign=campaign(),
            trial_id=bad_trial_id,
            receipt_verification_resolver=Resolver(),
            created_at=NOW,
        )
