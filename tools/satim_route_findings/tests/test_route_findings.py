from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from satim_route_findings.loaders import load_required_ledgers
from satim_route_findings.report import run_analysis
from satim_route_findings.schemas import REQUIRED_FILENAMES, validate_ledgers


FIXTURES = Path(__file__).parent / "fixtures"


def _copy_fixtures(tmp_path: Path) -> Path:
    input_dir = tmp_path / "input"
    shutil.copytree(FIXTURES, input_dir)
    return input_dir


def test_schema_validation_accepts_small_fixtures(tmp_path: Path) -> None:
    input_dir = _copy_fixtures(tmp_path)
    ledgers = load_required_ledgers(input_dir, REQUIRED_FILENAMES)
    validate_ledgers(ledgers)


def test_run_analysis_writes_expected_outputs(tmp_path: Path) -> None:
    input_dir = _copy_fixtures(tmp_path)
    output_dir = tmp_path / "out"

    summary = run_analysis(input_dir, output_dir)

    assert summary == {"route_clusters": 4, "fn_candidates": 3, "review_rows": 3}
    assert (output_dir / "route_cluster_summary.csv").exists()
    assert (output_dir / "fn_candidate_summary.csv").exists()
    assert (output_dir / "review_queue.csv").exists()
    assert (output_dir / "route_findings_report.md").exists()


def test_output_order_is_deterministic(tmp_path: Path) -> None:
    input_dir = _copy_fixtures(tmp_path)
    output_a = tmp_path / "out_a"
    output_b = tmp_path / "out_b"

    run_analysis(input_dir, output_a)
    run_analysis(input_dir, output_b)

    for filename in ("route_cluster_summary.csv", "fn_candidate_summary.csv", "review_queue.csv", "route_findings_report.md"):
        assert (output_a / filename).read_text(encoding="utf-8") == (output_b / filename).read_text(encoding="utf-8")


def test_input_tree_is_read_only(tmp_path: Path) -> None:
    input_dir = _copy_fixtures(tmp_path)
    with pytest.raises(ValueError, match="Output directory must not be the input directory"):
        run_analysis(input_dir, input_dir)
    with pytest.raises(ValueError, match="Output directory must not be the input directory"):
        run_analysis(input_dir, input_dir / "nested_output")


def test_cli_smoke(tmp_path: Path) -> None:
    input_dir = _copy_fixtures(tmp_path)
    output_dir = tmp_path / "cli_out"

    result = subprocess.run(
        [sys.executable, "-m", "satim_route_findings.cli", "--input", str(input_dir), "--output", str(output_dir)],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "SATIM route findings complete" in result.stdout
    assert (output_dir / "route_findings_report.md").exists()
