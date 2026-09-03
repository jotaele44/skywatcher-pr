"""Enforces the Core / SATIM / FPIM / CORRIM module boundary (requirement 7):
SATIM must contain no flight-behavior logic, FPIM must contain no
terrain-classification logic, and CORRIM must be the only module that
combines SATIM and FPIM outputs. Uses stdlib ast only — no import-linter/
grimp dependency exists in this repo (see docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md).
"""

import ast
from pathlib import Path

from skywatcher.core.module_boundaries import (
    ALLOWED_IMPORTS,
    MODULE_BOUNDARIES,
    MODULE_IMPORT_EXCEPTIONS,
    SHIM_MODULE_BUCKETS,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _files_for_bucket(bucket: str) -> list[Path]:
    files: list[Path] = []
    for pattern in MODULE_BOUNDARIES[bucket]:
        files.extend(sorted(REPO_ROOT.glob(pattern)))
    return files


def _rel_path(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _module_name_for(path: Path) -> str:
    parts = list(path.relative_to(REPO_ROOT).with_suffix("").parts)
    if parts[0] == "src":
        parts = parts[1:]
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _build_module_index() -> dict[str, str]:
    """dotted module name -> bucket, for every file classified in MODULE_BOUNDARIES."""
    index: dict[str, str] = {}
    for bucket in MODULE_BOUNDARIES:
        for path in _files_for_bucket(bucket):
            index[_module_name_for(path)] = bucket
    return index


MODULE_INDEX = _build_module_index()


def _bucket_of(dotted_name: str) -> str | None:
    """Longest-prefix match of an imported dotted name against known modules
    and known backward-compat shims."""
    parts = dotted_name.split(".")
    for i in range(len(parts), 0, -1):
        candidate = ".".join(parts[:i])
        if candidate in MODULE_INDEX:
            return MODULE_INDEX[candidate]
        if candidate in SHIM_MODULE_BUCKETS:
            return SHIM_MODULE_BUCKETS[candidate]
    return None


def _imported_names(py_file: Path) -> list[str]:
    tree = ast.parse(py_file.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue  # intra-package relative import; always same bucket
            if node.module:
                names.append(node.module)
    return names


def test_no_forbidden_cross_boundary_imports():
    violations = []
    for bucket in MODULE_BOUNDARIES:
        if bucket == "legacy":
            continue
        for py_file in _files_for_bucket(bucket):
            rel = _rel_path(py_file)
            exceptions = MODULE_IMPORT_EXCEPTIONS.get(rel, set())
            for imported in _imported_names(py_file):
                target_bucket = _bucket_of(imported)
                if target_bucket is None or target_bucket == bucket:
                    continue
                if target_bucket in ALLOWED_IMPORTS[bucket] or target_bucket in exceptions:
                    continue
                violations.append(f"{rel}: bucket={bucket!r} imports {imported!r} (bucket={target_bucket!r})")
    assert not violations, "\n".join(violations)


def test_legacy_quarantine_not_imported_by_active_modules():
    violations = []
    for bucket in ("core", "satim", "fpim", "corrim"):
        for py_file in _files_for_bucket(bucket):
            for imported in _imported_names(py_file):
                if _bucket_of(imported) == "legacy":
                    violations.append(f"{_rel_path(py_file)} imports quarantined {imported!r}")
    assert not violations, "\n".join(violations)


def test_only_corrim_may_combine_satim_and_fpim():
    violations = []
    for bucket in ("core", "satim", "fpim"):
        for py_file in _files_for_bucket(bucket):
            imported_buckets = {_bucket_of(name) for name in _imported_names(py_file)}
            if {"satim", "fpim"} <= imported_buckets:
                violations.append(f"{_rel_path(py_file)} (bucket={bucket!r}) imports both satim and fpim")
    assert not violations, "\n".join(violations)
