#!/usr/bin/env python3
"""Create a deterministic source-only ZIP without frontend or production data."""
from __future__ import annotations

import argparse
from pathlib import Path

from skywatcher.core.repository_export import export


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
