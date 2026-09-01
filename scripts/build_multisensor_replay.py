#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from sensor_replay.core import ReplayError, build_replay_receipt, write_receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a deterministic multisensor replay receipt")
    parser.add_argument("bundle_root", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        receipt = build_replay_receipt(args.bundle_root, args.manifest)
        write_receipt(receipt, args.output)
    except ReplayError as exc:
        parser.error(str(exc))
    print(receipt["content_digest"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
