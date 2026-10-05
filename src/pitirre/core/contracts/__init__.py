"""Versioned, domain-neutral PITIRRE contract helpers."""

from .air_event import (
    AIR_EVENT_SCHEMA_VERSION,
    load_air_event_schema,
    validate_air_event_contract,
)
from .observation import (
    ADAPTER_VERSION,
    OBSERVATION_SCHEMA_VERSION,
    ObservationAdapterError,
    PitirreObservation,
    adapt_airspace_observation,
    adapt_maritime_baseline,
)

__all__ = [
    "AIR_EVENT_SCHEMA_VERSION",
    "ADAPTER_VERSION",
    "OBSERVATION_SCHEMA_VERSION",
    "ObservationAdapterError",
    "PitirreObservation",
    "adapt_airspace_observation",
    "adapt_maritime_baseline",
    "load_air_event_schema",
    "validate_air_event_contract",
]
