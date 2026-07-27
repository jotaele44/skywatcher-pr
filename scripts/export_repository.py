#!/usr/bin/env python3
"""Create a deterministic source-only ZIP without frontend or production data."""

from __future__ import annotations

import argparse
import subprocess
import zipfile
from pathlib import Path

EXCLUDED_PREFIXES = ("frontend/", "data/", "var/", "tile_cache/", "exports/federation/", "reports/runtime/")


def tracked_paths(root: Path) -> list[str]:
    output = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True
    ).stdout
    return sorted(item.decode("utf-8") for item in output.split(b"\0") if item)


def export(root: Path, output: Path) -> int:
    paths = [p for p in tracked_paths(root) if not p.startswith(EXCLUDED_PREFIXES)]
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative in paths:
            source = root / relative
            if not source.is_file():
                continue
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, source.read_bytes())
    return len(paths)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    count = export(args.root.resolve(), args.output.resolve())
    print(f"Wrote {count} tracked source files to {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
