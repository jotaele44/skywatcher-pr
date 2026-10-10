"""Backward-compatible module alias for PITIRRE OpenSky provider."""

import sys as _sys

from pitirre.domains.air.aviation.adsb.providers import opensky as _canonical

_sys.modules[__name__] = _canonical
