"""
ADS-B providers — registry.

``get_provider(name)`` returns a provider instance. Names: ``opensky``
(OpenSky Network, OAuth2 client credentials with anonymous fallback).
"""

from __future__ import annotations

from .base import AdsbProvider, ProviderError
from .opensky import OpenSkyProvider

_PROVIDERS: dict[str, type[AdsbProvider]] = {
    "opensky": OpenSkyProvider,
    "opensky-network": OpenSkyProvider,
}

_INSTANCES: dict[str, AdsbProvider] = {}


def available_providers() -> list[str]:
    return ["opensky"]


def get_provider(name: str) -> AdsbProvider:
    key = (name or "").strip().lower()
    cls = _PROVIDERS.get(key)
    if cls is None:
        raise ProviderError(f"unknown provider {name!r}; choose one of {available_providers()}")
    if key not in _INSTANCES:
        _INSTANCES[key] = cls()
    return _INSTANCES[key]


__all__ = [
    "AdsbProvider",
    "ProviderError",
    "get_provider",
    "available_providers",
    "OpenSkyProvider",
]
