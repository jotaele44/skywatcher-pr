"""Setuptools bridge for the mixed root/src layout during Phase 0 migration.

The canonical Skywatcher package lives in ``src/skywatcher``. Existing root
modules and packages remain installable compatibility surfaces until their
planned package migration is complete.
"""
from pathlib import Path

from setuptools import find_packages, setup

ROOT = Path(__file__).parent
PY_MODULES = sorted(
    path.stem
    for path in ROOT.glob("*.py")
    if path.name not in {"setup.py"} and not path.name.startswith("_")
)
PACKAGES = sorted(set(find_packages(".") + find_packages("src")))

setup(
    packages=PACKAGES,
    package_dir={"skywatcher": "src/skywatcher"},
    py_modules=PY_MODULES,
)
