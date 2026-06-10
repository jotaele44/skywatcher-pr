"""Config-default loader and validator for FR24 visual signal scoring."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from fr24_allowed_enums import AllowedEnumRegistry, load_allowed_enum_registry


DEFAULT_CONFIG_PATH = Path("data/reference/fr24_config_defaults.json")


class ConfigDefaultsError(ValueError):
    """Raised when FR24 config defaults are invalid."""


@dataclass(frozen=True)
class SignalGroupConfig:
    """Scoring defaults for a single signal group."""

    signal_group_id: str
    weights: Mapping[str, float]
    review_thresholds: Mapping[str, float]
    suppression_multipliers: Mapping[str, float]
    defaults: Mapping[str, Any]

    @classmethod
    def from_mapping(cls, signal_group_id: str, payload: Mapping[str, Any]) -> "SignalGroupConfig":
        return cls(
            signal_group_id=signal_group_id,
            weights={key: float(value) for key, value in payload.get("weights", {}).items()},
            review_thresholds={key: float(value) for key, value in payload.get("review_thresholds", {}).items()},
            suppression_multipliers={
                key: float(value) for key, value in payload.get("suppression_multipliers", {}).items()
            },
            defaults=dict(payload.get("defaults", {})),
        )


@dataclass(frozen=True)
class ConfigDefaults:
    """Loaded scoring/suppression defaults for FR24 visual analysis."""

    payload: Mapping[str, Any]

    @property
    def pipeline_stage_order(self) -> tuple[str, ...]:
        return tuple(self.payload["pipeline_stage_order"])

    @property
    def threshold_groups(self) -> Mapping[str, Any]:
        return self.payload["threshold_groups"]

    @property
    def global_defaults(self) -> Mapping[str, Any]:
        return self.payload["global_defaults"]

    def validate(self, registry: AllowedEnumRegistry | None = None) -> None:
        """Validate config shape, score ranges, stage order, and registry compatibility."""

        required_top_level = {
            "config_id",
            "config_version",
            "pipeline_stage_order",
            "global_defaults",
            "threshold_groups",
        }
        missing = sorted(required_top_level - set(self.payload))
        if missing:
            raise ConfigDefaultsError(f"config missing top-level keys: {missing}")

        stages = self.pipeline_stage_order
        if len(stages) != len(set(stages)):
            raise ConfigDefaultsError("pipeline_stage_order contains duplicates")
        if registry is not None and stages != registry.pipeline_stage_order:
            raise ConfigDefaultsError("config pipeline_stage_order must match allowed enum registry")

        score_min = float(self.global_defaults.get("score_min", 0.0))
        score_max = float(self.global_defaults.get("score_max", 1.0))
        if score_min != 0.0 or score_max != 1.0:
            raise ConfigDefaultsError("global score_min/score_max must be 0.0/1.0")
        self._validate_review_thresholds(
            self.global_defaults.get("default_review_thresholds", {}),
            context="global_defaults.default_review_thresholds",
        )
        self._validate_multipliers(
            self.global_defaults.get("default_suppression_multipliers", {}),
            context="global_defaults.default_suppression_multipliers",
        )

        allowed_signal_groups = registry.allowed_families if registry is not None else None
        routed_signal_groups = set(registry.signal_group_routes) if registry is not None else None

        for group_name, group_payload in self.threshold_groups.items():
            stage = group_payload.get("pipeline_stage")
            if stage not in stages:
                raise ConfigDefaultsError(f"threshold group {group_name} uses unknown stage: {stage}")
            if stage != group_name:
                raise ConfigDefaultsError(
                    f"threshold group {group_name} must use matching pipeline_stage {group_name}"
                )
            signal_groups = group_payload.get("signal_groups", {})
            if not isinstance(signal_groups, Mapping) or not signal_groups:
                raise ConfigDefaultsError(f"threshold group {group_name} has no signal_groups")

            for signal_group_id, signal_payload in signal_groups.items():
                if allowed_signal_groups is not None and signal_group_id not in allowed_signal_groups:
                    raise ConfigDefaultsError(
                        f"signal group {signal_group_id} is not allowed by enum registry"
                    )
                if routed_signal_groups is not None and signal_group_id not in routed_signal_groups:
                    raise ConfigDefaultsError(
                        f"signal group {signal_group_id} has config defaults but no router entry"
                    )
                signal_config = SignalGroupConfig.from_mapping(signal_group_id, signal_payload)
                self._validate_weights(signal_config.weights, context=f"{signal_group_id}.weights")
                self._validate_review_thresholds(
                    signal_config.review_thresholds,
                    context=f"{signal_group_id}.review_thresholds",
                )
                self._validate_multipliers(
                    signal_config.suppression_multipliers,
                    context=f"{signal_group_id}.suppression_multipliers",
                )
                self._validate_guardrail(signal_config.defaults, context=f"{signal_group_id}.defaults")

        if registry is not None:
            self._validate_stage_coverage(registry)

    def signal_group_config(self, signal_group_id: str) -> SignalGroupConfig:
        """Return scoring defaults for a signal group."""

        for group_payload in self.threshold_groups.values():
            signal_groups = group_payload.get("signal_groups", {})
            if signal_group_id in signal_groups:
                return SignalGroupConfig.from_mapping(signal_group_id, signal_groups[signal_group_id])
        raise ConfigDefaultsError(f"unknown signal group config: {signal_group_id}")

    def suppression_multiplier(self, signal_group_id: str, reason: str) -> float:
        """Return the suppression multiplier for a signal group/reason pair."""

        config = self.signal_group_config(signal_group_id)
        if reason in config.suppression_multipliers:
            return config.suppression_multipliers[reason]
        if "none" in config.suppression_multipliers:
            return config.suppression_multipliers["none"]
        raise ConfigDefaultsError(f"no suppression multiplier for {signal_group_id}: {reason}")

    @staticmethod
    def _validate_weights(weights: Mapping[str, float], *, context: str) -> None:
        if not weights:
            raise ConfigDefaultsError(f"{context} must not be empty")
        total = sum(weights.values())
        if abs(total - 1.0) > 0.000001:
            raise ConfigDefaultsError(f"{context} weights must sum to 1.0; got {total:.6f}")
        for key, value in weights.items():
            if value < 0.0 or value > 1.0:
                raise ConfigDefaultsError(f"{context}.{key} must be between 0.0 and 1.0")

    @staticmethod
    def _validate_review_thresholds(thresholds: Mapping[str, Any], *, context: str) -> None:
        required = ("reject_below", "review_at", "high_priority_at", "auto_accept_at")
        missing = [key for key in required if key not in thresholds]
        if missing:
            raise ConfigDefaultsError(f"{context} missing review thresholds: {missing}")
        values = [float(thresholds[key]) for key in required]
        if any(value < 0.0 or value > 1.0 for value in values):
            raise ConfigDefaultsError(f"{context} thresholds must be between 0.0 and 1.0")
        if values != sorted(values):
            raise ConfigDefaultsError(f"{context} thresholds must be monotonically increasing")

    @staticmethod
    def _validate_multipliers(multipliers: Mapping[str, Any], *, context: str) -> None:
        if not multipliers:
            raise ConfigDefaultsError(f"{context} must not be empty")
        for key, value in multipliers.items():
            numeric = float(value)
            if numeric < 0.0 or numeric > 1.0:
                raise ConfigDefaultsError(f"{context}.{key} must be between 0.0 and 1.0")

    @staticmethod
    def _validate_guardrail(defaults: Mapping[str, Any], *, context: str) -> None:
        guardrail = defaults.get("interpretation_guardrail")
        if not guardrail:
            raise ConfigDefaultsError(f"{context} must include interpretation_guardrail")

    def _validate_stage_coverage(self, registry: AllowedEnumRegistry) -> None:
        stage_index = {stage: index for index, stage in enumerate(self.pipeline_stage_order)}
        configured_signal_groups = {
            signal_group_id
            for group_payload in self.threshold_groups.values()
            for signal_group_id in group_payload.get("signal_groups", {})
        }
        for signal_group_id, route in registry.signal_group_routes.items():
            if route.pipeline_stage in {"tile_suppression", "ground_context", "infrastructure_context", "recurrence"}:
                if signal_group_id not in configured_signal_groups:
                    raise ConfigDefaultsError(f"missing config defaults for routed signal group: {signal_group_id}")
            for dependency in route.suppression_dependencies:
                if dependency in registry.signal_group_routes:
                    dependency_stage = registry.signal_group_routes[dependency].pipeline_stage
                    if stage_index[dependency_stage] > stage_index[route.pipeline_stage]:
                        raise ConfigDefaultsError(
                            f"dependency {dependency} must not run after {signal_group_id}"
                        )


def load_config_defaults(
    path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    registry: AllowedEnumRegistry | None = None,
    registry_path: str | Path | None = None,
) -> ConfigDefaults:
    """Load and validate FR24 config defaults."""

    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    if registry is None:
        registry = load_allowed_enum_registry(registry_path) if registry_path is not None else load_allowed_enum_registry()

    config = ConfigDefaults(payload=payload)
    config.validate(registry=registry)
    return config
