from pathlib import Path

from server.backend.console.capabilities import build_capabilities


def test_phase3_map_runtime_capabilities_are_explicit(tmp_path: Path) -> None:
    payload = build_capabilities(tmp_path)
    capabilities = {entry["id"]: entry for entry in payload["capabilities"]}

    assert payload["api_version"] == "0.3.0"
    assert payload["capability_count"] == 24
    assert payload["coverage_percent"] == 100.0
    assert capabilities["map_navigation"]["status"] == "available"
    assert capabilities["geolocation"]["status"] == "available"
    assert capabilities["basemap_controls"]["status"] == "available"
    assert capabilities["playback_timeline"]["status"] == "unavailable_no_artifact"

    runtime = payload["map_runtime"]
    assert runtime == {
        "engine": "MapLibre GL JS",
        "route": "/console",
        "offline_basemap_id": "local-blank-diagnostic",
        "network_required_for_blank_diagnostic": False,
        "provider_keys_required": False,
        "attribution_always_visible": True,
        "webgl_cleanup_required": True,
    }


def test_phase3_does_not_relax_producer_policy(tmp_path: Path) -> None:
    policy = build_capabilities(tmp_path)["policy"]
    assert policy["fr24_scraping"] is False
    assert policy["proprietary_asset_copying"] is False
    assert policy["synthetic_production_eligible"] is False
    assert policy["row_level_provenance_required"] is True
