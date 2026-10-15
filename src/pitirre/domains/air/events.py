"""AIR event facade over Core-owned normalization and contract validation."""

from pitirre.core.contracts.air_event import validate_air_event_contract
from pitirre.core.normalization.air_event import normalize_air_event

__all__ = ["normalize_air_event", "validate_air_event_contract"]
