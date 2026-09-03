"""SQLite connection configuration helper (T4-27).

Call ``configure_connection()`` immediately after ``sqlite3.connect()`` in
every pipeline module.  The PRAGMAs are idempotent and safe to set on an
existing database.
"""

from __future__ import annotations

import sqlite3


def configure_connection(conn: sqlite3.Connection) -> None:
    """Apply WAL mode and performance-tuned PRAGMAs to *conn*.

    - WAL mode keeps readers and writers non-blocking.
    - NORMAL synchronous gives crash-safe durability without fsync on every commit.
    - 32 MB page cache (negative = KiB) avoids repeated page re-reads.
    - 10 s busy timeout prevents instant SQLITE_BUSY on write contention.
    - MEMORY temp_store keeps sort/index scratch space off disk.
    """
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA cache_size = -32000")
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.execute("PRAGMA temp_store = MEMORY")
