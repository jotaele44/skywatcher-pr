from __future__ import annotations

import zipfile

import pytest

from satim_engine.safe_archive import UnsafeArchiveError, safe_extract_zip


def test_satim_safe_archive_rejects_traversal(tmp_path):
    source = tmp_path / "bad.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("../escape.csv", "x")
    with pytest.raises(UnsafeArchiveError):
        safe_extract_zip(source, tmp_path / "out")
    assert not (tmp_path / "escape.csv").exists()
