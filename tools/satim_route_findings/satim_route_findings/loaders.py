"""CSV loading helpers for SATIM route findings.

The loaders are intentionally read-only. They never mutate source ledgers.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class Ledger:
    """A loaded CSV ledger."""

    name: str
    path: Path
    fieldnames: tuple[str, ...]
    rows: tuple[dict[str, str], ...]


def resolve_input_dir(input_dir: str | Path) -> Path:
    """Resolve an input directory and require that it exists."""

    path = Path(input_dir).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Input directory does not exist: {path}")
    if not path.is_dir():
        raise NotADirectoryError(f"Input path is not a directory: {path}")
    return path


def load_csv_ledger(input_dir: str | Path, filename: str) -> Ledger:
    """Load one CSV ledger from a directory."""

    base = resolve_input_dir(input_dir)
    path = (base / filename).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Required ledger missing: {filename}")
    if not path.is_file():
        raise FileNotFoundError(f"Ledger path is not a regular file: {path}")

    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = tuple(reader.fieldnames or ())
        rows = tuple(dict(row) for row in reader)
    return Ledger(name=filename, path=path, fieldnames=fieldnames, rows=rows)


def load_required_ledgers(input_dir: str | Path, filenames: Iterable[str]) -> dict[str, Ledger]:
    """Load all required ledgers by filename."""

    return {name: load_csv_ledger(input_dir, name) for name in filenames}
