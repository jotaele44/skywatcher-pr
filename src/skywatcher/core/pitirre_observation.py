"""Backward-compatible alias for the canonical PITIRRE observation contract."""

from pitirre.core.contracts.observation import (
    ADAPTER_VERSION,
    OBSERVATION_SCHEMA_VERSION,
    ObservationAdapterError,
    PitirreObservation,
    _envelope,
    adapt_airspace_observation,
    adapt_maritime_baseline,
)

__all__ = [
    "ADAPTER_VERSION",
    "OBSERVATION_SCHEMA_VERSION",
    "ObservationAdapterError",
    "PitirreObservation",
    "_envelope",
    "adapt_airspace_observation",
    "adapt_maritime_baseline",
]
