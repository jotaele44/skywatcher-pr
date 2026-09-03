from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.backend.console.capabilities import CAPABILITY_DEFINITIONS, build_capabilities
from server.backend.console.router import router


def test_registry_is_exactly_24_unique_capabilities():
    assert len(CAPABILITY_DEFINITIONS) == 24
    assert len({item["id"] for item in CAPABILITY_DEFINITIONS}) == 24


def test_build_capabilities_reports_synthetic_separation(tmp_path: Path):
    airport_dir = tmp_path / "data" / "reference"
    airport_dir.mkdir(parents=True)
    (airport_dir / "pr_airports.jsonl").write_text('{"airport_id":"TJSJ"}\n', encoding="utf-8")

    package = tmp_path / "exports" / "examples" / "synthetic_airspace_package"
    package.mkdir(parents=True)
    (package / "observations.csv").write_text(
        "observation_id,event_datetime,source_id,source_type,lineage_id,synthetic\n"
        "syn-1,2026-05-20T10:00:00Z,src-1,screenshot,lin-1,true\n",
        encoding="utf-8",
    )
    result = build_capabilities(tmp_path)
    assert result["capability_count"] == 24
    assert result["coverage_percent"] == 100.0
    assert result["data_planes"]["operational_position"]["available"] is False
    assert result["data_planes"]["synthetic_test"]["record_count"] == 1
    assert result["policy"]["fr24_scraping"] is False
    assert result["policy"]["synthetic_production_eligible"] is False


def test_capabilities_endpoint_returns_contract():
    app = FastAPI()
    app.include_router(router)
    response = TestClient(app).get("/api/console/capabilities")
    assert response.status_code == 200
    payload = response.json()
    assert payload["capability_count"] == 24
    assert len(payload["capabilities"]) == 24
    assert payload["policy"]["row_level_provenance_required"] is True
