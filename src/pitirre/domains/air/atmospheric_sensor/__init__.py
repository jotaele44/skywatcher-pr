"""Atmospheric sensor observations/state."""

from pitirre.core.domains.registry import validate_domain_path

DOMAIN_PATH = validate_domain_path("AIR", subdomain="ATMOSPHERIC_SENSOR")

__all__ = ["DOMAIN_PATH"]
