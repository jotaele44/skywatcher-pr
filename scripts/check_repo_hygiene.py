#!/usr/bin/env python3
"""Fail when generated, local, or archive-contamination files are tracked."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path, PurePosixPath

FORBIDDEN_NAMES = {".DS_Store", "__MACOSX", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"}
FORBIDDEN_SUFFIXES = {".pyc", ".pyo", ".log"}
FORBIDDEN_PREFIXES = ("Archive/", "var/", "tile_cache/", "frontend/node_modules/", "frontend/dist/")


def tracked_paths(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True
    )
    return [item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def violations(paths: list[str]) -> list[str]:
    bad: list[str] = []
    for raw in paths:
        path = PurePosixPath(raw)
        if raw.startswith(FORBIDDEN_PREFIXES):
            bad.append(raw)
            continue
        if any(part in FORBIDDEN_NAMES for part in path.parts):
            bad.append(raw)
            continue
        if path.suffix.lower() in FORBIDDEN_SUFFIXES or path.name.startswith("._"):
            bad.append(raw)
    return sorted(set(bad))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    bad = violations(tracked_paths(args.root.resolve()))
    if bad:
        print("Repository hygiene violations:")
        for path in bad:
            print(f"  - {path}")
        return 1
    print("Repository hygiene: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
