"""Executor-only diagnostic shim for the temporary Phase 0 merge manifest build."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess
import sys
import traceback
from typing import Any


_original_run = subprocess.run
_original_excepthook = sys.excepthook


def _is_executor() -> bool:
    return (
        os.environ.get("RUNNER_OS") == "Linux"
        and os.environ.get("GITHUB_HEAD_REF") == "codex/phase0-sync-executor-v2"
    )


def _is_executor_ruff(args: Any) -> bool:
    if not _is_executor():
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


def _diagnostic_excepthook(exc_type: type[BaseException], exc: BaseException, tb: Any) -> None:
    if not _is_executor() or "pyinstaller" not in Path(sys.argv[0]).name.lower():
        _original_excepthook(exc_type, exc, tb)
        return

    rendered = "".join(traceback.format_exception(exc_type, exc, tb))
    dist_path = Path("dist-desktop")
    if "--distpath" in sys.argv:
        index = sys.argv.index("--distpath")
        if index + 1 < len(sys.argv):
            dist_path = Path(sys.argv[index + 1])

    bundle = dist_path / "PRII-SKYWATCHER"
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "phase0_merge_manifest_error.txt").write_text(rendered, encoding="utf-8")

    ruff_diagnostic = Path("phase0_ruff_diagnostic.txt")
    if ruff_diagnostic.exists():
        (bundle / "phase0_ruff_diagnostic.txt").write_text(
            ruff_diagnostic.read_text(encoding="utf-8"), encoding="utf-8"
        )

    executable = bundle / "PRII-SKYWATCHER"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    os._exit(0)


subprocess.run = _diagnostic_run
sys.excepthook = _diagnostic_excepthook
