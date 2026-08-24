from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

from sensor_replay.core import (
    ReplayError,
    build_replay_receipt,
    canonical_json,
    normalize_utc,
)

FIXTURE = Path(__file__).parent / "fixtures" / "multisensor_replay"
SCHEMAS = Path(__file__).parents[1] / "schemas"


def _manifest() -> dict:
    return json.loads(
        (FIXTURE / "manifest.json").read_text(encoding="utf-8")
    )


def _write_manifest(tmp_path: Path, manifest: dict) -> Path:
    candidate = tmp_path / "manifest.json"
    candidate.write_text(json.dumps(manifest), encoding="utf-8")
    return candidate


def _validator(name: str) -> Draft202012Validator:
    schema = json.loads(
        (SCHEMAS / name).read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(
        schema,
        format_checker=FormatChecker(),
    )


def test_normalize_utc_requires_offset() -> None:
    assert normalize_utc(
        "2026-01-01T00:00:00-04:00"
    ) == "2026-01-01T04:00:00.000000Z"
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
    assert {
        item["sensor_type"] for item in first["observations"]
    } == {
        "aircraft_observation",
        "provider_rendered_frame",
        "geomagnetic_timeseries",
        "weather_timeseries",
    }


def test_path_traversal_fails_closed(tmp_path: Path) -> None:
    manifest = _manifest()
    manifest["members"][0]["path"] = "../frame.txt"
    candidate = _write_manifest(tmp_path, manifest)
    with pytest.raises(ReplayError, match="unsafe member path"):
        build_replay_receipt(FIXTURE, candidate)


def test_content_replacement_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "frame.txt").write_text("replaced\n", encoding="utf-8")
    candidate = _write_manifest(root, copy.deepcopy(_manifest()))
    with pytest.raises(
        ReplayError,
        match="content replacement detected",
    ):
        build_replay_receipt(root, candidate)


def test_source_and_observation_type_mismatch_fails_closed(
    tmp_path: Path,
) -> None:
    manifest = _manifest()
    manifest["observations"][0]["sensor_type"] = (
        "geomagnetic_timeseries"
    )
    candidate = _write_manifest(tmp_path, manifest)
    with pytest.raises(
        ReplayError,
        match="source and observation sensor_type mismatch",
    ):
        build_replay_receipt(FIXTURE, candidate)


def test_duplicate_observation_id_fails_closed(
    tmp_path: Path,
) -> None:
    manifest = _manifest()
    manifest["observations"][1]["observation_id"] = "a1"
    candidate = _write_manifest(tmp_path, manifest)
    with pytest.raises(
        ReplayError,
        match="duplicate observation_id",
    ):
        build_replay_receipt(FIXTURE, candidate)


def test_provider_frame_member_and_hash_are_cross_bound(
    tmp_path: Path,
) -> None:
    manifest = _manifest()
    frame = manifest["observations"][1]["payload"]
    frame["content_sha256"] = "0" * 64
    candidate = _write_manifest(tmp_path, manifest)
    with pytest.raises(
        ReplayError,
        match="provider frame hash does not match",
    ):
        build_replay_receipt(FIXTURE, candidate)

    manifest = _manifest()
    manifest["observations"][1]["payload"]["member_path"] = (
        "missing.txt"
    )
    candidate = _write_manifest(tmp_path, manifest)
    with pytest.raises(
        ReplayError,
        match="references undeclared member",
    ):
        build_replay_receipt(FIXTURE, candidate)


def test_reversed_and_overlapping_gaps_fail_closed(
    tmp_path: Path,
) -> None:
    manifest = _manifest()
    manifest["gaps"][0]["start_utc"] = "2026-01-01T04:06:00Z"
    candidate = _write_manifest(tmp_path, manifest)
    with pytest.raises(
        ReplayError,
        match="start_utc must be before",
    ):
        build_replay_receipt(FIXTURE, candidate)

    manifest = _manifest()
    manifest["gaps"].append(
        {
            "source_id": "radar-fixture",
            "start_utc": "2026-01-01T04:04:00Z",
            "end_utc": "2026-01-01T04:06:00Z",
            "reason": "overlap",
        }
    )
    candidate = _write_manifest(tmp_path, manifest)
    with pytest.raises(
        ReplayError,
        match="overlapping gaps",
    ):
        build_replay_receipt(FIXTURE, candidate)


@pytest.mark.parametrize(
    ("schema_name", "valid_instance", "invalid_instance"),
    [
        (
            "sensor_source_v1.schema.json",
            _manifest()["sources"][0],
            {
                **_manifest()["sources"][0],
                "sensor_type": "magnetic_wave",
            },
        ),
        (
            "sensor_observation_v1.schema.json",
            _manifest()["observations"][0],
            {
                **_manifest()["observations"][0],
                "event_time_utc": "not-a-time",
            },
        ),
        (
            "sensor_frame_manifest_v1.schema.json",
            _manifest()["observations"][1]["payload"],
            {
                **_manifest()["observations"][1]["payload"],
                "member_path": "../frame.txt",
            },
        ),
        (
            "replay_session_v1.schema.json",
            {
                "protocol": "skywatcher-multisensor-replay-v1",
                "replay_id": "fixture-replay-001",
                "timeline_policy": "union_observation_timestamps",
                "interpolation": "none",
                "source_ids": ["fr24-fixture"],
            },
            {
                "protocol": "skywatcher-multisensor-replay-v1",
                "replay_id": "fixture-replay-001",
                "timeline_policy": "union_observation_timestamps",
                "interpolation": "linear",
                "source_ids": ["fr24-fixture"],
            },
        ),
        (
            "sensor_adjudication_v1.schema.json",
            {
                "adjudication_id": "adj-1",
                "observation_id": "r1",
                "classification": "rf_interference",
                "decision_source": "human_adjudication",
                "confidence": 0.8,
            },
            {
                "adjudication_id": "adj-1",
                "observation_id": "r1",
                "classification": "magnetic_causation",
                "decision_source": "human_adjudication",
                "confidence": 0.8,
            },
        ),
    ],
)
def test_contract_schemas_accept_positive_and_reject_negative(
    schema_name: str,
    valid_instance: dict,
    invalid_instance: dict,
) -> None:
    validator = _validator(schema_name)
    validator.validate(valid_instance)
    with pytest.raises(ValidationError):
        validator.validate(invalid_instance)


def test_receipt_schema_accepts_authoritative_receipt() -> None:
    receipt = build_replay_receipt(
        FIXTURE,
        FIXTURE / "manifest.json",
    )
    validator = _validator("replay_receipt_v1.schema.json")
    validator.validate(receipt)
    invalid = {**receipt, "interpolation": "linear"}
    with pytest.raises(ValidationError):
        validator.validate(invalid)
