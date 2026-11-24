"""PITIRRE domain registry foundation.

This module is additive scaffolding inside the current SkyWatcher namespace.
It does not rename historical artifacts or change the repository's operational
identity.  The canonical candidate top-level domain denominator is:

    AIR | LAND | WATER | SPACE

ROAD is intentionally not a top-level domain.  It is represented as the
LAND.TRANSPORT.ROAD network family so topology/state semantics stay first-class
without making every transport network a peer physical domain.
"""

from __future__ import annotations

from dataclasses import dataclass

DOMAIN_REGISTRY_VERSION = "pitirre-domain-registry-v0.1"

TOP_LEVEL_DOMAINS: tuple[str, ...] = ("AIR", "LAND", "WATER", "SPACE")

AIR_SUBDOMAINS: tuple[str, ...] = (
    "AVIATION",
    "AIRSPACE",
    "AEROSTAT",
    "ATMOSPHERIC_SENSOR",
)

LAND_SUBDOMAINS: tuple[str, ...] = (
    "TERRAIN",
    "FACILITY",
    "INFRASTRUCTURE",
    "TRANSPORT",
    "VEHICLE",
    "CONSTRUCTION",
    "SENSOR",
    "FIELD_ACTIVITY",
)

TRANSPORT_NETWORK_TYPES: tuple[str, ...] = (
    "ROAD",
    "RAIL",
    "TRAIL",
    "OTHER_NETWORK",
)

WATER_SUBDOMAINS: tuple[str, ...] = (
    "HYDROLOGIC",
    "COASTAL",
    "MARITIME",
)

SPACE_SUBDOMAINS: tuple[str, ...] = (
    "ORBITAL",
    "SATELLITE",
    "LAUNCH",
    "REENTRY",
    "REMOTE_SENSING",
    "SPACE_WEATHER",
    "GROUND_SEGMENT",
)

SUBDOMAINS_BY_DOMAIN: dict[str, tuple[str, ...]] = {
    "AIR": AIR_SUBDOMAINS,
    "LAND": LAND_SUBDOMAINS,
    "WATER": WATER_SUBDOMAINS,
    "SPACE": SPACE_SUBDOMAINS,
}


class DomainRegistryError(ValueError):
    """Raised when a domain path violates the PITIRRE domain contract."""


@dataclass(frozen=True)
class DomainPath:
    """Validated canonical domain path."""

    domain: str
    subdomain: str | None = None
    network_type: str | None = None

    @property
    def canonical(self) -> str:
        parts = [self.domain]
        if self.subdomain is not None:
            parts.append(self.subdomain)
        if self.network_type is not None:
            parts.append(self.network_type)
        return ".".join(parts)


def validate_domain_path(
    domain: str,
    *,
    subdomain: str | None = None,
    network_type: str | None = None,
) -> DomainPath:
    """Validate an exact canonical domain path.

    Values are deliberately not normalized here.  Normalization is a discovery
    convenience, not identity proof; callers must provide canonical registry
    tokens explicitly.
    """

    if domain not in TOP_LEVEL_DOMAINS:
        raise DomainRegistryError(f"unsupported top-level domain: {domain!r}")

    allowed_subdomains = SUBDOMAINS_BY_DOMAIN[domain]
    if subdomain is not None and subdomain not in allowed_subdomains:
        raise DomainRegistryError(
            f"unsupported subdomain for {domain}: {subdomain!r}"
        )

    if network_type is not None:
        if domain != "LAND" or subdomain != "TRANSPORT":
            raise DomainRegistryError(
                "network_type is only valid under LAND.TRANSPORT"
            )
        if network_type not in TRANSPORT_NETWORK_TYPES:
            raise DomainRegistryError(
                f"unsupported LAND.TRANSPORT network_type: {network_type!r}"
            )

    return DomainPath(
        domain=domain,
        subdomain=subdomain,
        network_type=network_type,
    )


def road_domain_path() -> DomainPath:
    """Return the canonical ROAD binding."""

    return validate_domain_path(
        "LAND",
        subdomain="TRANSPORT",
        network_type="ROAD",
    )
