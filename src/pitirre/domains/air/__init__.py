"""PITIRRE AIR physical domain.

AIR owns aviation, airspace, aerostat and atmospheric-sensor observations/state.
It does not infer mission or intent. Analytical trajectory interpretation remains
FPIM-owned and cross-domain association remains CORRIM-owned.
"""

from .registry import AIR_DOMAIN, AIR_SUBDOMAIN_PATHS

__all__ = ["AIR_DOMAIN", "AIR_SUBDOMAIN_PATHS"]
