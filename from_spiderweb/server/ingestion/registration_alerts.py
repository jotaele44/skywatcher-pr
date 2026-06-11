"""
Registration watchlist alerts for PRIIS.

Two rules, evaluated against the priis.db ``events`` table:

  * "seen"             — a watchlisted registration appears in the data.
  * "expected missing" — a watchlisted registration with an ``expected_within_days``
                         cadence has not appeared inside that window.

Alerts are written to the existing ``alerts`` table with deterministic ids
(``REG-SEEN-{reg}-{date}`` / ``REG-MISS-{reg}-{date}``) via INSERT OR IGNORE, so
re-running the same day is a no-op. Each *newly created* alert is handed to the
external notifier (server/notifications/notifier.py), which is a no-op unless a
channel is configured.

Usage (from repo root):
    python3 server/ingestion/registration_alerts.py [--db server/priis.db] \
        [--watchlist configs/registration_watchlist.yaml] [--no-notify]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from server.ingestion.registration_common import normalize_registration  # noqa: E402
from server.notifications.notifier import send_alert  # noqa: E402

DB_DEFAULT = _ROOT / "server" / "priis.db"
WATCHLIST_DEFAULT = _ROOT / "configs" / "registration_watchlist.yaml"

SEEN_TIER = "T3"
MISSING_TIER = "T1"


def load_watchlist(path: Path) -> List[Dict[str, Any]]:
    """Load the registration watchlist YAML into a normalized list of entries."""
    if not path.exists():
        return []
    import yaml  # local import: keeps the dependency optional for callers

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw = data.get("registrations", data) if isinstance(data, dict) else data
    entries: List[Dict[str, Any]] = []
    for item in raw or []:
        if isinstance(item, str):
            item = {"registration": item}
        reg = (item.get("registration") or "").strip()
        if not reg:
            continue
        entries.append(
            {
                "registration": reg,
                "label": item.get("label") or reg,
                "operator": item.get("operator") or "",
                "expected_within_days": item.get("expected_within_days"),
            }
        )
    return entries


def _parse_at(value: object) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    # Normalize to naive UTC so tz-aware ADS-B stamps ("...Z") compare with the
    # naive timestamps from FR24/flight-log rows without raising TypeError.
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def seen_registrations(conn: sqlite3.Connection) -> Dict[str, datetime]:
    """Map normalized registration → most-recent sighting datetime.

    Considers the registration column plus callsign/ref_id/label so that rows
    ingested before the registration column existed still match.
    """
    latest: Dict[str, datetime] = {}
    cur = conn.execute(
        "SELECT at, registration, callsign, ref_id, label FROM events WHERE kind='flight'"
    )
    for row in cur.fetchall():
        at = _parse_at(row["at"] if isinstance(row, sqlite3.Row) else row[0])
        candidates = (
            row["registration"], row["callsign"], row["ref_id"], row["label"]
        ) if isinstance(row, sqlite3.Row) else row[1:]
        for cand in candidates:
            norm = normalize_registration(cand)
            if not norm:
                continue
            if at is None:
                latest.setdefault(norm, datetime.min)
            elif norm not in latest or at > latest[norm]:
                latest[norm] = at
    return latest


def _insert_alert(conn: sqlite3.Connection, alert: Dict[str, Any]) -> bool:
    """INSERT OR IGNORE one alert. Returns True if a new row was created."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO alerts (id, at, kind, title, tier, investigation, registration) "
        "VALUES (?,?,?,?,?,?,?)",
        (
            alert["id"], alert["at"], alert["kind"], alert["title"],
            alert["tier"], alert.get("investigation"), alert.get("registration"),
        ),
    )
    return cur.rowcount > 0


def generate_alerts(
    conn: sqlite3.Connection,
    watchlist: List[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
    notify: bool = True,
    env: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Evaluate both rules, persist new alerts, notify on each new one."""
    now = now or datetime.utcnow()
    today = now.strftime("%Y-%m-%d")
    latest = seen_registrations(conn)

    new_alerts: List[Dict[str, Any]] = []
    seen_count = 0
    missing_count = 0

    for entry in watchlist:
        reg = entry["registration"]
        norm = normalize_registration(reg)
        if not norm:
            continue

        if norm in latest:
            seen_count += 1
            alert = {
                "id": f"REG-SEEN-{norm}-{today}",
                "at": now.isoformat(),
                "kind": "aircraft",
                "title": f"Watchlisted aircraft {reg} seen",
                "tier": SEEN_TIER,
                "investigation": None,
                "registration": reg,
            }
            if _insert_alert(conn, alert):
                new_alerts.append(alert)

        days = entry.get("expected_within_days")
        if days:
            cutoff = now - timedelta(days=int(days))
            last = latest.get(norm)
            if last is None or last < cutoff:
                missing_count += 1
                last_txt = "never" if last is None else last.strftime("%Y-%m-%d")
                alert = {
                    "id": f"REG-MISS-{norm}-{today}",
                    "at": now.isoformat(),
                    "kind": "aircraft",
                    "title": (
                        f"Expected aircraft {reg} not seen in {days}d "
                        f"(last: {last_txt})"
                    ),
                    "tier": MISSING_TIER,
                    "investigation": None,
                    "registration": reg,
                }
                if _insert_alert(conn, alert):
                    new_alerts.append(alert)

    conn.commit()

    notified = 0
    if notify:
        for alert in new_alerts:
            if send_alert(alert, env=env):
                notified += 1

    return {
        "watchlist_size": len(watchlist),
        "seen_matches": seen_count,
        "missing_matches": missing_count,
        "new_alerts": len(new_alerts),
        "notified": notified,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate registration watchlist alerts")
    parser.add_argument("--db", default=str(DB_DEFAULT), help="Path to priis.db")
    parser.add_argument("--watchlist", default=str(WATCHLIST_DEFAULT), help="Watchlist YAML")
    parser.add_argument("--no-notify", action="store_true", help="Skip external notification")
    args = parser.parse_args()

    watchlist = load_watchlist(Path(args.watchlist))
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        summary = generate_alerts(conn, watchlist, notify=not args.no_notify)
    finally:
        conn.close()
    print(summary)


if __name__ == "__main__":
    main()
