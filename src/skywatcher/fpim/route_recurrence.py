"""FPIM route-recurrence core — flight clustering, POI sequences, recurring routes.

Extracted from ``scripts/rlsm_route_inference.py`` (Phase C) so the same logic
feeds both the route-inference CLI and the per-craft profile builder. Recurrence
claims carry an eligible-period denominator (distinct flight-days for the
registration) so downstream confidence grading can cap them per the skill's
coverage gates. This module contains no intent/mission inference — it describes
observed geometry only.

Core-only imports (stdlib). Must not import satim/corrim.
"""
from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

CLUSTER_GAP_MINUTES = 60
DEFAULT_MIN_ROUTE_REPEAT = 3
MAX_ROUTE_POIS = 8


def parse_ts(s: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp; None on missing/short/invalid (16-char min)."""
    if not s or len(s) < 16:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def shape_of(sequence: List[str]) -> str:
    """Classify an ordered POI sequence's geometry.

    loop / out_and_back / hub_and_spoke / linear / multi_visit / single_poi /
    stationary / absent. Identical rules to scripts/rlsm_route_inference.py.
    """
    if not sequence:
        return "absent"
    if len(sequence) == 1:
        return "single_poi"
    if len(set(sequence)) == 1:
        return "stationary"
    if sequence[0] == sequence[-1] and len(sequence) >= 3:
        return "loop"
    if len(sequence) == 3 and sequence[0] == sequence[2] and sequence[0] != sequence[1]:
        return "out_and_back"
    counts = Counter(sequence)
    most_common = counts.most_common(1)[0]
    if most_common[1] / len(sequence) > 0.5:
        return "hub_and_spoke"
    return "linear" if len(set(sequence)) == len(sequence) else "multi_visit"


def ts_expr(conn: sqlite3.Connection) -> str:
    """Timestamp SQL expression, preferring true_flight_ts when present."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(screenshots)")}
    if "true_flight_ts" in cols:
        return "COALESCE(s.true_flight_ts, s.filename_ts)"
    return "s.filename_ts"


def has_side_mining(conn: sqlite3.Connection) -> bool:
    """True when origin/destination side-mining columns exist (later migration)."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(aircraft_observations)")}
    return "origin_iata" in cols


def load_observation_rows(conn: sqlite3.Connection) -> List[tuple]:
    """Return ``[(registration, ts, screenshot_id, origin_iata, destination_iata,
    operator_text_manual)]`` ordered by registration then time.

    O/D and operator columns are NULL-filled when the side-mining migration
    hasn't been applied.
    """
    expr = ts_expr(conn)
    if has_side_mining(conn):
        sql = f"""
            SELECT a.registration, {expr} AS ts, a.screenshot_id,
                   a.origin_iata, a.destination_iata, a.operator_text_manual
            FROM aircraft_observations a
            JOIN screenshots s USING(screenshot_id)
            WHERE a.registration IS NOT NULL AND {expr} IS NOT NULL
            ORDER BY a.registration, ts
        """
    else:
        sql = f"""
            SELECT a.registration, {expr} AS ts, a.screenshot_id,
                   NULL AS origin_iata, NULL AS destination_iata,
                   NULL AS operator_text_manual
            FROM aircraft_observations a
            JOIN screenshots s USING(screenshot_id)
            WHERE a.registration IS NOT NULL AND {expr} IS NOT NULL
            ORDER BY a.registration, ts
        """
    return list(conn.execute(sql).fetchall())


def load_poi_index(conn: sqlite3.Connection) -> Dict[int, List[str]]:
    """Map ``screenshot_id -> [normalized_label]`` for real (non-candidate) pins."""
    poi_idx: Dict[int, List[str]] = defaultdict(list)
    for sid, label, _guess in conn.execute(
        """
        SELECT screenshot_id, normalized_label, pin_type_guess
        FROM labeled_pins
        WHERE pin_type_guess != 'unknown_label_candidate'
        """
    ):
        poi_idx[sid].append(label)
    return poi_idx


def cluster_flights(rows: List[tuple]) -> List[dict]:
    """Cluster observation rows into flight events.

    A cluster is same registration + same calendar date + consecutive gaps
    <= CLUSTER_GAP_MINUTES. Rows must be pre-sorted by (registration, ts).
    """
    clusters: List[dict] = []
    cur: Optional[dict] = None
    for reg, ts, sid, oia, dia, op in rows:
        dt = parse_ts(ts)
        if not dt:
            continue
        if cur is None:
            cur = _new_cluster(reg, dt, sid, op)
        else:
            same = cur["reg"] == reg and cur["date"] == dt.date().isoformat()
            within = (dt - cur["end"]) <= timedelta(minutes=CLUSTER_GAP_MINUTES)
            if same and within:
                cur["end"] = dt
                cur["sids"].append(sid)
            else:
                clusters.append(cur)
                cur = _new_cluster(reg, dt, sid, op)
        if oia:
            cur["origins"][oia] += 1
        if dia:
            cur["destinations"][dia] += 1
    if cur:
        clusters.append(cur)
    return clusters


def _new_cluster(reg: str, dt: datetime, sid: int, operator: Optional[str] = None) -> dict:
    return {
        "reg": reg,
        "date": dt.date().isoformat(),
        "start": dt,
        "end": dt,
        "sids": [sid],
        "origins": Counter(),
        "destinations": Counter(),
        "operator": operator,
    }


def sequence_for_cluster(cluster: dict, poi_idx: Dict[int, List[str]]) -> List[str]:
    """Ordered, consecutive-deduplicated POI sequence for a flight cluster."""
    seq: List[str] = []
    for sid in cluster["sids"]:
        for poi in poi_idx.get(sid, []):
            if not seq or seq[-1] != poi:
                seq.append(poi)
    return seq


def derive_route_counts(
    clusters: List[dict], poi_idx: Dict[int, List[str]]
) -> Counter:
    """Count ``(registration, route_pattern, shape)`` occurrences across clusters."""
    counts: Counter = Counter()
    for c in clusters:
        seq = sequence_for_cluster(c, poi_idx)
        if not seq:
            continue
        route_key = " → ".join(seq[:MAX_ROUTE_POIS])
        counts[(c["reg"], route_key, shape_of(seq))] += 1
    return counts


def recurring_routes(
    route_counts: Counter, min_repeat: int = DEFAULT_MIN_ROUTE_REPEAT
) -> List[Tuple[str, str, str, int]]:
    """``(registration, route_pattern, shape, n_observed)`` seen >= min_repeat,
    most-frequent first."""
    return [
        (reg, route, shape, n)
        for (reg, route, shape), n in sorted(route_counts.items(), key=lambda x: -x[1])
        if n >= min_repeat
    ]


def eligible_flight_days(clusters: List[dict], registration: str) -> int:
    """Distinct flight-days observed for a registration — the recurrence
    denominator. A route seen 4x over 40 eligible days is graded very
    differently from 4x over 5."""
    return len({c["date"] for c in clusters if c["reg"] == registration})


def craft_routes_and_base(
    conn: sqlite3.Connection,
    registration: str,
    min_repeat: int = DEFAULT_MIN_ROUTE_REPEAT,
) -> dict:
    """Per-craft recurring routes + O/D home-base signal for the profile builder.

    Returns ``{recurring_routes[], origin_counts, destination_counts,
    eligible_flight_days, has_side_mining}``. ``origin_counts`` /
    ``destination_counts`` are IATA -> count (empty when side-mining columns
    are absent); the most-frequent origin/destination is the home-base
    candidate, graded against ``eligible_flight_days`` downstream.
    """
    rows = [r for r in load_observation_rows(conn) if r[0] == registration]
    poi_idx = load_poi_index(conn)
    clusters = cluster_flights(rows)
    counts = derive_route_counts(clusters, poi_idx)
    denom = eligible_flight_days(clusters, registration)

    origins: Counter = Counter()
    destinations: Counter = Counter()
    for c in clusters:
        origins.update(c["origins"])
        destinations.update(c["destinations"])

    routes = [
        {
            "route_pattern": route,
            "shape": shape,
            "n_observed": n,
            "denominator": denom,
        }
        for (_reg, route, shape, n) in recurring_routes(counts, min_repeat)
    ]

    return {
        "recurring_routes": routes,
        "origin_counts": dict(origins),
        "destination_counts": dict(destinations),
        "eligible_flight_days": denom,
        "has_side_mining": has_side_mining(conn),
    }
