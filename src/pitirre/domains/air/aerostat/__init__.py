"""Aerostat observations/state without inferred purpose."""

from pitirre.core.domains.registry import validate_domain_path

DOMAIN_PATH = validate_domain_path("AIR", subdomain="AEROSTAT")

__all__ = ["DOMAIN_PATH"]
