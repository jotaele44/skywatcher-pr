"""Canonical SQLite persistence primitives inherited from the FR24 datastore.

The namespace name preserves datastore lineage; ownership is PITIRRE Core.
Master Flight Log authority and source-manifestation semantics are unchanged.
"""

from . import database, database_migrations

__all__ = ["database", "database_migrations"]
