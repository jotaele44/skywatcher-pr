"""Allowed enum registry and signal-group router for FR24 visual analysis."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


DEFAULT_REGISTRY_PATH = Path("data/reference/fr24_allowed_enum_registry.json")


class AllowedEnumRegistryError(ValueError):
    """Raised when the allowed enum registry is invalid."""


@dataclass(frozen=True)
class SignalGroupRoute:
    """Routing metadata for one signal group."""

    signal_group_id: str
    owned_by_module: str
    pipeline_stage: str
    export_targets: tuple[str, ...]
    recurrence_enabled: bool
    suppression_dependencies: tuple[str, ...]
    interpretation_guardrail: str

    @classmethod
    def from_mapping(cls, signal_group_id: str, payload: Mapping[str, Any]) -> "SignalGroupRoute":
        return cls(
            signal_group_id=signal_group_id,
            owned_by_module=str(payload["owned_by_module"]),
            pipeline_stage=str(payload["pipeline_stage"]),
            export_targets=tuple(payload.get("export_targets", ())),
            recurrence_enabled=bool(payload.get("recurrence_enabled", False)),
            suppression_dependencies=tuple(payload.get("suppression_dependencies", ())),
            interpretation_guardrail=str(payload.get("interpretation_guardrail", "")),
        )


@dataclass(frozen=True)
class ModuleCapability:
    """Declared signal groups and exports owned by one module."""

    module: str
    pipeline_stage: str
    handled_signal_groups: tuple[str, ...]
    emits: tuple[str, ...]
    depends_on: tuple[str, ...]

    @classmethod
    def from_mapping(cls, module: str, payload: Mapping[str, Any]) -> "ModuleCapability":
        return cls(
            module=module,
            pipeline_stage=str(payload["pipeline_stage"]),
            handled_signal_groups=tuple(payload.get("handled_signal_groups", ())),
            emits=tuple(payload.get("emits", ())),
            depends_on=tuple(payload.get("depends_on", ())),
        )


@dataclass(frozen=True)
class AllowedEnumRegistry:
    """Loaded allowed-enum registry plus module routing maps."""

    payload: Mapping[str, Any]

    @property
    def pipeline_stage_order(self) -> tuple[str, ...]:
        return tuple(self.payload["pipeline_stage_order"])

    @property
    def allowed_families(self) -> set[str]:
        return set(self.payload["allowed_families"])

    @property
    def allowed_source_methods(self) -> set[str]:
        return set(self.payload["allowed_source_methods"])

    @property
    def allowed_export_targets(self) -> set[str]:
        return set(self.payload["allowed_export_targets"])

    @property
    def signal_group_routes(self) -> dict[str, SignalGroupRoute]:
        return {
            signal_group_id: SignalGroupRoute.from_mapping(signal_group_id, route)
            for signal_group_id, route in self.payload["signal_group_export_map"].items()
        }

    @property
    def module_capabilities(self) -> dict[str, ModuleCapability]:
        return {
            module: ModuleCapability.from_mapping(module, capability)
            for module, capability in self.payload["module_capability_map"].items()
        }

    def validate(self) -> None:
        """Validate registry routing integrity."""

        required_top_level = {
            "registry_id",
            "registry_version",
            "pipeline_stage_order",
            "allowed_families",
            "allowed_source_methods",
            "allowed_export_targets",
            "module_capability_map",
            "signal_group_export_map",
            "validation_rules",
        }
        missing = sorted(required_top_level - set(self.payload))
        if missing:
            raise AllowedEnumRegistryError(f"registry missing top-level keys: {missing}")

        stages = self.pipeline_stage_order
        if len(stages) != len(set(stages)):
            raise AllowedEnumRegistryError("pipeline_stage_order contains duplicates")
        if "tile_suppression" not in stages or "ground_context" not in stages:
            raise AllowedEnumRegistryError("tile_suppression and ground_context stages are required")
        if stages.index("tile_suppression") >= stages.index("ground_context"):
            raise AllowedEnumRegistryError("tile_suppression must precede ground_context")

        allowed_exports = self.allowed_export_targets
        allowed_families = self.allowed_families
        module_caps = self.module_capabilities
        routes = self.signal_group_routes

        for module, capability in module_caps.items():
            if capability.pipeline_stage not in stages:
                raise AllowedEnumRegistryError(f"module {module} uses unknown stage {capability.pipeline_stage}")
            unknown_exports = sorted(set(capability.emits) - allowed_exports)
            if unknown_exports:
                raise AllowedEnumRegistryError(f"module {module} emits unknown exports: {unknown_exports}")
            unknown_families = sorted(set(capability.handled_signal_groups) - allowed_families)
            if unknown_families:
                raise AllowedEnumRegistryError(
                    f"module {module} handles unknown signal groups: {unknown_families}"
                )

        for signal_group_id, route in routes.items():
            if signal_group_id not in allowed_families:
                raise AllowedEnumRegistryError(f"signal group {signal_group_id} is not an allowed family")
            if route.owned_by_module not in module_caps:
                raise AllowedEnumRegistryError(
                    f"signal group {signal_group_id} references unknown module {route.owned_by_module}"
                )
            capability = module_caps[route.owned_by_module]
            if signal_group_id not in capability.handled_signal_groups:
                raise AllowedEnumRegistryError(
                    f"signal group {signal_group_id} is not declared by {route.owned_by_module}"
                )
            if route.pipeline_stage != capability.pipeline_stage:
                raise AllowedEnumRegistryError(
                    f"signal group {signal_group_id} stage does not match owner module stage"
                )
            unknown_exports = sorted(set(route.export_targets) - allowed_exports)
            if unknown_exports:
                raise AllowedEnumRegistryError(
                    f"signal group {signal_group_id} exports unknown targets: {unknown_exports}"
                )

        recurrence_module = module_caps.get("fr24_poi_recurrence.py")
        if recurrence_module is None:
            raise AllowedEnumRegistryError("fr24_poi_recurrence.py capability is required")
        forbidden_visual_groups = {
            "vehicle_cluster_signature",
            "land_clearing_signature",
            "unlabeled_warehouse_signature",
            "pool_signature",
            "seam_anomaly_detection",
        }
        overlap = forbidden_visual_groups.intersection(recurrence_module.handled_signal_groups)
        if overlap:
            raise AllowedEnumRegistryError(
                f"recurrence module must not own visual detection signal groups: {sorted(overlap)}"
            )

    def route_for(self, signal_group_id: str) -> SignalGroupRoute:
        """Return routing metadata for a signal group."""

        try:
            return self.signal_group_routes[signal_group_id]
        except KeyError as exc:
            raise AllowedEnumRegistryError(f"unknown signal group route: {signal_group_id}") from exc

    def capability_for(self, module: str) -> ModuleCapability:
        """Return capability metadata for a module."""

        try:
            return self.module_capabilities[module]
        except KeyError as exc:
            raise AllowedEnumRegistryError(f"unknown module capability: {module}") from exc


def load_allowed_enum_registry(path: str | Path = DEFAULT_REGISTRY_PATH) -> AllowedEnumRegistry:
    """Load and validate the allowed enum registry."""

    registry_path = Path(path)
    with registry_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    registry = AllowedEnumRegistry(payload=payload)
    registry.validate()
    return registry
