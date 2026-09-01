"""FPIM schedule core — empirical (day-of-week, hour-bucket) cadence.

Extracted from ``scripts/rlsm_predictive.py`` (Phase H) so the same logic can
feed both the forecast CLI and the per-craft profile builder without
duplication. This is an **empirical baseline, not a regression**: it reports
"based on recent behaviour, here's when an aircraft has been showing up",
carrying the eligible-period denominator (lookback weeks) so downstream
confidence grading can cap ungrounded claims.

Core-only imports (stdlib). Must not import satim/corrim (see
docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md).
"""

from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta

DOW_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
HOUR_BUCKET_SIZE = 3
NOISE_FLOOR = 0.25  # expected sightings/day below this are dropped as noise


def parse_ts(s: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp string; return None on missing/short/invalid.

    Mirrors the parser in the RLSM intel scripts (16-char minimum guards
    against date-only or truncated strings).
    """
    if not s or len(s) < 16:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def ts_expr(conn: sqlite3.Connection) -> str:
    """Return the timestamp SQL expression, preferring true_flight_ts when the
    column exists (a later-migration column absent from the base schema)."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(screenshots)")}
    if "true_flight_ts" in cols:
        return "COALESCE(s.true_flight_ts, s.filename_ts)"
    return "s.filename_ts"


def load_observations(conn: sqlite3.Connection, since: str | None = None) -> list[tuple[str, str]]:
    """Return ``[(registration, ts)]`` for every registered aircraft observation.

    ``since`` (ISO string) filters to timestamps at or after it when provided.
    """
    expr = ts_expr(conn)
    sql = f"""
        SELECT a.registration, {expr} AS ts
        FROM aircraft_observations a
        JOIN screenshots s USING(screenshot_id)
        WHERE a.registration IS NOT NULL AND {expr} IS NOT NULL
    """
    params: tuple = ()
    if since is not None:
        sql += f" AND {expr} >= ?"
        params = (since,)
    return list(conn.execute(sql, params).fetchall())


def max_corpus_ts(rows: list[tuple[str, str]]) -> datetime | None:
    """Latest parseable timestamp across ``rows`` (the corpus "now")."""
    best: datetime | None = None
    for _reg, ts in rows:
        dt = parse_ts(ts)
        if dt and (best is None or dt > best):
            best = dt
    return best


def build_cells(
    rows: list[tuple[str, str]],
    keep_regs: set | None = None,
    hour_bucket_size: int = HOUR_BUCKET_SIZE,
) -> dict[tuple[str, int, int], int]:
    """Aggregate observations into ``(registration, dow, hour_bucket) -> count``.

    ``keep_regs`` optionally restricts to a set of registrations.
    """
    cells: dict[tuple[str, int, int], int] = defaultdict(int)
    for reg, ts in rows:
        if keep_regs is not None and reg not in keep_regs:
            continue
        dt = parse_ts(ts)
        if not dt:
            continue
        hb = (dt.hour // hour_bucket_size) * hour_bucket_size
        cells[(reg, dt.weekday(), hb)] += 1
    return cells


def top_registrations(rows: list[tuple[str, str]], limit: int) -> list[str]:
    """Registrations ranked by observation volume, most-frequent first."""
    counts = Counter(reg for reg, _ in rows)
    return [reg for reg, _ in counts.most_common(limit)]


def forecast_rows(
    cells: dict[tuple[str, int, int], int],
    regs: list[str],
    max_dt: datetime,
    lookback_weeks: int,
    forecast_days: int,
    hour_bucket_size: int = HOUR_BUCKET_SIZE,
) -> list[dict]:
    """Project ``cells`` forward into per-day expected-sighting rows.

    Expected sightings for a cell = hits / lookback_weeks. Cells below
    ``NOISE_FLOOR`` are dropped. Output is sorted by (date, -expected).
    """
    today = (max_dt + timedelta(days=1)).date()
    out: list[dict] = []
    for offset in range(forecast_days):
        d = today + timedelta(days=offset)
        dow = d.weekday()
        for reg in regs:
            for hb in range(0, 24, hour_bucket_size):
                hits = cells.get((reg, dow, hb), 0)
                if hits == 0:
                    continue
                expected = hits / lookback_weeks
                if expected < NOISE_FLOOR:
                    continue
                out.append(
                    {
                        "date": d.isoformat(),
                        "dow": DOW_NAMES[dow],
                        "hour_bucket": f"{hb:02d}-{hb + hour_bucket_size:02d}",
                        "registration": reg,
                        "expected_sightings": round(expected, 2),
                        "based_on_hits": hits,
                        "lookback_weeks": lookback_weeks,
                    }
                )
    out.sort(key=lambda r: (r["date"], -r["expected_sightings"]))
    return out


def craft_schedule(
    conn: sqlite3.Connection,
    registration: str,
    lookback_weeks: int = 12,
    hour_bucket_size: int = HOUR_BUCKET_SIZE,
) -> dict:
    """Per-craft schedule summary for the profile builder.

    Returns a dict with the populated ``(dow, hour_bucket)`` cells (expected
    sightings/week over the lookback window), a human ``operating_hours``
    summary, and the eligible-period denominator (``lookback_weeks``). Empty
    ``dow_hour_cells`` means no cadence signal in the window.
    """
    rows = load_observations(conn)
    reg_rows = [(r, t) for r, t in rows if r == registration]
    max_dt = max_corpus_ts(rows)
    if not reg_rows or max_dt is None:
        return {
            "dow_hour_cells": [],
            "operating_hours_summary": "",
            "lookback_weeks": lookback_weeks,
            "denominator": lookback_weeks,
        }

    since = (max_dt - timedelta(weeks=lookback_weeks)).isoformat()
    windowed = [(r, t) for r, t in reg_rows if (parse_ts(t) or max_dt) >= parse_ts(since)]
    cells = build_cells(windowed, keep_regs={registration}, hour_bucket_size=hour_bucket_size)

    dow_hour_cells: list[dict] = []
    hours_seen: list[int] = []
    for (_reg, dow, hb), hits in sorted(cells.items(), key=lambda kv: (kv[0][1], kv[0][2])):
        expected = hits / lookback_weeks
        if expected < NOISE_FLOOR:
            continue
        dow_hour_cells.append(
            {
                "dow": DOW_NAMES[dow],
                "hour_bucket": f"{hb:02d}-{hb + hour_bucket_size:02d}",
                "expected_per_week": round(expected, 2),
                "based_on_hits": hits,
            }
        )
        hours_seen.append(hb)

    if hours_seen:
        lo, hi = min(hours_seen), max(hours_seen) + hour_bucket_size
        operating = (
            f"Observed {lo:02d}:00-{hi:02d}:00 local (empirical, {lookback_weeks}-wk baseline)"
        )
    else:
        operating = ""

    return {
        "dow_hour_cells": dow_hour_cells,
        "operating_hours_summary": operating,
        "lookback_weeks": lookback_weeks,
        "denominator": lookback_weeks,
    }
