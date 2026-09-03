from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "configs" / "visual_reasoning"
DOC = ROOT / "docs" / "architecture"


def _load_yaml(name: str) -> dict:
    data = yaml.safe_load((CFG / name).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert data.get("spec_version") == "0.2.0"
    return data


def _git_blob_sha1(path: Path) -> str:
    raw = path.read_bytes()
    header = f"blob {len(raw)}\0".encode()
    return hashlib.sha1(header + raw).hexdigest()


def test_all_vector1_yaml_parses() -> None:
    for name in (
        "parameter_registry_v0_2.yaml",
        "rule_registry_v0_2.yaml",
        "control_plane_v0_2.yaml",
        "ontology_and_adapters_v0_2.yaml",
        "calibration_and_coverage_v0_2.yaml",
        "reason_codes_v0_2.yaml",
    ):
        _load_yaml(name)


def test_parameter_denominator_has_unique_ids_and_required_families() -> None:
    data = _load_yaml("parameter_registry_v0_2.yaml")
    ids: list[str] = []
    for family in data["families"].values():
        ids.extend(family["parameters"])
    assert ids
    assert len(ids) == len(set(ids))
    expected = {
        "input_custody",
        "ui_ocr",
        "quality_zoom",
        "illumination_shadow",
        "seam_stitch_artifact",
        "palm_vegetation",
        "water_hydrography",
        "roads_buildings",
        "infrastructure",
        "quarry",
        "excavation",
        "portal_like",
        "multiscale_multiframe",
        "scene_graph",
        "scene_locator",
        "confidence_and_global",
    }
    assert set(data["families"]) == expected
    assert data["default_metadata"]["status"] == "CALIBRATION_REQUIRED"
    assert data["canonical_overrides"]["GLOBAL.PROXIMITY_ONLY_IDENTITY_ALLOWED"] is False
    assert data["canonical_overrides"]["GLOBAL.DETERMINISTIC_TIE_BREAK_COUNTS_AS_EVIDENCE"] is False


def test_rule_ids_unique_and_reason_codes_closed() -> None:
    rules = _load_yaml("rule_registry_v0_2.yaml")["rules"]
    ids = [item["id"] for item in rules]
    assert len(ids) == len(set(ids))
    codes = set(_load_yaml("reason_codes_v0_2.yaml")["codes"])
    used = {item["reason"] for item in rules}
    assert used <= codes
    assert used == codes


def test_fail_closed_control_plane() -> None:
    data = _load_yaml("control_plane_v0_2.yaml")
    nulls = data["null_policy"]
    ties = data["tie_policy"]
    assert nulls["missing_input_is_zero"] is False
    assert nulls["missing_input_is_false"] is False
    assert nulls["missing_input_is_negative_evidence"] is False
    assert ties["deterministic_order_is_evidence"] is False
    assert ties["location_runner_up_must_be_preserved"] is True
    assert data["precedence"][0] == "HARD_FALSIFIER"
    assert data["precedence"][-1] == "HEURISTIC_DISCOVERY"


def test_identity_adapter_prohibits_heuristic_identity_methods() -> None:
    data = _load_yaml("ontology_and_adapters_v0_2.yaml")
    forbidden = set(data["adapters"]["external_identity_binding"]["forbidden_identity_methods"])
    assert forbidden == {
        "NAME_ONLY",
        "NORMALIZED_NAME_ONLY",
        "COUNT_EQUALITY",
        "NEAREST_ONLY",
        "PROXIMITY_ONLY",
        "SAME_CATEGORY",
        "SOURCE_ABSENCE",
    }


def test_declared_coverage_has_zero_open_families() -> None:
    data = _load_yaml("calibration_and_coverage_v0_2.yaml")
    assert data["coverage"]["parameter_family_open_count"] == 0
    assert data["coverage"]["rule_family_open_count"] == 0
    assert all(value == "PASS" for value in data["coverage"]["declared_families"].values())
    assert data["calibration_policy"]["unvalidated_numeric_status"] == "CALIBRATION_REQUIRED"


def test_freeze_manifest_git_blob_identities() -> None:
    manifest = json.loads((DOC / "VISUAL_REASONING_VECTOR1_FREEZE_MANIFEST_v0_2.json").read_text(encoding="utf-8"))
    assert manifest["state"] == "PASS_BOUNDED_EXHAUSTION"
    for rel, identity in manifest["artifacts"].items():
        assert identity.startswith("gitblob:")
        assert _git_blob_sha1(ROOT / rel) == identity.removeprefix("gitblob:")
