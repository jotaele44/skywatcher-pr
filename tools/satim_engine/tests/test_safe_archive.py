from __future__ import annotations

import inspect
import zipfile
from pathlib import Path

import pytest

import satim_engine.safe_archive as safe_archive_module

UnsafeArchiveError = safe_archive_module.UnsafeArchiveError
safe_extract_zip = safe_archive_module.safe_extract_zip


def test_satim_safe_archive_rejects_traversal(tmp_path):
    source = tmp_path / "bad.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("../escape.csv", "x")
    with pytest.raises(UnsafeArchiveError):
        safe_extract_zip(source, tmp_path / "out")


def test_standalone_contract_has_recoverable_replace_default():
    assert inspect.signature(safe_extract_zip).parameters["replace"].default is False


def test_standalone_replace_rolls_back_after_promotion_failure(tmp_path, monkeypatch):
    target = tmp_path / "out"
    target.mkdir()
    (target / "old").write_text("old", encoding="utf-8")
    source = tmp_path / "new.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("new", "new")

    real_replace = safe_archive_module.os.replace
    failed = False

    def fail_temp_promotion(source_path, destination_path):
        nonlocal failed
        source_path = Path(source_path)
        destination_path = Path(destination_path)
        if not failed and source_path.name.startswith(".out.tmp-") and destination_path == target:
            failed = True
            raise OSError("injected promotion failure")
        return real_replace(source_path, destination_path)

    monkeypatch.setattr(safe_archive_module.os, "replace", fail_temp_promotion)
    with pytest.raises(OSError, match="injected promotion failure"):
        safe_extract_zip(source, target, replace=True)

    assert failed is True
    assert (target / "old").read_text(encoding="utf-8") == "old"
    assert not (target / "new").exists()
    assert not list(tmp_path.glob(".out.tmp-*"))
    assert not list(tmp_path.glob(".out.backup-*"))
