#!/usr/bin/env python3
"""Fail when a type checker reports more errors than its committed ceiling.

Usage:
    python3 scripts/check_error_ceiling.py <name> -- <command> [args...]

The command is run as given. Each output line matching the ceiling's regex
counts as one error. The check fails when the count exceeds the ceiling in
configs/quality_ceilings.json. It also fails, whatever the count, when the
command exits with a code outside the entry's ``ok_exit_codes``: a checker with
a known backlog exits non-zero on ordinary errors, but a different code means
the check stopped early (for example mypy's "errors prevented further checking",
exit 2) and the count is incomplete. Exit codes cannot always tell the two
apart: TypeScript 7 exits 1 both for type errors and for a config it cannot
use. So an entry may also list ``incomplete_patterns``; any output line matching
one of them fails the check the same way, whatever the count or exit code.
Without ``ok_exit_codes``, any non-zero exit with no countable errors fails.
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

    for raw in entry.get("incomplete_patterns", []):
        incomplete = re.compile(raw)
        hit = next((line for line in output.splitlines() if incomplete.search(line)), None)
        if hit is not None:
            print(
                f"error-ceiling FAIL {name}: output matches incomplete pattern {raw!r}"
                f" ({hit.strip()[:120]}). Tool failure; the check is incomplete.",
            )
            return 1
    ok_codes = entry.get("ok_exit_codes")
    if ok_codes is not None and proc.returncode not in ok_codes:
        print(
            f"error-ceiling FAIL {name}: exited {proc.returncode}, expected one of"
            f" {sorted(ok_codes)}. Tool failure; the check is incomplete.",
        )
        return 1
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
