"""
ADS-B providers — base interface.

Defines the provider contract: pull live aircraft state vectors for a bbox.
Mirrors ``imagery/providers/base.py``'s shape so the two "fetch third-party
geodata behind OAuth2 client-credentials" pipelines in this repo stay
consistent, without sharing code (each provider owns its own transport).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import StateVector


class ProviderError(Exception):
    """Raised for provider misconfiguration or non-recoverable fetch failure."""


class AdsbProvider(ABC):
    """Common contract for automated aircraft-state-vector feeds."""

    name: str = "base"

    @abstractmethod
    def fetch_states(self, bbox: list[float]) -> list[StateVector]:
        """Return current state vectors within ``bbox``.

        ``bbox`` is ``(west, south, east, north)`` in WGS84 decimal degrees,
        matching ``imagery``'s convention.
        """
