"""Standalone safe ZIP extraction for the distributable SATIM package."""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath


class UnsafeArchiveError(ValueError):
    pass


def _path(name: str) -> PurePosixPath:
    if not name or "\x00" in name:
        raise UnsafeArchiveError("invalid archive member name")
    path = PurePosixPath(name.replace("\\", "/"))
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise UnsafeArchiveError(f"unsafe archive path: {name!r}")
    if path.parts and ":" in path.parts[0]:
        raise UnsafeArchiveError(f"drive-qualified archive path: {name!r}")
    return path


def safe_extract_zip(source: str | Path, target: str | Path) -> Path:
    source_path = Path(source).resolve()
    target_path = Path(target).resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source_path) as archive:
        infos = archive.infolist()
        if len(infos) > 10_000:
            raise UnsafeArchiveError("archive contains too many entries")
        total = 0
        seen: set[str] = set()
        checked = []
        for info in infos:
            relative = _path(info.filename)
            key = relative.as_posix().casefold()
            if key in seen:
                raise UnsafeArchiveError(f"duplicate archive destination: {relative}")
            seen.add(key)
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise UnsafeArchiveError(f"symbolic links are not allowed: {relative}")
            if info.flag_bits & 0x1:
                raise UnsafeArchiveError(f"encrypted member is not supported: {relative}")
            if info.file_size > 512 * 1024 * 1024:
                raise UnsafeArchiveError(f"member exceeds size limit: {relative}")
            total += info.file_size
            if total > 2 * 1024 * 1024 * 1024:
                raise UnsafeArchiveError("expanded archive exceeds size limit")
            ratio = info.file_size / info.compress_size if info.compress_size else (float("inf") if info.file_size else 1.0)
            if ratio > 200:
                raise UnsafeArchiveError(f"excessive compression ratio: {relative}")
            checked.append((info, relative))

        temp = Path(tempfile.mkdtemp(prefix=f".{target_path.name}.tmp-", dir=target_path.parent))
        try:
            for info, relative in checked:
                destination = temp.joinpath(*relative.parts)
                if info.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as src, destination.open("xb") as dst:
                        shutil.copyfileobj(src, dst, length=1024 * 1024)
            if target_path.exists():
                shutil.rmtree(target_path) if target_path.is_dir() else target_path.unlink()
            os.replace(temp, target_path)
        except Exception:
            shutil.rmtree(temp, ignore_errors=True)
            raise
    return target_path
