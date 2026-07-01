"""Historical baseline analytics for Skywatcher sensor fusion records."""

from __future__ import annotations

from collections import defaultdict
from statistics import mean, pstdev
from typing import Iterable, Mapping


def _key(record: Mapping[str, object]) -> tuple[str, str]:
    corridor = str(record.get("corridor_id") or "unassigned")
    domain = str(record.get("domain") or record.get("source_domain") or "context")
    return corridor, domain


def build_historical_baselines(records: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    """Build aggregate historical baselines by corridor and domain.

    Baselines are statistical summaries for analytical review. They are not live
    tracking surfaces and do not emit operational recommendations.
    """

    groups: dict[tuple[str, str], list[Mapping[str, object]]] = defaultdict(list)
    for record in records:
        groups[_key(record)].append(record)

    baselines: list[dict[str, object]] = []
    for (corridor_id, domain), items in sorted(groups.items()):
        confidence_values = [float(item.get("confidence", 0.0)) for item in items]
        count_values = [float(item.get("event_count", 1.0)) for item in items]
        baseline_count = sum(count_values)
        confidence_mean = mean(confidence_values) if confidence_values else 0.0
        count_stddev = pstdev(count_values) if len(count_values) > 1 else 0.0
        baselines.append({
            "corridor_id": corridor_id,
            "domain": domain,
            "historical_count": int(baseline_count) if baseline_count.is_integer() else round(baseline_count, 3),
            "mean_confidence": round(confidence_mean, 3),
            "count_stddev": round(count_stddev, 3),
            "baseline_type": "historical_aggregate",
            "operator_use": "review_context_only",
            "live_tracking": False,
        })
    return baselines


def index_baselines(baselines: Iterable[Mapping[str, object]]) -> dict[tuple[str, str], Mapping[str, object]]:
    """Index historical baselines by corridor/domain."""

    return {(str(item.get("corridor_id")), str(item.get("domain"))): item for item in baselines}
