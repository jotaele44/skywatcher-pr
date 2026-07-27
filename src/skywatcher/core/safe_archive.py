"""Resource-bounded ZIP extraction for untrusted research bundles."""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


class UnsafeArchiveError(ValueError):
    """Raised when an archive violates path or resource-safety policy."""


@dataclass(frozen=True)
class ArchiveLimits:
    max_files: int = 10_000
    max_member_bytes: int = 512 * 1024 * 1024
    max_total_bytes: int = 2 * 1024 * 1024 * 1024
    max_compression_ratio: float = 200.0


def _normalized_member(name: str) -> PurePosixPath:
    if not name or "\x00" in name:
        raise UnsafeArchiveError("archive member has an empty or NUL-containing name")
    normalized = PurePosixPath(name.replace("\\", "/"))
    if normalized.is_absolute() or any(part in {"", ".", ".."} for part in normalized.parts):
        raise UnsafeArchiveError(f"unsafe archive path: {name!r}")
    if normalized.parts and ":" in normalized.parts[0]:
        raise UnsafeArchiveError(f"drive-qualified archive path: {name!r}")
    return normalized


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_ISLNK(mode)


def validate_zip(archive: zipfile.ZipFile, limits: ArchiveLimits = ArchiveLimits()) -> list[tuple[zipfile.ZipInfo, PurePosixPath]]:
    infos = archive.infolist()
    if len(infos) > limits.max_files:
        raise UnsafeArchiveError(f"archive has {len(infos)} entries; limit is {limits.max_files}")

    total = 0
    seen: set[str] = set()
    validated: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
    for info in infos:
        path = _normalized_member(info.filename)
        key = path.as_posix().casefold()
        if key in seen:
            raise UnsafeArchiveError(f"duplicate archive destination: {path}")
        seen.add(key)
        if info.flag_bits & 0x1:
            raise UnsafeArchiveError(f"encrypted member is not supported: {path}")
        if _is_symlink(info):
            raise UnsafeArchiveError(f"symbolic links are not allowed: {path}")
        if info.file_size > limits.max_member_bytes:
            raise UnsafeArchiveError(f"archive member exceeds size limit: {path}")
        total += info.file_size
        if total > limits.max_total_bytes:
            raise UnsafeArchiveError("archive expanded size exceeds configured limit")
        if info.compress_size == 0:
            ratio = float("inf") if info.file_size else 1.0
        else:
            ratio = info.file_size / info.compress_size
        if ratio > limits.max_compression_ratio:
            raise UnsafeArchiveError(f"archive member compression ratio is excessive: {path}")
        validated.append((info, path))
    return validated


def safe_extract_zip(
    source: str | Path,
    target: str | Path,
    *,
    limits: ArchiveLimits = ArchiveLimits(),
    replace: bool = True,
) -> Path:
    """Validate and atomically extract ``source`` into ``target``.

    No destination content is promoted until every member has passed validation
    and streamed extraction has completed successfully.
    """

    source_path = Path(source).expanduser().resolve()
    target_path = Path(target).expanduser().resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(source_path) as archive:
        members = validate_zip(archive, limits)
        temp_root = Path(tempfile.mkdtemp(prefix=f".{target_path.name}.tmp-", dir=target_path.parent))
        try:
            for info, relative in members:
                destination = temp_root.joinpath(*relative.parts)
                if info.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info, "r") as src, destination.open("xb") as dst:
                    shutil.copyfileobj(src, dst, length=1024 * 1024)
            if target_path.exists():
                if not replace:
                    raise FileExistsError(target_path)
                if target_path.is_dir():
                    shutil.rmtree(target_path)
                else:
                    target_path.unlink()
            os.replace(temp_root, target_path)
        except Exception:
            shutil.rmtree(temp_root, ignore_errors=True)
            raise
    return target_path
