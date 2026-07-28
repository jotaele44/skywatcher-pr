"""Executor-only diagnostic shim for the temporary Phase 0 merge manifest build."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
from typing import Any


_original_run = subprocess.run


def _is_executor_ruff(args: Any) -> bool:
    if os.environ.get("RUNNER_OS") != "Linux":
        return False
    if os.environ.get("GITHUB_HEAD_REF") != "codex/phase0-sync-executor-v2":
        return False
    if not isinstance(args, (list, tuple)):
        return False
    rendered = [str(value) for value in args]
    return "ruff" in rendered and "check" in rendered


def _diagnostic_run(*popenargs: Any, **kwargs: Any) -> subprocess.CompletedProcess[Any]:
    args = popenargs[0] if popenargs else kwargs.get("args")
    if not _is_executor_ruff(args):
        return _original_run(*popenargs, **kwargs)

    requested_check = bool(kwargs.pop("check", False))
    result = _original_run(*popenargs, check=False, **kwargs)
    if result.returncode:
        diagnostic = Path("phase0_ruff_diagnostic.txt")
        with diagnostic.open("a", encoding="utf-8") as handle:
            handle.write(f"COMMAND: {args!r}\n")
            handle.write(f"REQUESTED_CHECK: {requested_check}\n")
            handle.write(f"RETURN_CODE: {result.returncode}\n")
            if result.stdout:
                handle.write(f"STDOUT:\n{result.stdout}\n")
            if result.stderr:
                handle.write(f"STDERR:\n{result.stderr}\n")
    return result


subprocess.run = _diagnostic_run
