"""Unified command-line entry point for the Skywatcher backend/core."""

from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import shutil
import sys
from pathlib import Path
from typing import Any


def _repo_root(value: str | None) -> Path:
    return Path(value).expanduser().resolve() if value else Path.cwd().resolve()


def _doctor(root: Path) -> int:
    checks: dict[str, Any] = {
        "python": {"version": platform.python_version(), "supported": sys.version_info >= (3, 10)},
        "root": str(root),
        "paths": {
            "schemas": (root / "schemas").is_dir(),
            "configs": (root / "configs").is_dir(),
            "frontend_present": (root / "frontend").is_dir(),
            "data_present": (root / "data").is_dir(),
            "runtime_writable": (root / "var").parent.exists(),
        },
        "python_packages": {
            name: importlib.util.find_spec(name) is not None
            for name in ("jsonschema", "PIL", "fitz", "prii_maintenance", "prii_export_utils")
        },
        "executables": {name: shutil.which(name) for name in ("git", "ffmpeg", "tesseract")},
        "policy": {"intent_inference": False, "operational_cueing": False},
    }
    checks["status"] = "healthy" if checks["python"]["supported"] and checks["paths"]["schemas"] else "degraded"
    print(json.dumps(checks, indent=2, sort_keys=True))
    return 0 if checks["status"] == "healthy" else 1


def _validate(root: Path) -> int:
    from jsonschema import validators

    failures: list[str] = []
    count = 0
    for path in sorted((root / "schemas").rglob("*.json")):
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
            validators.validator_for(schema).check_schema(schema)
            count += 1
        except Exception as exc:  # validation command must report every schema failure
            failures.append(f"{path.relative_to(root)}: {exc}")
    print(json.dumps({"schemas_checked": count, "failures": failures}, indent=2))
    return 1 if failures else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="skywatcher")
    parser.add_argument("--root", help="repository root; defaults to current directory")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="report dependency, data-pack, and policy readiness")
    sub.add_parser("validate", help="validate repository JSON Schemas")
    export_parser = sub.add_parser("export-source", help="create a source-only reproducible ZIP")
    export_parser.add_argument("output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = _repo_root(args.root)
    if args.command == "doctor":
        return _doctor(root)
    if args.command == "validate":
        return _validate(root)
    if args.command == "export-source":
        from scripts.export_repository import export

        count = export(root, args.output.expanduser().resolve())
        print(f"Wrote {count} tracked source files to {args.output.expanduser().resolve()}")
        return 0
    raise AssertionError(args.command)
