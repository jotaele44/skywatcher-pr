from __future__ import annotations

import csv
import subprocess
from pathlib import Path


def test_import_preserves_all_rows_and_splits_helipads(tmp_path: Path) -> None:
    source = Path("data/reference/puerto_rico_airfields_dataset.csv")
    footprints = tmp_path / "footprints.csv"
    helipads = tmp_path / "helipads.csv"
    report = tmp_path / "report.md"

    result = subprocess.run(
        [
            "python",
            "scripts/import_pr_airspace_footprints.py",
            "--input",
            str(source),
            "--footprints-out",
            str(footprints),
            "--helipads-out",
            str(helipads),
            "--report",
            str(report),
            "--last-verified",
            "2026-06-12",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "rejected=0" in result.stdout

    with source.open(newline="", encoding="utf-8") as handle:
        source_rows = list(csv.DictReader(handle))
    with footprints.open(newline="", encoding="utf-8") as handle:
        footprint_rows = list(csv.DictReader(handle))
    with helipads.open(newline="", encoding="utf-8") as handle:
        helipad_rows = list(csv.DictReader(handle))

    assert len(source_rows) == len(footprint_rows) + len(helipad_rows)
    assert len(helipad_rows) == 7
    assert all(row["helipad_id"].startswith("pr-") for row in helipad_rows)
    assert all(row["footprint_id"].startswith("pr-") for row in footprint_rows)
    assert report.exists()


def test_helipads_include_coordinates(tmp_path: Path) -> None:
    helipads = tmp_path / "helipads.csv"
    subprocess.run(
        [
            "python",
            "scripts/import_pr_airspace_footprints.py",
            "--helipads-out",
            str(helipads),
            "--footprints-out",
            str(tmp_path / "footprints.csv"),
            "--report",
            str(tmp_path / "report.md"),
            "--last-verified",
            "2026-06-12",
        ],
        check=True,
    )
    with helipads.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    assert all(row["latitude"] for row in rows)
    assert all(row["longitude"] for row in rows)
