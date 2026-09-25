from __future__ import annotations

import json
from pathlib import Path

import pytest

from skywatcher.fr24.acquisition_receipts import (
    AcquisitionReceiptError,
    export_harvest_carryover,
    load_manifest,
    next_discovery_target,
    record_blocked_auth,
    record_discovery,
    status_summary,
)


def _target(
    acquisition_id: str,
    identity: str,
    *,
    recoverable_from: str,
    recoverable_to: str,
    score: int = 100,
    days_left: int = 5,
) -> dict:
    return {
        "acquisition_id": acquisition_id,
        "type": "GAP",
        "identity": identity,
        "from": recoverable_from,
        "to": recoverable_to,
        "recoverable_from": recoverable_from,
        "recoverable_to": recoverable_to,
        "lost_days": 0,
        "priority_score": score,
        "priority_tier": "P1",
        "deadline": recoverable_to,
        "days_left_at_freeze": days_left,
        "discovery_status": "BLOCKED_EXTERNAL_AUTH",
        "discovered_flight_ids": [],
        "discovered_flights": [],
        "playback_status": "NOT_ATTEMPTED",
        "attempt_count": 0,
        "last_attempt_at": None,
        "last_error": "auth unavailable",
    }


def _manifest(*targets: dict) -> dict:
    return {
        "schema_version": 1,
        "generated_as_of": "2026-09-25",
        "targets": list(targets),
    }


def _write(path: Path, manifest: dict) -> None:
    path.write_text(json.dumps(manifest), encoding="utf-8")


def test_committed_p1_manifest_is_valid():
    repo = Path(__file__).resolve().parents[1]
    manifest = load_manifest(repo / "data" / "flight_acquisition" / "p1_2026-09-25.json")
    summary = status_summary(manifest)
    assert summary["target_count"] == 12
    assert summary["discovery"] == {"BLOCKED_EXTERNAL_AUTH": 12}
    assert summary["playback"] == {"NOT_ATTEMPTED": 12}
    assert summary["discovered_flight_count"] == 0


def test_next_discovery_prefers_nearest_deadline_then_score(tmp_path):
    path = tmp_path / "manifest.json"
    _write(path, _manifest(
        _target("later", "N1", recoverable_from="2026-01-01", recoverable_to="2026-02-01", score=120, days_left=6),
        _target("now", "N2", recoverable_from="2026-01-01", recoverable_to="2026-02-01", score=90, days_left=0),
    ))
    target = next_discovery_target(load_manifest(path))
    assert target is not None
    assert target["acquisition_id"] == "now"


def test_record_discovery_dedupes_and_makes_playback_ready(tmp_path):
    path = tmp_path / "manifest.json"
    _write(path, _manifest(
        _target("p1", "N684JB", recoverable_from="2025-09-29", recoverable_to="2025-10-16")
    ))
    target = record_discovery(
        path,
        "p1",
        [
            {"date": "2025-10-01", "flight_id": "abcdef12"},
            {"date": "2025-10-01", "flight_id": "ABCDEF12"},
            {"date": "2025-10-02", "flight_id": "1234567a"},
        ],
        source="fr24-authenticated-history",
        observed_at="2026-09-25T07:00:00+00:00",
    )
    assert target["discovery_status"] == "DISCOVERED"
    assert target["playback_status"] == "READY"
    assert target["attempt_count"] == 1
    assert target["discovered_flight_ids"] == ["abcdef12", "1234567a"]


def test_record_discovery_rejects_flight_outside_recoverable_window(tmp_path):
    path = tmp_path / "manifest.json"
    _write(path, _manifest(
        _target("p1", "N540DB", recoverable_from="2025-09-25", recoverable_to="2025-11-16")
    ))
    with pytest.raises(AcquisitionReceiptError, match="before recoverable window"):
        record_discovery(
            path,
            "p1",
            [{"date": "2025-09-10", "flight_id": "abcdef12"}],
            source="fr24-authenticated-history",
        )


def test_record_discovery_rejects_non_hex_flight_id(tmp_path):
    path = tmp_path / "manifest.json"
    _write(path, _manifest(
        _target("p1", "N1", recoverable_from="2026-01-01", recoverable_to="2026-02-01")
    ))
    with pytest.raises(AcquisitionReceiptError, match="hexadecimal"):
        record_discovery(
            path,
            "p1",
            [{"date": "2026-01-10", "flight_id": "nothex!"}],
            source="fr24-authenticated-history",
        )


def test_block_auth_increments_attempt_without_spending_playback(tmp_path):
    path = tmp_path / "manifest.json"
    _write(path, _manifest(
        _target("p1", "C6062", recoverable_from="2025-09-25", recoverable_to="2026-09-25")
    ))
    target = record_blocked_auth(
        path,
        "p1",
        reason="FR24 API key unavailable",
        observed_at="2026-09-25T07:00:00+00:00",
    )
    assert target["discovery_status"] == "BLOCKED_EXTERNAL_AUTH"
    assert target["attempt_count"] == 1
    assert target["playback_status"] == "NOT_ATTEMPTED"
    assert target["last_error"] == "FR24 API key unavailable"


def test_export_harvest_carryover_only_emits_discovered_targets(tmp_path):
    manifest = _manifest(
        _target("p1", "N684JB", recoverable_from="2025-09-29", recoverable_to="2025-10-16"),
        _target("p2", "N767PD", recoverable_from="2025-10-01", recoverable_to="2026-06-08"),
    )
    first, second = manifest["targets"]
    first["discovery_status"] = "DISCOVERED"
    first["playback_status"] = "READY"
    first["discovered_flights"] = [
        {
            "identity": "N684JB",
            "date": "2025-10-01",
            "flight_id": "abcdef12",
            "discovery_source": "fr24-authenticated-history",
        }
    ]
    first["discovered_flight_ids"] = ["abcdef12"]
    second["discovery_status"] = "NO_MATCHES"

    output = tmp_path / "_harvest_carryover_test.csv"
    count = export_harvest_carryover(manifest, output)

    assert count == 1
    assert output.read_text(encoding="utf-8").splitlines() == [
        "date,tail,flight_id",
        "2025-10-01,N684JB,abcdef12",
    ]
