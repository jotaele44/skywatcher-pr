"""Tests for scripts/check_error_ceiling.py, the type-checker ratchet gate."""

from __future__ import annotations

import json
import sys

import pytest

import scripts.check_error_ceiling as gate


@pytest.fixture()
def ceilings(tmp_path, monkeypatch):
    path = tmp_path / "quality_ceilings.json"
    path.write_text(
        json.dumps({"ceilings": {"demo": {"max_errors": 2, "pattern": ": error:"}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(gate, "CEILINGS", path)
    return path


def _emit(lines: int, code: int = 1) -> list[str]:
    script = f"import sys; print('\\n'.join(['f.py:1: error: x'] * {lines})); sys.exit({code})"
    return [sys.executable, "-c", script]


def test_passes_at_ceiling(ceilings, capsys):
    assert gate.main(["demo", "--", *_emit(2)]) == 0
    assert "at ceiling 2" in capsys.readouterr().out


def test_passes_below_ceiling_and_asks_to_lower(ceilings, capsys):
    assert gate.main(["demo", "--", *_emit(1)]) == 0
    assert "Lower max_errors for demo to 1" in capsys.readouterr().out


def test_fails_above_ceiling(ceilings, capsys):
    assert gate.main(["demo", "--", *_emit(3)]) == 1
    assert "3 errors > ceiling 2" in capsys.readouterr().out


def test_clean_run_passes(ceilings):
    assert gate.main(["demo", "--", *_emit(0, code=0)]) == 0


def test_tool_failure_without_countable_errors_fails(ceilings):
    assert gate.main(["demo", "--", sys.executable, "-c", "raise SystemExit(3)"]) == 1


def test_unknown_name_and_bad_usage(ceilings):
    assert gate.main(["nope", "--", "true"]) == 2
    assert gate.main(["demo"]) == 2


def test_committed_ceilings_are_well_formed():
    data = json.loads(gate.CEILINGS.read_text(encoding="utf-8"))
    assert set(data["ceilings"]) >= {"mypy", "tsc"}
    for entry in data["ceilings"].values():
        assert isinstance(entry["max_errors"], int) and entry["max_errors"] >= 0
        assert entry["pattern"]
