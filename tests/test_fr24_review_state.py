"""Tests for FR24 dashboard local review-state JSON helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import fr24.dashboard_data as dashboard_schema

import fr24.review_state as mod



def test_build_local_state_payload_uses_dashboard_schema_single_source():
    payload = mod.build_local_state_payload({
        "fused::a.png": "dashboard_review_deferred",
        "fused::b.png": "dashboard_review_rejected",
    }, generated_at="2026-05-24T00:00:00+00:00")

    assert payload["schema_version"] == dashboard_schema.LOCAL_STATE_SCHEMA_VERSION
    assert payload["policy"] == dashboard_schema.LOCAL_STATE_POLICY
    assert payload["allowed_queue_statuses"] == list(dashboard_schema.ALLOWED_QUEUE_STATUSES)
    assert payload["entries"] == {
        "fused::a.png": "dashboard_review_deferred",
        "fused::b.png": "dashboard_review_rejected",
    }


def test_local_state_round_trip_import_export_smoke(tmp_path: Path):
    path = tmp_path / "fr24_dashboard_review_queue.local_state.json"
    exported = mod.write_local_state_json(path, {
        "fused::a.png": "dashboard_review_accepted_after_manual_review",
    })
    imported = mod.read_local_state_json(path)

    assert path.exists()
    assert imported["schema_version"] == exported["schema_version"]
    assert imported["policy"] == exported["policy"]
    assert imported["allowed_queue_statuses"] == exported["allowed_queue_statuses"]
    assert imported["entries"] == {
        "fused::a.png": "dashboard_review_accepted_after_manual_review",
    }


def test_local_state_rejects_prohibited_or_unknown_status(tmp_path: Path):
    path = tmp_path / "bad_state.json"
    path.write_text(json.dumps({
        "schema_version": dashboard_schema.LOCAL_STATE_SCHEMA_VERSION,
        "policy": dashboard_schema.LOCAL_STATE_POLICY,
        "entries": {"fused::bad.png": "confirmed_aircraft_event"},
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported FR24 review queue status"):
        mod.read_local_state_json(path)


def test_local_state_rejects_wrong_schema_version():
    with pytest.raises(ValueError, match="schema_version"):
        mod.validate_local_state_payload({
            "schema_version": "legacy",
            "policy": dashboard_schema.LOCAL_STATE_POLICY,
            "entries": {},
        })


def test_local_state_rejects_empty_identity():
    with pytest.raises(ValueError, match="non-empty"):
        mod.build_local_state_payload({"": "dashboard_review_open"})
