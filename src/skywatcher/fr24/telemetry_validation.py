"""TELEMETRY VALIDATION + FAILURE ACCOUNTING (mission responsibilities 13 & 17)

Physics/consistency validation of reconstructed flight waves (wraps
``fr24.wave_validator``) plus a small, structured failure-accounting helper and a
JSON-schema validation entry point.

``jsonschema`` is imported lazily inside :func:`validate_against_schema` so the
module imports without it; it is a declared dependency and available at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from fr24.wave_validator import (
    MAX_CLIMB_FT_PER_MIN,
    MAX_SPEED_MPH,
    PROHIBITED_LABELS,
    VALIDATOR_VERSION,
    validate_wave,
)

__all__ = [
    "VALIDATOR_VERSION",
    "MAX_SPEED_MPH",
    "MAX_CLIMB_FT_PER_MIN",
    "PROHIBITED_LABELS",
    "validate_wave",
    "FailureLedger",
    "validate_against_schema",
]


@dataclass
class FailureLedger:
    """In-memory accounting of processing failures, mirroring the
    ``processing_failures`` table columns. Deterministic and testable; callers
    persist ``entries`` via the database layer."""

    entries: List[Dict[str, Any]] = field(default_factory=list)

    def record(
        self,
        *,
        stage: str,
        reason: str,
        screenshot_id: Optional[str] = None,
        detail: Optional[str] = None,
    ) -> Dict[str, Any]:
        entry = {
            "stage": stage,
            "reason": reason,
            "screenshot_id": screenshot_id,
            "detail": detail,
        }
        self.entries.append(entry)
        return entry

    def count(self) -> int:
        return len(self.entries)

    def by_stage(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for e in self.entries:
            out[e["stage"]] = out.get(e["stage"], 0) + 1
        return out


def validate_against_schema(instance: Any, schema: Dict[str, Any]) -> List[str]:
    """Validate ``instance`` against a JSON ``schema``; return a list of human
    -readable error strings (empty == valid). Uses ``jsonschema`` lazily and
    supports both draft-07 and 2020-12 schemas (auto-selected by ``$schema``)."""
    from jsonschema import Draft7Validator, Draft202012Validator  # noqa: WPS433

    dialect = str(schema.get("$schema", ""))
    validator_cls = Draft202012Validator if "2020-12" in dialect else Draft7Validator
    validator = validator_cls(schema)
    return [f"{list(e.path)}: {e.message}" for e in validator.iter_errors(instance)]
