"""Airspace observations, constraints and non-causal spatial state."""

from pitirre.core.domains.registry import validate_domain_path

DOMAIN_PATH = validate_domain_path("AIR", subdomain="AIRSPACE")

__all__ = ["DOMAIN_PATH"]
