"""Deterministic tracked-source ZIP export."""
from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

from .repository_policy import is_export_excluded


def tracked_entries(root: Path) -> list[tuple[str, int]]:
    output = subprocess.run(
        ["git", "ls-files", "--stage", "-z"], cwd=root, check=True, capture_output=True
    ).stdout
    entries: list[tuple[str, int]] = []
    for item in output.split(b"\0"):
        if not item:
            continue
        metadata, raw_path = item.split(b"\t", 1)
        mode = int(metadata.split()[0], 8)
        entries.append((raw_path.decode("utf-8"), mode))
    return sorted(entries)


def export(root: Path, output: Path) -> int:
    entries = [(path, mode) for path, mode in tracked_entries(root) if not is_export_excluded(path)]
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative, mode in entries:
            source = root / relative
            if not source.is_file():
                continue
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            permission = 0o755 if mode == 0o100755 else 0o644
            info.external_attr = (0o100000 | permission) << 16
            archive.writestr(info, source.read_bytes())
    return len(entries)
