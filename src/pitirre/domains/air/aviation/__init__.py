"""Aircraft/flight observations and source-declared aviation state."""

from pitirre.core.domains.registry import validate_domain_path

DOMAIN_PATH = validate_domain_path("AIR", subdomain="AVIATION")

__all__ = ["DOMAIN_PATH"]
