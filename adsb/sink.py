"""Backward-compatible module alias for the PITIRRE ADS-B persistence sink."""

import sys as _sys

from pitirre.domains.air.aviation.adsb import sink as _canonical

_sys.modules[__name__] = _canonical
