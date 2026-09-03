"""
ADS-B feed — persistence sink.

Writes polled :class:`~adsb.models.StateVector` rows into the FR24 SQLite
database's ``adsb_state_vectors`` table (migration 0002; see
``schemas/adsb_state_vectors.sql``), through the same
``skywatcher.fr24.database`` connection/migration machinery the rest of the
FR24 pipeline uses. Never raises on a persistence failure — a sink error must
not fail the poll itself; see ``persist_batch``'s return value instead.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (_REPO_ROOT, _REPO_ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from skywatcher.fr24 import database as db  # noqa: E402
from skywatcher.fr24 import database_migrations as migrations  # noqa: E402

from . import config  # noqa: E402
from .models import StateVector  # noqa: E402


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def persist_batch(
    states: list[StateVector],
    *,
    db_path: str | Path | None = None,
    source_ref: str = "adsb-poll",
) -> dict[str, Any]:
    """Persist ``states`` as one ingestion batch. Returns a result dict.

    Keys: ``persisted`` (bool), ``n_written`` (int), ``batch_id`` (int|None),
    ``errors`` (list[str]). Applies pending migrations idempotently before
    writing, so a fresh database gets ``adsb_state_vectors`` created on first
    use.
    """
    path = Path(db_path) if db_path else db.resolve_db_path(config.SKYWATCHER_DB or None)
    try:
        conn = db.connect(path)
    except db.DatabaseError as exc:
        return {"persisted": False, "n_written": 0, "batch_id": None, "errors": [str(exc)]}

    try:
        migrations.apply_migrations(conn)
        now = _utc_now_iso()
        cur = conn.execute(
            "INSERT INTO ingestion_batches "
            "(batch_kind, source_ref, started_at, status, n_inputs) "
            "VALUES (?, ?, ?, 'in_progress', ?)",
            ("adsb_poll", source_ref, now, len(states)),
        )
        batch_id = cur.lastrowid

        for s in states:
            conn.execute(
                """
                INSERT INTO adsb_state_vectors (
                    provider, icao24, callsign, origin_country,
                    time_position, last_contact, longitude, latitude,
                    baro_altitude_m, on_ground, velocity_mps, true_track_deg,
                    vertical_rate_mps, geo_altitude_m, squawk,
                    position_source, batch_id, polled_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    s.provider,
                    s.icao24,
                    s.callsign,
                    s.origin_country,
                    s.time_position,
                    s.last_contact,
                    s.longitude,
                    s.latitude,
                    s.baro_altitude,
                    int(s.on_ground),
                    s.velocity,
                    s.true_track,
                    s.vertical_rate,
                    s.geo_altitude,
                    s.squawk,
                    s.position_source,
                    batch_id,
                    now,
                ),
            )

        conn.execute(
            "UPDATE ingestion_batches SET status='completed', ended_at=?, "
            "n_processed=? WHERE batch_id=?",
            (_utc_now_iso(), len(states), batch_id),
        )
        conn.commit()
        return {"persisted": True, "n_written": len(states), "batch_id": batch_id, "errors": []}
    except Exception as exc:  # noqa: BLE001 - persistence must never raise
        conn.rollback()
        return {"persisted": False, "n_written": 0, "batch_id": None, "errors": [str(exc)]}
    finally:
        conn.close()
