"""Backward-compatible ADS-B provider facade for PITIRRE AIR.AVIATION."""

from pitirre.domains.air.aviation.adsb.providers import (
    AdsbProvider,
    OpenSkyProvider,
    ProviderError,
    available_providers,
    get_provider,
)

__all__ = [
    "AdsbProvider",
    "ProviderError",
    "get_provider",
    "available_providers",
    "OpenSkyProvider",
]
