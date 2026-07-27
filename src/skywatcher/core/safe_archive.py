"""Resource-bounded, recoverable ZIP extraction for untrusted bundles."""
from __future__ import annotations

import os
import shutil
import stat
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


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
    for part in normalized.parts:
        if ":" in part:
            raise UnsafeArchiveError(f"colon/alternate-stream path is not allowed: {name!r}")
        if part.endswith((" ", ".")):
            raise UnsafeArchiveError(f"trailing dot/space path is not allowed: {name!r}")
        stem = part.split(".", 1)[0].upper()
        if stem in WINDOWS_RESERVED:
            raise UnsafeArchiveError(f"Windows reserved path is not allowed: {name!r}")
    return normalized


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    return stat.S_ISLNK((info.external_attr >> 16) & 0xFFFF)


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
        ratio = info.file_size / info.compress_size if info.compress_size else (float("inf") if info.file_size else 1.0)
        if ratio > limits.max_compression_ratio:
            raise UnsafeArchiveError(f"archive member compression ratio is excessive: {path}")
        validated.append((info, path))
    return validated


def _remove(path: Path) -> None:
    if not path.exists():
        return
    shutil.rmtree(path) if path.is_dir() else path.unlink()


def safe_extract_zip(source: str | Path, target: str | Path, *, limits: ArchiveLimits = ArchiveLimits(), replace: bool = False) -> Path:
    """Validate, stream-extract, and recoverably promote ``source`` into ``target``."""
    source_path = Path(source).expanduser().resolve()
    target_path = Path(target).expanduser().resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists() and not replace:
        raise FileExistsError(target_path)
    temp_root = Path(tempfile.mkdtemp(prefix=f".{target_path.name}.tmp-", dir=target_path.parent))
    backup = target_path.with_name(f".{target_path.name}.backup-{uuid.uuid4().hex}")
    total_streamed = 0
    try:
        with zipfile.ZipFile(source_path) as archive:
            for info, relative in validate_zip(archive, limits):
                destination = temp_root.joinpath(*relative.parts)
                if info.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                member_streamed = 0
                with archive.open(info, "r") as src, destination.open("xb") as dst:
                    while True:
                        chunk = src.read(1024 * 1024)
                        if not chunk:
                            break
                        member_streamed += len(chunk)
                        total_streamed += len(chunk)
                        if member_streamed > limits.max_member_bytes or total_streamed > limits.max_total_bytes:
                            raise UnsafeArchiveError("streamed archive data exceeds configured limit")
                        dst.write(chunk)
                if member_streamed != info.file_size:
                    raise UnsafeArchiveError(f"archive member size mismatch: {relative}")
        if target_path.exists():
            os.replace(target_path, backup)
        try:
            os.replace(temp_root, target_path)
        except Exception:
            if backup.exists() and not target_path.exists():
                os.replace(backup, target_path)
            raise
        _remove(backup)
        return target_path
    except Exception:
        _remove(temp_root)
        if backup.exists() and not target_path.exists():
            os.replace(backup, target_path)
        raise
