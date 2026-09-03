#!/usr/bin/env python3
"""Bounded setup smoke check for federation startup certification.

This verifies that the checked-out repo has the setup metadata and importable
runtime modules needed by the startup/test/export gates. It deliberately avoids
mutating the interpreter with a full dependency reinstall during every audit.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEDERATION_ROOT = ROOT.parent

for package in ("prii_maintenance", "prii_export_utils"):
    package_src = FEDERATION_ROOT / "thehub-pr" / "packages" / package / "src"
    if package_src.exists():
        sys.path.insert(0, str(package_src))

REQUIRED_FILES = [
    "pyproject.toml",
    "uv.lock",
    "server/backend/requirements.txt",
    "scripts/validate_airspace_export.py",
    "scripts/federation_export.py",
]

REQUIRED_MODULES = [
    "PIL",
    "fitz",
    "httpx",
    "jsonschema",
    "openpyxl",
    "pytest",
    "prii_export_utils",
    "prii_maintenance",
]


def main() -> int:
    missing_files = [path for path in REQUIRED_FILES if not (ROOT / path).exists()]
    missing_modules = []
    for module in REQUIRED_MODULES:
        try:
            importlib.import_module(module)
        except Exception as exc:  # pragma: no cover - diagnostic message path
            missing_modules.append(f"{module}: {exc}")

    if missing_files or missing_modules:
        if missing_files:
            print("Missing required setup files:")
            for path in missing_files:
                print(f"- {path}")
        if missing_modules:
            print("Missing required Python modules:")
            for module in missing_modules:
                print(f"- {module}")
        return 1

    print("Skywatcher federation setup smoke passed.")
    print(f"Python: {sys.version.split()[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
