"""Unified command-line entry point for the Skywatcher backend/core."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any


def _repo_root(value: str | None) -> Path:
    if value:
        root = Path(value).expanduser().resolve()
    else:
        root = Path.cwd().resolve()
        for candidate in (root, *root.parents):
            if (candidate / "schemas").is_dir() and (candidate / "pyproject.toml").is_file():
                root = candidate
                break
    return root


def _runtime_writable(root: Path) -> bool:
    try:
        runtime = root / "var"
        runtime.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".doctor-", dir=runtime)
        os.close(fd)
        Path(name).unlink()
        return True
    except OSError:
        return False


def _doctor(root: Path) -> int:
    checks: dict[str, Any] = {
        "python": {"version": platform.python_version(), "supported": sys.version_info >= (3, 10)},
        "root": str(root),
        "paths": {
            "schemas": (root / "schemas").is_dir(),
            "configs": (root / "configs").is_dir(),
            "frontend_present": (root / "frontend").is_dir(),
            "data_present": (root / "data").is_dir(),
            "runtime_writable": _runtime_writable(root),
        },
        "python_packages": {
            name: importlib.util.find_spec(name) is not None
            for name in ("jsonschema", "PIL", "fitz", "prii_maintenance", "prii_export_utils")
        },
        "executables": {name: shutil.which(name) for name in ("git", "ffmpeg", "tesseract")},
        "policy": {"intent_inference": False, "operational_cueing": False},
    }
    required = (
        checks["python"]["supported"]
        and checks["paths"]["schemas"]
        and checks["paths"]["runtime_writable"]
    )
    checks["status"] = "healthy" if required else "degraded"
    print(json.dumps(checks, indent=2, sort_keys=True))
    return 0 if checks["status"] == "healthy" else 1


def _validate(root: Path) -> int:
    from jsonschema import validators

    schema_root = root / "schemas"
    if not schema_root.is_dir():
        print(
            json.dumps(
                {"schemas_checked": 0, "failures": [f"schema directory not found: {schema_root}"]},
                indent=2,
            )
        )
        return 1
    paths = sorted(schema_root.rglob("*.json"))
    if not paths:
        print(
            json.dumps(
                {"schemas_checked": 0, "failures": [f"no JSON Schemas found under {schema_root}"]},
                indent=2,
            )
        )
        return 1
    failures: list[str] = []
    for path in paths:
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
            validators.validator_for(schema).check_schema(schema)
        except Exception as exc:
            failures.append(f"{path.relative_to(root)}: {exc}")
    print(json.dumps({"schemas_checked": len(paths), "failures": failures}, indent=2))
    return 1 if failures else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="skywatcher")
    parser.add_argument("--root", help="repository root containing schemas/configs")
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
        from skywatcher.core.repository_export import export

        count = export(root, args.output.expanduser().resolve())
        print(f"Wrote {count} tracked source files to {args.output.expanduser().resolve()}")
        return 0
    raise AssertionError(args.command)
