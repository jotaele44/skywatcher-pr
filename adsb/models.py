"""Backward-compatible module alias for PITIRRE ADS-B models."""

import sys as _sys

from pitirre.domains.air.aviation.adsb import models as _canonical

_sys.modules[__name__] = _canonical
