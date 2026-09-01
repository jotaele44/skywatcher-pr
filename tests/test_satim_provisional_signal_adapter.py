from __future__ import annotations

from pathlib import Path

import pytest

from skywatcher.satim.provisional_signal import SatimSignalAdapterError, adapt_satim_output


def _satim() -> dict:
    return {
        "satim_output_id": "satim-1",
        "signal_domain": "terrain_imagery",
        "observation_type": "tile_seam",
        "lat": 18.4,
        "lon": -66.1,
        "evidence_tier": "T3",
        "confidence": 0.72,
        "geometry_status": "approximate",
        "source_layer": "gibs:test",
        "notes": "calibration fixture",
    }


def test_adapter_is_deterministic_and_always_provisional() -> None:
    kwargs = {
        "source_artifact_ids": ["artifact-b", "artifact-a", "artifact-a"],
        "method_version": "satim-adapter.v1",
        "created_at": "2026-07-30T15:00:00Z",
        "parameters": {"threshold": 0.2},
    }
    first = adapt_satim_output(_satim(), **kwargs)
    second = adapt_satim_output(_satim(), **kwargs)
    assert first == second
    assert first["source_artifact_ids"] == ["artifact-a", "artifact-b"]
    assert first["method"] == "TILE_SEAM_CLASSIFICATION"
    assert first["provisional"] is True
    assert first["review_status"] == "NEEDS_REVIEW"
    assert first["schema_version"] == "satim_provisional_signal.v1"


def test_adapter_preserves_domain_result_without_promoting_evidence() -> None:
    record = adapt_satim_output(
        _satim(),
        source_artifact_ids=["artifact-a"],
        method_version="satim-adapter.v1",
        created_at="2026-07-30T15:00:00Z",
    )
    assert record["result"]["evidence_tier"] == "T3"
    assert record["result"]["geometry_status"] == "approximate"
    assert "certified" not in record


def test_adapter_rejects_invalid_or_unaccounted_input() -> None:
    invalid = _satim()
    invalid["confidence"] = 1.1
    with pytest.raises(SatimSignalAdapterError):
        adapt_satim_output(
            invalid,
            source_artifact_ids=["artifact-a"],
            method_version="v1",
            created_at="2026-07-30T15:00:00Z",
        )
    with pytest.raises(SatimSignalAdapterError):
        adapt_satim_output(
            _satim(),
            source_artifact_ids=[],
            method_version="v1",
            created_at="2026-07-30T15:00:00Z",
        )


def test_adapter_source_contains_no_network_or_provider_runtime() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "skywatcher"
        / "satim"
        / "provisional_signal.py"
    ).read_text().lower()
    for forbidden in (
        "import requests",
        "import urllib",
        "import socket",
        "anthropic",
        "openai",
        "boto3",
    ):
        assert forbidden not in source
