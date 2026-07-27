from __future__ import annotations

import stat
import zipfile
from pathlib import Path

import pytest

from skywatcher.core.safe_archive import ArchiveLimits, UnsafeArchiveError, safe_extract_zip


def _zip(path: Path, members: list[tuple[str, bytes, int | None]]) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content, mode in members:
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            if mode is not None:
                info.external_attr = mode << 16
            archive.writestr(info, content)
    return path


def test_valid_and_refuses_existing_by_default(tmp_path):
    source = _zip(tmp_path / "valid.zip", [("bundle/a.txt", b"a", None)])
    target = safe_extract_zip(source, tmp_path / "out")
    assert (target / "bundle/a.txt").read_bytes() == b"a"
    with pytest.raises(FileExistsError):
        safe_extract_zip(source, target)


@pytest.mark.parametrize(
    "name",
    ["../x", "/x", "a/../../x", "C:/x", "a:b", "CON.txt", "folder/LPT1", "trail. /x"],
)
def test_rejects_unsafe_paths(tmp_path, name):
    source = _zip(tmp_path / "bad.zip", [(name, b"x", None)])
    with pytest.raises(UnsafeArchiveError):
        safe_extract_zip(source, tmp_path / "out")


def test_rejects_symlink_duplicate_and_ratio(tmp_path):
    symlink = _zip(tmp_path / "symlink.zip", [("link", b"target", stat.S_IFLNK | 0o777)])
    with pytest.raises(UnsafeArchiveError):
        safe_extract_zip(symlink, tmp_path / "a")
    duplicate = _zip(tmp_path / "dup.zip", [("A.txt", b"1", None), ("a.txt", b"2", None)])
    with pytest.raises(UnsafeArchiveError):
        safe_extract_zip(duplicate, tmp_path / "b")
    ratio = _zip(tmp_path / "ratio.zip", [("x", b"0" * 4096, None)])
    with pytest.raises(UnsafeArchiveError):
        safe_extract_zip(
            ratio,
            tmp_path / "c",
            limits=ArchiveLimits(max_compression_ratio=1.0),
        )


def test_replace_preserves_new_content(tmp_path):
    target = tmp_path / "out"
    target.mkdir()
    (target / "old").write_text("old")
    source = _zip(tmp_path / "new.zip", [("new", b"new", None)])
    safe_extract_zip(source, target, replace=True)
    assert not (target / "old").exists()
    assert (target / "new").read_text() == "new"
