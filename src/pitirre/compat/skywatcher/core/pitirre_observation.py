"""Compatibility alias for the historical PITIRRE observation envelope path."""

from pitirre.core.contracts.observation import (
    ADAPTER_VERSION,
    OBSERVATION_SCHEMA_VERSION,
    ObservationAdapterError,
    PitirreObservation,
    adapt_airspace_observation,
    adapt_maritime_baseline,
)

__all__ = [
    "ADAPTER_VERSION",
    "OBSERVATION_SCHEMA_VERSION",
    "ObservationAdapterError",
    "PitirreObservation",
    "adapt_airspace_observation",
    "adapt_maritime_baseline",
]
