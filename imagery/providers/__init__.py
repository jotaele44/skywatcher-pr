"""
Imagery providers — registry.

``get_provider(name)`` returns a provider instance. Names:
``gibs`` (no auth), ``sentinelhub`` (OAuth2), ``copernicus`` (CDSE OAuth2).
"""

from __future__ import annotations

from .base import ImageryProvider, ProviderError
from .copernicus import CopernicusProvider
from .gibs import GibsProvider
from .sentinelhub import SentinelHubProvider

_PROVIDERS: dict[str, type[ImageryProvider]] = {
    "gibs": GibsProvider,
    "sentinelhub": SentinelHubProvider,
    "sentinel-hub": SentinelHubProvider,
    "copernicus": CopernicusProvider,
    "cdse": CopernicusProvider,
}

_INSTANCES: dict[str, ImageryProvider] = {}


def available_providers() -> list[str]:
    return ["gibs", "sentinelhub", "copernicus"]


def get_provider(name: str) -> ImageryProvider:
    key = (name or "").strip().lower()
    cls = _PROVIDERS.get(key)
    if cls is None:
        raise ProviderError(
            f"unknown provider {name!r}; choose one of {available_providers()}"
        )
    if key not in _INSTANCES:
        _INSTANCES[key] = cls()
    return _INSTANCES[key]


__all__ = [
    "ImageryProvider",
    "ProviderError",
    "get_provider",
    "available_providers",
    "GibsProvider",
    "SentinelHubProvider",
    "CopernicusProvider",
]
