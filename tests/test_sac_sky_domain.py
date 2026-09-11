from __future__ import annotations

import json
from pathlib import Path

import pytest

from skywatcher.core.sky_correlation import ALL_GATES, classify_candidate

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "data" / "sky_events" / "sac_seed_2026-09-11.jsonl"


def _gates(**overrides: str) -> dict[str, str]:
    gates = {name: "NOT_APPLICABLE" for name in ALL_GATES}
    gates["time"] = "PASS"
    gates["visibility"] = "PASS"
    gates.update(overrides)
    return gates


def test_seed_fixture_ids_and_urls_are_bounded_and_unique() -> None:
    rows = [json.loads(line) for line in FIXTURES.read_text(encoding="utf-8").splitlines() if line.strip()]
    ids = [row["sky_event_id"] for row in rows]
    assert len(rows) == 4
    assert len(ids) == len(set(ids))
    for row in rows:
        assert row["source_id"] == "sac-pr"
        assert row["timezone"] == "America/Puerto_Rico"
        assert "fbclid=" not in row["source_url_canonical"]
        assert "utm_" not in row["source_url_canonical"]
        assert row["classification_state"] == "NOT_CORRELATED"


def test_positive_candidate_requires_material_passes() -> None:
    assert classify_candidate(_gates(location="PASS", azimuth="PASS", trajectory="PASS")) == "MATCHED"


def test_false_azimuth_falsifies_candidate() -> None:
    assert classify_candidate(_gates(location="PASS", azimuth="FAIL", trajectory="PASS")) == "CONTRADICTED"


def test_false_trajectory_falsifies_candidate() -> None:
    assert classify_candidate(_gates(location="PASS", azimuth="PASS", trajectory="FAIL")) == "CONTRADICTED"


def test_time_only_match_cannot_match() -> None:
    gates = _gates()
    for name in ("location", "azimuth", "elevation", "trajectory", "duration", "appearance", "upstream_identity"):
        gates[name] = "UNKNOWN"
    assert classify_candidate(gates) == "UNRESOLVED"


def test_partial_preserves_unknown_material_evidence() -> None:
    gates = _gates(location="PASS", azimuth="UNKNOWN", trajectory="PASS")
    assert classify_candidate(gates) == "PARTIAL"


def test_missing_gate_fails_closed() -> None:
    gates = _gates()
    gates.pop("azimuth")
    with pytest.raises(ValueError, match="missing gates"):
        classify_candidate(gates)
