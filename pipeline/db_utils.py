"""Backward-compat shim. Logic moved to skywatcher.core.db_utils.
See docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md."""
from __future__ import annotations

from skywatcher.core.db_utils import configure_connection

__all__ = ["configure_connection"]
