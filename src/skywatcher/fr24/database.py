"""Backward-compatible module alias for PITIRRE Core database storage."""

import sys as _sys

from pitirre.core.storage.fr24 import database as _canonical

_sys.modules[__name__] = _canonical
