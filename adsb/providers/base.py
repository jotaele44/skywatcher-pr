"""Backward-compatible module alias for PITIRRE ADS-B provider contracts."""

import sys as _sys

from pitirre.domains.air.aviation.adsb.providers import base as _canonical

_sys.modules[__name__] = _canonical
