#!/usr/bin/env python3
"""Fail when a type checker reports more errors than its committed ceiling.

Usage:
    python3 scripts/check_error_ceiling.py <name> -- <command> [args...]

The command is run as given. Each output line matching the ceiling's regex
counts as one error. The check fails when the count exceeds the ceiling in
configs/quality_ceilings.json and passes otherwise; the command's own exit
status is ignored, because a checker with a known backlog always exits non-zero.
When the count drops below the ceiling, the script says so, so the ceiling can
be lowered in the same change. Stdlib only.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

CEILINGS = Path(__file__).resolve().parent.parent / "configs" / "quality_ceilings.json"


def main(argv: list[str]) -> int:
    if len(argv) < 3 or argv[1] != "--":
        print(__doc__, file=sys.stderr)
        return 2
    name, command = argv[0], argv[2:]
    ceilings = json.loads(CEILINGS.read_text(encoding="utf-8"))["ceilings"]
    if name not in ceilings:
        print(f"error-ceiling: unknown name {name!r}; known: {sorted(ceilings)}", file=sys.stderr)
        return 2
    entry = ceilings[name]
    ceiling = int(entry["max_errors"])
    pattern = re.compile(entry["pattern"])

    proc = subprocess.run(command, capture_output=True, text=True, check=False)
    output = proc.stdout + proc.stderr
    sys.stdout.write(output)
    count = sum(1 for line in output.splitlines() if pattern.search(line))

    if count == 0 and proc.returncode != 0:
        print(
            f"error-ceiling: {name} exited {proc.returncode} with no countable errors;"
            " treating as a tool failure",
            file=sys.stderr,
        )
        return 1
    if count > ceiling:
        print(
            f"error-ceiling FAIL {name}: {count} errors > ceiling {ceiling}."
            " Fix the new errors; do not raise the ceiling."
        )
        return 1
    if count < ceiling:
        print(
            f"error-ceiling PASS {name}: {count} errors, ceiling {ceiling}."
            f" Lower max_errors for {name} to {count} in {CEILINGS.name}."
        )
    else:
        print(f"error-ceiling PASS {name}: {count} errors, at ceiling {ceiling}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
