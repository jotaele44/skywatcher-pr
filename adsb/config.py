"""Backward-compatible module alias for PITIRRE ADS-B configuration."""

import sys as _sys

from pitirre.domains.air.aviation.adsb import config as _canonical

_sys.modules[__name__] = _canonical
