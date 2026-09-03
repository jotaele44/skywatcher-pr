"""
ADS-B — automated aircraft-state-vector fetch (OpenSky Network).

Replaces the manual, quota-limited FR24 browser-export step
(``scripts/fr24_harvest.py``) with a scheduled poll against the OpenSky
Network's free REST API, for the subset of aircraft data that a live ADS-B
feed can actually provide (position, altitude, velocity, callsign). It does
not replace the FR24 screenshot/OCR corpus, which remains the source for
historical reconstruction.

Entry point: ``python scripts/adsb_poll.py``.
"""

from .models import StateVector

__all__ = ["StateVector"]
