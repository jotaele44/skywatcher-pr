import copy
import json
from pathlib import Path

import pytest

from fr24_allowed_enums import (
    AllowedEnumRegistry,
    AllowedEnumRegistryError,
    load_allowed_enum_registry,
)


REGISTRY_PATH = Path("data/reference/fr24_allowed_enum_registry.json")


def load_payload():
    with REGISTRY_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def test_load_default_allowed_enum_registry():
    registry = load_allowed_enum_registry(REGISTRY_PATH)

    assert "tile_suppression" in registry.pipeline_stage_order
    assert "ground_context" in registry.pipeline_stage_order
    assert "tile_seam_anomalies" in registry.allowed_export_targets
    assert "vehicle_cluster_signature" in registry.allowed_families


def test_tile_analysis_runs_before_ground_context():
    registry = load_allowed_enum_registry(REGISTRY_PATH)
    stages = registry.pipeline_stage_order

    assert stages.index("tile_suppression") < stages.index("ground_context")


def test_signal_group_routes_have_expected_owners():
    registry = load_allowed_enum_registry(REGISTRY_PATH)

    assert registry.route_for("seam_anomaly_detection").owned_by_module == "fr24_tile_analysis.py"
    assert registry.route_for("vehicle_cluster_signature").owned_by_module == "fr24_ground_context.py"
    assert registry.route_for("land_clearing_signature").owned_by_module == "fr24_ground_context.py"
    assert registry.route_for("unlabeled_warehouse_signature").owned_by_module == "fr24_ground_context.py"
    assert registry.route_for("poi_recurrence").owned_by_module == "fr24_poi_recurrence.py"


def test_recurrence_module_does_not_own_visual_detection_groups():
    registry = load_allowed_enum_registry(REGISTRY_PATH)
    recurrence = registry.capability_for("fr24_poi_recurrence.py")

    forbidden = {
        "vehicle_cluster_signature",
        "land_clearing_signature",
        "unlabeled_warehouse_signature",
        "pool_signature",
        "seam_anomaly_detection",
    }
    assert forbidden.isdisjoint(recurrence.handled_signal_groups)


def test_unknown_signal_group_route_is_rejected():
    registry = load_allowed_enum_registry(REGISTRY_PATH)

    with pytest.raises(AllowedEnumRegistryError, match="unknown signal group route"):
        registry.route_for("missing_group")


def test_registry_rejects_unknown_export_target():
    payload = load_payload()
    payload = copy.deepcopy(payload)
    payload["signal_group_export_map"]["seam_anomaly_detection"]["export_targets"].append("bad_export")

    with pytest.raises(AllowedEnumRegistryError, match="exports unknown targets"):
        AllowedEnumRegistry(payload=payload).validate()


def test_registry_rejects_unknown_owner_module():
    payload = load_payload()
    payload = copy.deepcopy(payload)
    payload["signal_group_export_map"]["seam_anomaly_detection"]["owned_by_module"] = "missing.py"

    with pytest.raises(AllowedEnumRegistryError, match="references unknown module"):
        AllowedEnumRegistry(payload=payload).validate()


def test_registry_rejects_stage_order_drift():
    payload = load_payload()
    payload = copy.deepcopy(payload)
    payload["pipeline_stage_order"] = [
        "provenance",
        "privacy",
        "ground_context",
        "tile_suppression",
        "infrastructure_context",
        "recurrence",
        "export",
    ]

    with pytest.raises(AllowedEnumRegistryError, match="tile_suppression must precede"):
        AllowedEnumRegistry(payload=payload).validate()


def test_registry_rejects_visual_groups_in_recurrence_module():
    payload = load_payload()
    payload = copy.deepcopy(payload)
    payload["module_capability_map"]["fr24_poi_recurrence.py"]["handled_signal_groups"].append(
        "vehicle_cluster_signature"
    )

    with pytest.raises(AllowedEnumRegistryError, match="recurrence module must not own"):
        AllowedEnumRegistry(payload=payload).validate()
