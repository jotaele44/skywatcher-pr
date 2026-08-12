"""Capability-manifest reachability for the RLSM spatial-truth vertical slice."""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "manifests" / "rlsm_aircraft_spatial_truth_v0_1.json"


def test_capability_manifest_reaches_storage_backend_api_and_gui() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert manifest["capability_id"] == "rlsm_aircraft_spatial_truth_v0_1"
    assert manifest["status"] == "implemented_operator_run_pending"
    assert manifest["coordinate_contract"]["heading_field_overwritten"] is False
    assert manifest["coordinate_contract"]["maximum_located_error_m"] == 500
    assert manifest["marker_contract"]["selection_margin_min"] == 0.1
    assert manifest["zoom_contract"]["minimum_transfer_support"] == 3
    assert (
        manifest["zoom_contract"]["evidence_only_rungs_assigned_to_frames"]
        is False
    )

    storage_paths = [manifest["storage"]["schema"], manifest["storage"]["migration"]]
    implementation_paths = [
        value
        for key, value in manifest["implementation"].items()
        if key.endswith("file")
        or key
        in {
            "marker_detector",
            "georeference",
            "pipeline",
            "exporter",
            "backend",
            "data_provider",
            "page",
        }
    ]
    for relative_path in storage_paths + implementation_paths + manifest["tests"]:
        assert (REPO / relative_path).is_file(), relative_path

    schema = (REPO / manifest["storage"]["schema"]).read_text(encoding="utf-8")
    for table in (
        manifest["storage"]["accounting_table"],
        manifest["storage"]["candidate_table"],
        manifest["storage"]["georeference_table"],
        manifest["storage"]["zoom_table"],
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in schema

    pipeline = (REPO / manifest["implementation"]["pipeline"]).read_text(
        encoding="utf-8"
    )
    for stage in manifest["pipeline_stages"]:
        assert f'"{stage}"' in pipeline

    backend = (REPO / manifest["implementation"]["backend"]).read_text(
        encoding="utf-8"
    )
    provider = (REPO / manifest["implementation"]["data_provider"]).read_text(
        encoding="utf-8"
    )
    for entity in manifest["api_entities"]:
        assert entity in backend
        assert entity in provider or entity in {"AirspaceObservations", "AircraftProfiles"}

    route = manifest["implementation"]["route"]
    route_file = (REPO / manifest["implementation"]["route_file"]).read_text(
        encoding="utf-8"
    )
    navigation = (REPO / manifest["implementation"]["navigation_file"]).read_text(
        encoding="utf-8"
    )
    assert route in route_file
    assert route in navigation
    assert manifest["deferred"]["track_polyline"] is True
    assert (
        manifest["deferred"]["scale_bar_ocr"]["trigger"]
        == "unresolved_otherwise_recoverable_rate_gt_0.15"
    )
