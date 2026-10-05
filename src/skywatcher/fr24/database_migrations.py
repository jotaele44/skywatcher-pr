"""Backward-compatible module alias for PITIRRE Core database migrations."""

import sys as _sys

from pitirre.core.storage.fr24 import database_migrations as _canonical

_sys.modules[__name__] = _canonical
