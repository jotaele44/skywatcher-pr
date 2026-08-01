from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from sensor_replay.core import ReplayError, build_replay_receipt, canonical_json, normalize_utc

FIXTURE = Path(__file__).parent / "fixtures" / "multisensor_replay"


def test_normalize_utc_requires_offset() -> None:
    assert normalize_utc("2026-01-01T00:00:00-04:00") == "2026-01-01T04:00:00.000000Z"
    with pytest.raises(ReplayError):
        normalize_utc("2026-01-01T00:00:00")


def test_two_replays_are_byte_identical_and_fully_accounted() -> None:
    first = build_replay_receipt(FIXTURE, FIXTURE / "manifest.json")
    second = build_replay_receipt(FIXTURE, FIXTURE / "manifest.json")
    assert canonical_json(first) == canonical_json(second)
    assert first["member_count"] == 1
    assert first["observation_count"] == 4
    assert first["source_count"] == 4
    assert first["timestamp_count"] == 4
    assert first["interpolation"] == "none"
    assert {item["sensor_type"] for item in first["observations"]} == {"aircraft_observation", "provider_rendered_frame", "geomagnetic_timeseries", "weather_timeseries"}


def test_path_traversal_fails_closed(tmp_path: Path) -> None:
    manifest = json.loads((FIXTURE / "manifest.json").read_text())
    manifest["members"][0]["path"] = "../frame.txt"
    candidate = tmp_path / "manifest.json"
    candidate.write_text(json.dumps(manifest))
    with pytest.raises(ReplayError, match="unsafe member path"):
        build_replay_receipt(FIXTURE, candidate)


def test_content_replacement_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "frame.txt").write_text("replaced\n")
    manifest = copy.deepcopy(json.loads((FIXTURE / "manifest.json").read_text()))
    candidate = root / "manifest.json"
    candidate.write_text(json.dumps(manifest))
    with pytest.raises(ReplayError, match="content replacement detected"):
        build_replay_receipt(root, candidate)


def test_sensor_type_payload_separation(tmp_path: Path) -> None:
    manifest = json.loads((FIXTURE / "manifest.json").read_text())
    manifest["observations"][0]["sensor_type"] = "geomagnetic_timeseries"
    candidate = tmp_path / "manifest.json"
    candidate.write_text(json.dumps(manifest))
    with pytest.raises(ReplayError, match="timeseries payload"):
        build_replay_receipt(FIXTURE, candidate)
