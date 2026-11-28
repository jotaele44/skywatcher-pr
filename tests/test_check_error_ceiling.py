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


@pytest.fixture()
def strict_ceilings(tmp_path, monkeypatch):
    path = tmp_path / "quality_ceilings.json"
    path.write_text(
        json.dumps(
            {
                "ceilings": {
                    "demo": {"max_errors": 2, "pattern": ": error:", "ok_exit_codes": [0, 1]}
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(gate, "CEILINGS", path)
    return path


def test_allowed_nonzero_exit_with_errors_passes(strict_ceilings):
    assert gate.main(["demo", "--", *_emit(2, code=1)]) == 0


def test_blocking_exit_under_ceiling_fails(strict_ceilings, capsys):
    # mypy exits 2 when "errors prevented further checking": the count is incomplete.
    assert gate.main(["demo", "--", *_emit(1, code=2)]) == 1
    assert "exited 2" in capsys.readouterr().out


def test_incomplete_pattern_fails_even_with_allowed_exit(tmp_path, monkeypatch, capsys):
    # TypeScript 7 exits 1 for type errors and for a broken config alike.
    path = tmp_path / "quality_ceilings.json"
    path.write_text(
        json.dumps(
            {
                "ceilings": {
                    "demo": {
                        "max_errors": 5,
                        "pattern": "error TS[0-9]+:",
                        "ok_exit_codes": [0, 1],
                        "incomplete_patterns": ["error TS5[0-9]{3}:"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(gate, "CEILINGS", path)
    bad = "import sys; print(\"jsconfig.json(3,5): error TS5102: Option removed.\"); sys.exit(1)"
    assert gate.main(["demo", "--", sys.executable, "-c", bad]) == 1
    assert "incomplete pattern" in capsys.readouterr().out
    ok = "import sys; print(\"a.js(1,1): error TS2339: x\"); sys.exit(1)"
    assert gate.main(["demo", "--", sys.executable, "-c", ok]) == 0


def test_committed_ceilings_are_well_formed():
    data = json.loads(gate.CEILINGS.read_text(encoding="utf-8"))
    assert set(data["ceilings"]) >= {"mypy", "tsc"}
    for entry in data["ceilings"].values():
        assert isinstance(entry["max_errors"], int) and entry["max_errors"] >= 0
        assert entry["pattern"]
        assert 0 in entry["ok_exit_codes"]
