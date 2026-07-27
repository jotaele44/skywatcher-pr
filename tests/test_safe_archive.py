from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from skywatcher.core.safe_archive import UnsafeArchiveError, safe_extract_zip


def _zip(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return path


def test_safe_extract_zip_extracts_valid_bundle(tmp_path):
    source = _zip(tmp_path / "valid.zip", {"bundle/manifest.json": b"{}", "bundle/a.txt": b"a"})
    target = safe_extract_zip(source, tmp_path / "out")
    assert (target / "bundle" / "manifest.json").read_text() == "{}"


@pytest.mark.parametrize("name", ["../escape.txt", "/absolute.txt", "folder/../../escape.txt", "C:/escape.txt"])
def test_safe_extract_zip_rejects_path_traversal(tmp_path, name):
    source = _zip(tmp_path / "bad.zip", {name: b"owned"})
    outside = tmp_path / "escape.txt"
    with pytest.raises(UnsafeArchiveError):
        safe_extract_zip(source, tmp_path / "out")
    assert not outside.exists()
    assert not (tmp_path / "out").exists()
