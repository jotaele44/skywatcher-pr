"""Compatibility alias for the historical SkyWatcher domain registry."""

from pitirre.core.domains.registry import (
    AIR_SUBDOMAINS,
    DOMAIN_REGISTRY_VERSION,
    LAND_SUBDOMAINS,
    SPACE_SUBDOMAINS,
    SUBDOMAINS_BY_DOMAIN,
    TOP_LEVEL_DOMAINS,
    TRANSPORT_NETWORK_TYPES,
    WATER_SUBDOMAINS,
    DomainPath,
    DomainRegistryError,
    road_domain_path,
    validate_domain_path,
)

__all__ = [
    "AIR_SUBDOMAINS",
    "DOMAIN_REGISTRY_VERSION",
    "LAND_SUBDOMAINS",
    "SPACE_SUBDOMAINS",
    "SUBDOMAINS_BY_DOMAIN",
    "TOP_LEVEL_DOMAINS",
    "TRANSPORT_NETWORK_TYPES",
    "WATER_SUBDOMAINS",
    "DomainPath",
    "DomainRegistryError",
    "road_domain_path",
    "validate_domain_path",
]
