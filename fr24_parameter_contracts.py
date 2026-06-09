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
            raise ParameterContractError(f"{field_name} must contain non-empty strings")
        if require_snake_case_values:
            require_snake_case(value, field_name)
        if value not in normalized:
            normalized.append(value)
    return tuple(normalized)


def normalize_int_sequence(values: Iterable[int] | None, field_name: str) -> tuple[int, ...]:
    """Normalize optional integer sequences into tuples."""

    if values is None:
        return ()
    if isinstance(values, (str, bytes)):
        raise ParameterContractError(f"{field_name} must be a sequence of integers")
    normalized: list[int] = []
    for value in values:
        if not isinstance(value, int):
            raise ParameterContractError(f"{field_name} must contain integers")
        if value not in normalized:
            normalized.append(value)
    return tuple(normalized)


@dataclass(frozen=True)
class ParameterContract:
    """Registry-ready contract for one FR24 parameter."""

    parameter_id: str
    family: str
    type: str
    source_method: str
    confidence_field: str | None
    failure_modes: Sequence[str]
    export_target: str
    review_rule: str
    implemented_by: str | None
    test_required: bool
    status: ParameterStatus | str
    required: bool = False
    nullable: bool = True
    allowed_values: Sequence[str] = field(default_factory=tuple)
    default_value: Any = None
    fixture_required: bool = False
    registry_version: str = "1.0.0"
    parameter_version: str = "1.0.0"
    deprecated: bool = False
    replacement_parameter_id: str | None = None
    created_in_operation: int | None = None
    mapped_operation_ids: Sequence[int] = field(default_factory=tuple)
    parameter_origin: str = "assistant_recommended"
    parameter_origin_note: str | None = None
    parameter_dependency_ids: Sequence[str] = field(default_factory=tuple)
    notes: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", ParameterStatus(self.status))
        object.__setattr__(
            self,
            "failure_modes",
            normalize_string_sequence(
                self.failure_modes,
                "failure_modes",
                require_snake_case_values=True,
            ),
        )
        object.__setattr__(
            self,
            "allowed_values",
            normalize_string_sequence(self.allowed_values, "allowed_values"),
        )
        object.__setattr__(
            self,
            "mapped_operation_ids",
            normalize_int_sequence(self.mapped_operation_ids, "mapped_operation_ids"),
        )
        object.__setattr__(
            self,
            "parameter_dependency_ids",
            normalize_string_sequence(
                self.parameter_dependency_ids,
                "parameter_dependency_ids",
                require_snake_case_values=True,
            ),
        )
        self.validate()

    def validate(self) -> None:
        """Validate the parameter contract."""

        require_snake_case(self.parameter_id, "parameter_id")
        require_snake_case(self.family, "family")
        if self.confidence_field is not None:
            require_snake_case(self.confidence_field, "confidence_field")
        if self.replacement_parameter_id is not None:
            require_snake_case(self.replacement_parameter_id, "replacement_parameter_id")
        if self.type not in VALID_PARAMETER_TYPES:
            raise ParameterContractError(f"unsupported parameter type: {self.type!r}")
        if self.source_method not in VALID_SOURCE_METHODS:
            raise ParameterContractError(f"unsupported source_method: {self.source_method!r}")
        if self.export_target not in VALID_EXPORT_TARGETS:
            raise ParameterContractError(f"unsupported export_target: {self.export_target!r}")
        if self.parameter_origin not in VALID_PARAMETER_ORIGINS:
            raise ParameterContractError(f"unsupported parameter_origin: {self.parameter_origin!r}")
        if not self.failure_modes:
            raise ParameterContractError("failure_modes must contain at least one value")
        if not isinstance(self.review_rule, str) or not self.review_rule:
            raise ParameterContractError("review_rule is required")
        if self.status in {
            ParameterStatus.IMPLEMENTED,
            ParameterStatus.TESTED,
            ParameterStatus.EXPORT_READY,
            ParameterStatus.COMPLETE,
        } and not self.implemented_by:
            raise ParameterContractError("implemented parameters require implemented_by")
        if self.deprecated and not self.replacement_parameter_id:
            raise ParameterContractError("deprecated parameters require replacement_parameter_id")
        if self.required and self.nullable:
            raise ParameterContractError("required parameters cannot be nullable")
        if self.type == "enum" and not self.allowed_values:
            raise ParameterContractError("enum parameters require allowed_values")
        if self.created_in_operation is not None and self.created_in_operation < 0:
            raise ParameterContractError("created_in_operation must be non-negative")

    @property
    def is_registry_ready(self) -> bool:
        """Whether this contract is complete enough for registry inclusion."""

        return self.status not in {ParameterStatus.DRAFT, ParameterStatus.DEPRECATED}

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible registry payload."""

        return {
            "parameter_id": self.parameter_id,
            "family": self.family,
            "type": self.type,
            "source_method": self.source_method,
            "required": self.required,
            "nullable": self.nullable,
            "allowed_values": list(self.allowed_values),
            "default_value": self.default_value,
            "confidence_field": self.confidence_field,
            "failure_modes": list(self.failure_modes),
            "export_target": self.export_target,
            "review_rule": self.review_rule,
            "implemented_by": self.implemented_by,
            "test_required": self.test_required,
            "fixture_required": self.fixture_required,
            "status": self.status.value,
            "registry_version": self.registry_version,
            "parameter_version": self.parameter_version,
            "deprecated": self.deprecated,
            "replacement_parameter_id": self.replacement_parameter_id,
            "created_in_operation": self.created_in_operation,
            "mapped_operation_ids": list(self.mapped_operation_ids),
            "parameter_origin": self.parameter_origin,
            "parameter_origin_note": self.parameter_origin_note,
            "parameter_dependency_ids": list(self.parameter_dependency_ids),
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ParameterContract":
        """Create a contract from a mapping."""

        return cls(**dict(payload))


def validate_parameter_contracts(contracts: Iterable[ParameterContract | Mapping[str, Any]]) -> list[ParameterContract]:
    """Validate contracts and reject duplicate parameter IDs."""

    normalized: list[ParameterContract] = []
    seen: set[str] = set()
    for contract in contracts:
        item = contract if isinstance(contract, ParameterContract) else ParameterContract.from_dict(contract)
        if item.parameter_id in seen:
            raise ParameterContractError(f"duplicate parameter_id: {item.parameter_id}")
        seen.add(item.parameter_id)
        normalized.append(item)
    return normalized
