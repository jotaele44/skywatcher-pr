#!/usr/bin/env python3
"""Fail when generated, local, or archive-contamination files are tracked."""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from skywatcher.core.repository_policy import hygiene_violations


def tracked_paths(root: Path) -> list[str]:
    result = subprocess.run(["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True)
    return [item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    bad = hygiene_violations(tracked_paths(args.root.resolve()))
    if bad:
        print("Repository hygiene violations:")
        for path in bad:
            print(f"  - {path}")
        return 1
    print("Repository hygiene: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
