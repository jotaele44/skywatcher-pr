from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from fr24 import satim_engine, satim_engine_core

ENGINES = (satim_engine, satim_engine_core)


def _write_zip(path: Path, files: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)


@pytest.mark.parametrize(
    "engine",
    ENGINES,
    ids=lambda engine: engine.__name__.rsplit(".", 1)[-1],
)
def test_zip_backed_runs_replace_previous_extraction(tmp_path, engine):
    archive = tmp_path / "input.zip"
    output = tmp_path / "run"
    _write_zip(
        archive,
        {
            "bundle/screenshots/first.txt": "first",
            "bundle/stale.txt": "stale",
        },
    )

    first_root = engine.prepare_input_root(archive, output)
    assert (first_root / "screenshots" / "first.txt").read_text() == "first"
    assert (first_root / "stale.txt").exists()

    _write_zip(archive, {"bundle/screenshots/second.txt": "second"})
    second_root = engine.prepare_input_root(archive, output)

    assert second_root == first_root
    assert (second_root / "screenshots" / "second.txt").read_text() == "second"
    assert not (second_root / "screenshots" / "first.txt").exists()
    assert not (second_root / "stale.txt").exists()


def test_satim_engine_mirror_extraction_parity(tmp_path):
    archive = tmp_path / "input.zip"
    _write_zip(
        archive,
        {
            "bundle/screenshots/frame.txt": "frame",
            "bundle/annotations.json": "{}",
        },
    )

    snapshots = []
    returned_roots = []
    for engine in ENGINES:
        output = tmp_path / engine.__name__.rsplit(".", 1)[-1]
        root = engine.prepare_input_root(archive, output)
        returned_roots.append(root.relative_to(output).as_posix())
        snapshots.append(
            {
                item.relative_to(root).as_posix(): item.read_bytes()
                for item in sorted(root.rglob("*"))
                if item.is_file()
            }
        )

    assert returned_roots == ["_input_unpacked/bundle"] * 2
    assert snapshots[0] == snapshots[1]
