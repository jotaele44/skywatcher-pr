"""Validated AIR domain paths."""

from __future__ import annotations

from pitirre.core.domains.registry import AIR_SUBDOMAINS, DomainPath, validate_domain_path

AIR_DOMAIN = validate_domain_path("AIR")
AIR_SUBDOMAIN_PATHS: tuple[DomainPath, ...] = tuple(
    validate_domain_path("AIR", subdomain=name) for name in AIR_SUBDOMAINS
)
