"""Executable threshold registry, backed by the governance CSV.

ADR v2.1 A2 authorized thresholds to execute, under two binding conditions:

  1. the threshold carries a complete ADR v2.0 section 12 record, and
  2. every executed value stamps ``{threshold_id, value, status}`` into output.

This module is what makes both true. ``value_of`` refuses to return a value for a
PROHIBITED threshold, and ``stamp`` produces the provenance record callers must attach
so a consumer can always tell an EXECUTABLE_CANDIDATE cutoff from a VALIDATED one.

The registry reads the same CSV the governance test validates, so a threshold cannot
be executed without also being governed.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_THRESHOLD_CSV = (
    _REPO_ROOT / "docs" / "architecture" / "SKYWATCHER_THRESHOLD_REGISTRY_SEED_v2_0.csv"
)

# Statuses that may be executed. CANDIDATE is deliberately absent: a threshold stays
# documentation-only until it is explicitly promoted to EXECUTABLE_CANDIDATE, which is
# the step that forces someone to fill in its section 12 record.
EXECUTABLE_STATUSES = frozenset({"EXECUTABLE_CANDIDATE", "VALIDATED", "CANONICAL"})
PROHIBITED_STATUS = "PROHIBITED"


class ThresholdNotExecutable(RuntimeError):
    """Raised when code tries to execute a threshold governance forbids."""


@dataclass(frozen=True)
class ThresholdSpec:
    threshold_id: str
    owner: str
    raw_value: str
    unit: str
    purpose: str
    status: str
    validation_artifact: str
    failure_behavior: str
    effective_version: str
    supersedes: str = ""

    @property
    def executable(self) -> bool:
        return self.status in EXECUTABLE_STATUSES

    @property
    def value(self) -> Any:
        """The value as a number when it parses as one, else the raw string.

        Some registry rows are rules rather than numbers (ILAP-IDENTITY-PRIORITY holds
        prose), so this cannot assume float.
        """
        text = self.raw_value.strip()
        try:
            return int(text) if text.isdigit() or (
                text.startswith("-") and text[1:].isdigit()
            ) else float(text)
        except ValueError:
            return text

    def stamp(self) -> dict[str, Any]:
        """Provenance record to attach to any output this threshold influenced."""
        return {
            "threshold_id": self.threshold_id,
            "value": self.value,
            "status": self.status,
        }


class ThresholdRegistry:
    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path is not None else DEFAULT_THRESHOLD_CSV
        self._rows: dict[str, ThresholdSpec] = {}
        self._loaded = False

    def load(self) -> int:
        with self._path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                spec = ThresholdSpec(
                    threshold_id=row["threshold_id"].strip(),
                    owner=row["owner"].strip(),
                    raw_value=row["current_value"].strip(),
                    unit=row["unit"].strip(),
                    purpose=row["purpose"].strip(),
                    status=row["status"].strip(),
                    validation_artifact=row["validation_artifact"].strip(),
                    failure_behavior=row["failure_behavior"].strip(),
                    effective_version=row.get("effective_version", "").strip(),
                    supersedes=row.get("supersedes", "").strip(),
                )
                self._rows[spec.threshold_id] = spec
        self._loaded = True
        return len(self._rows)

    def _ensure(self) -> None:
        if not self._loaded:
            self.load()

    def get(self, threshold_id: str) -> ThresholdSpec:
        self._ensure()
        try:
            return self._rows[threshold_id]
        except KeyError:
            raise KeyError(
                f"threshold {threshold_id!r} is not in {self._path.name}; "
                "register it before binding code to it"
            ) from None

    def value_of(self, threshold_id: str) -> Any:
        """The executable value, or a refusal explaining why there isn't one."""
        spec = self.get(threshold_id)
        if spec.status == PROHIBITED_STATUS:
            raise ThresholdNotExecutable(
                f"{threshold_id} is PROHIBITED and must never execute. "
                f"Failure behavior on record: {spec.failure_behavior}"
            )
        if not spec.executable:
            raise ThresholdNotExecutable(
                f"{threshold_id} has status {spec.status}, which is not executable. "
                f"Promote it to EXECUTABLE_CANDIDATE with a complete section 12 record first."
            )
        return spec.value

    def stamp(self, threshold_ids: Iterable[str]) -> list[dict[str, Any]]:
        """Provenance stamps for a set of thresholds, in registry order."""
        return [self.get(tid).stamp() for tid in threshold_ids]

    def threshold_ids(self) -> list[str]:
        self._ensure()
        return sorted(self._rows)

    def executable_ids(self) -> list[str]:
        self._ensure()
        return sorted(tid for tid, spec in self._rows.items() if spec.executable)

    def to_dict(self) -> dict[str, Any]:
        self._ensure()
        return {
            "thresholds": [
                {
                    "threshold_id": s.threshold_id,
                    "owner": s.owner,
                    "value": s.value,
                    "unit": s.unit,
                    "purpose": s.purpose,
                    "status": s.status,
                    "executable": s.executable,
                    "validation_artifact": s.validation_artifact,
                    "failure_behavior": s.failure_behavior,
                    "effective_version": s.effective_version,
                }
                for s in (self._rows[k] for k in sorted(self._rows))
            ]
        }

    def __len__(self) -> int:
        self._ensure()
        return len(self._rows)

    def __contains__(self, threshold_id: object) -> bool:
        self._ensure()
        return threshold_id in self._rows


_DEFAULT: ThresholdRegistry | None = None


def default_registry() -> ThresholdRegistry:
    """Process-wide registry over the committed governance CSV.

    Module constants migrated onto the registry read through this, so the CSV is
    parsed once rather than per import.
    """
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = ThresholdRegistry()
        _DEFAULT.load()
    return _DEFAULT
