from __future__ import annotations

import inspect
import zipfile

import pytest

from satim_engine.safe_archive import UnsafeArchiveError, safe_extract_zip


def test_satim_safe_archive_rejects_traversal(tmp_path):
    source = tmp_path / "bad.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("../escape.csv", "x")
    with pytest.raises(UnsafeArchiveError):
        safe_extract_zip(source, tmp_path / "out")


def test_standalone_contract_has_recoverable_replace_default():
    assert inspect.signature(safe_extract_zip).parameters["replace"].default is False
