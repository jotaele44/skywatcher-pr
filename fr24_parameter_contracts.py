"""Contract layer for FR24 visual-analysis parameters.

The contract layer is the enforcement boundary between informal parameter ideas
and registry-ready parameter definitions. It is intentionally stdlib-only and
keeps enum expansion permissive enough for the later allowed-enum registry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any, Iterable, Mapping, Sequence


SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9_]*[a-z0-9]$")


class ParameterContractError(ValueError):
    """Raised when a parameter contract is invalid."""


class ParameterStatus(str, Enum):
    """Lifecycle state of a parameter definition."""

    DRAFT = "draft"
    QUEUED = "queued"
    DEFINED = "defined"
    IMPLEMENTED = "implemented"
    TESTED = "tested"
    EXPORT_READY = "export_ready"
    COMPLETE = "complete"
    DEFERRED = "deferred"
    DEPRECATED = "deprecated"


VALID_PARAMETER_TYPES = {
    "boolean",
    "integer",
    "float",
    "string",
    "datetime",
    "enum",
    "list[string]",
    "list[integer]",
    "list[float]",
    "list[object]",
    "object",
    "json",
    "geometry",
    "wkt",
}

VALID_SOURCE_METHODS = {
    "visual",
    "ocr",
    "geometric",
    "manual",
    "derived",
    "registry",
    "metadata",
    "export",
    "audit",
    "qc",
    "hybrid",
    "deferred",
}

VALID_EXPORT_TARGETS = {
    "observation",
    "visual_parameters",
    "poi_recurrence",
    "poi_layer_recurrence",
    "ilap_tlt_recurrence",
    "small_waterbody_locator",
    "waterbody_recurrence",
    "tile_seam_anomalies",
    "ground_poi_locator",
    "vehicle_cluster_recurrence",
    "land_clearing_recurrence",
    "warehouse_poi_recurrence",
    "container_poi_locator",
    "container_recurrence",
    "container_place_context",
    "sidecar",
    "manifest",
    "audit",
    "deferred",
}

VALID_PARAMETER_ORIGINS = {
    "user_established",
    "assistant_recommended",
    "repo_required",
    "schema_required",
    "export_required",
    "qc_required",
    "future_deferred",
}


def require_snake_case(value: str, field_name: str) -> None:
    """Validate snake_case identifier values."""

    if not isinstance(value, str) or not SNAKE_CASE_RE.match(value):
        raise ParameterContractError(f"{field_name} must be snake_case; got {value!r}")


def normalize_string_sequence(
    values: Iterable[str] | None,
    field_name: str,
    *,
    require_snake_case_values: bool = False,
) -> tuple[str, ...]:
    """Normalize optional string sequences into tuples."""

    if values is None:
        return ()
    if isinstance(values, str):
        raise ParameterContractError(f"{field_name} must be a sequence of strings")
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value:
            raise ParameterContractError(f"{field_name} values must be non-empty strings")
        if require_snake_case_values:
            require_snake_case(value, field_name)
        normalized.append(value)
    return tuple(normalized)


@dataclass(frozen=True)
class ParameterContract:
    """Validated metadata contract for one visual-analysis parameter."""

    parameter_id: str
    family: str
    type: str
    source_method: str
    confidence_field: str | None
    failure_modes: tuple[str, ...]
    export_target: str
    review_rule: str
    implemented_by: str | None = None
    test_required: bool = True
    status: ParameterStatus = ParameterStatus.DRAFT
    required: bool = False
    nullable: bool = True
    allowed_values: tuple[str, ...] = ()
    fixture_required: bool = False
    registry_version: str = "1.0.0"
    parameter_version: str = "1.0.0"
    deprecated: bool = False
    replacement_parameter_id: str | None = None
    created_in_operation: str | None = None
    mapped_operation_ids: tuple[int, ...] = field(default_factory=tuple)
    parameter_origin: str = "repo_required"
    parameter_dependency_ids: tuple[str, ...] = field(default_factory=tuple)
    notes: str = ""

    def __post_init__(self) -> None:
        require_snake_case(self.parameter_id, "parameter_id")
        require_snake_case(self.family, "family")
        if self.type not in VALID_PARAMETER_TYPES:
            raise ParameterContractError(f"unsupported parameter type: {self.type}")
        if self.source_method not in VALID_SOURCE_METHODS:
            raise ParameterContractError(f"unsupported source_method: {self.source_method}")
        if self.export_target not in VALID_EXPORT_TARGETS:
            raise ParameterContractError(f"unsupported export_target: {self.export_target}")
        if self.parameter_origin not in VALID_PARAMETER_ORIGINS:
            raise ParameterContractError(f"unsupported parameter_origin: {self.parameter_origin}")
        if not self.failure_modes:
            raise ParameterContractError("failure_modes must not be empty")
        if not self.review_rule:
            raise ParameterContractError("review_rule must not be empty")
        if self.status in {
            ParameterStatus.IMPLEMENTED,
            ParameterStatus.TESTED,
            ParameterStatus.EXPORT_READY,
            ParameterStatus.COMPLETE,
        } and not self.implemented_by:
            raise ParameterContractError("implemented/export-ready parameters require implemented_by")
        if self.deprecated and not self.replacement_parameter_id:
            raise ParameterContractError("deprecated parameters require replacement_parameter_id")
        if self.required and self.nullable:
            raise ParameterContractError("required parameters must not be nullable")
        if self.type == "enum" and not self.allowed_values:
            raise ParameterContractError("enum parameters require allowed_values")

        normalize_string_sequence(self.failure_modes, "failure_modes", require_snake_case_values=True)
        normalize_string_sequence(self.allowed_values, "allowed_values")
        normalize_string_sequence(
            self.parameter_dependency_ids,
            "parameter_dependency_ids",
            require_snake_case_values=True,
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ParameterContract":
        """Create a contract from a JSON-compatible mapping."""

        values = dict(payload)
        if "status" in values and not isinstance(values["status"], ParameterStatus):
            values["status"] = ParameterStatus(values["status"])
        for key in ("failure_modes", "allowed_values", "parameter_dependency_ids"):
            if key in values:
                values[key] = tuple(values[key])
        if "mapped_operation_ids" in values:
            values["mapped_operation_ids"] = tuple(values["mapped_operation_ids"])
        return cls(**values)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""

        payload = dict(self.__dict__)
        payload["status"] = self.status.value
        payload["failure_modes"] = list(self.failure_modes)
        payload["allowed_values"] = list(self.allowed_values)
        payload["mapped_operation_ids"] = list(self.mapped_operation_ids)
        payload["parameter_dependency_ids"] = list(self.parameter_dependency_ids)
        return payload


def validate_parameter_contracts(contracts: Sequence[ParameterContract]) -> None:
    """Validate a collection for cross-record constraints."""

    seen: set[str] = set()
    for contract in contracts:
        if contract.parameter_id in seen:
            raise ParameterContractError(f"duplicate parameter_id: {contract.parameter_id}")
        seen.add(contract.parameter_id)
