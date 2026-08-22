#!/usr/bin/env python3
"""Legacy aircraft co-occurrence network — NONCANONICAL/AUDIT_ONLY.

The historical graph is preserved for diagnostic comparison. It uses temporal
fallbacks and raw registration strings and does not normalize pairwise counts by
a closed simultaneous-observation-opportunity denominator. Community membership
therefore cannot be promoted to coordination. Use ``--audit-only`` to run it in
a quarantined output directory.
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from rlsm_noncanonical_guard import enter_audit_only

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
OUTS = REPO / "outputs"
FAA_CSV = REPO / "data" / "faa_registry_consolidated.csv"


def parse_ts(value):
    if not value or len(value) < 16:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def greedy_communities(adj: dict, edge_weights: dict) -> dict:
    """Historical greedy grouping; this is not a coordination classifier."""
    communities = {node: index for index, node in enumerate(adj)}
    changed = True
    iterations = 0
    while changed and iterations < 20:
        changed = False
        iterations += 1
        for node in adj:
            neighbor_weights = Counter()
            for neighbor in adj[node]:
                weight = edge_weights.get(tuple(sorted([node, neighbor])), 0)
                neighbor_weights[communities[neighbor]] += weight
            if neighbor_weights:
                best = neighbor_weights.most_common(1)[0][0]
                if best != communities[node]:
                    communities[node] = best
                    changed = True
    remap = {
        community: index
        for index, community in enumerate(sorted(set(communities.values())))
    }
    return {node: remap[community] for node, community in communities.items()}


def main() -> int:
    global OUTS
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--window-min",
        type=int,
        default=10,
        help="Legacy co-occurrence window in minutes",
    )
    ap.add_argument("--min-cooccur", type=int, default=2)
    ap.add_argument(
        "--audit-only",
        action="store_true",
        help="Run legacy noncanonical logic and quarantine its outputs.",
    )
    args = ap.parse_args()
    audit_dir = enter_audit_only(
        analysis="network_graph", audit_only=args.audit_only, repo=REPO
    )
    if audit_dir is None:
        return 2
    OUTS = audit_dir

    conn = sqlite3.connect(DB)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(screenshots)")}
    timestamp_expression = (
        "COALESCE(s.true_flight_ts, s.filename_ts)"
        if "true_flight_ts" in columns
        else "s.filename_ts"
    )
    rows = conn.execute(
        f"""
        SELECT a.registration, {timestamp_expression} AS ts
        FROM aircraft_observations a
        JOIN screenshots s USING(screenshot_id)
        WHERE a.registration IS NOT NULL AND {timestamp_expression} IS NOT NULL
        ORDER BY ts
        """
    ).fetchall()

    owner_by_reg = {}
    model_by_reg = {}
    if FAA_CSV.exists():
        for row in csv.DictReader(FAA_CSV.open()):
            tail = (row.get("registration") or row.get("n_number") or "").upper().strip()
            if not tail.startswith("N"):
                tail = "N" + tail if tail else tail
            owner = (
                row.get("owner") or row.get("owner_name") or row.get("name") or ""
            ).strip()
            model = (row.get("model") or "").strip()
            manufacturer = (row.get("manufacturer") or "").strip()
            if tail:
                owner_by_reg[tail] = owner
                model_by_reg[tail] = f"{manufacturer} {model}".strip() or model

    by_date = defaultdict(list)
    for registration, timestamp in rows:
        parsed = parse_ts(timestamp)
        if parsed:
            by_date[parsed.date().isoformat()].append((registration, parsed))

    edge_weights = Counter()
    aircraft_sightings = Counter(registration for registration, _timestamp in rows)
    window = timedelta(minutes=args.window_min)
    for items in by_date.values():
        items.sort(key=lambda item: item[1])
        for index, (left_reg, left_ts) in enumerate(items):
            for right_reg, right_ts in items[index + 1 :]:
                if right_ts - left_ts > window:
                    break
                if left_reg != right_reg:
                    edge_weights[tuple(sorted([left_reg, right_reg]))] += 1

    edges = [
        (left, right, weight)
        for (left, right), weight in edge_weights.items()
        if weight >= args.min_cooccur
    ]
    edges.sort(key=lambda row: -row[2])

    adjacency = defaultdict(set)
    for left, right, _weight in edges:
        adjacency[left].add(right)
        adjacency[right].add(left)
    communities = (
        greedy_communities(
            adjacency,
            {tuple(sorted([left, right])): weight for left, right, weight in edges},
        )
        if adjacency
        else {}
    )

    nodes = []
    for registration in adjacency:
        nodes.append(
            {
                "registration": registration,
                "owner": owner_by_reg.get(registration, "?"),
                "model": model_by_reg.get(registration, "?"),
                "sightings": aircraft_sightings.get(registration, 0),
                "degree": len(adjacency[registration]),
                "weighted_degree": sum(
                    edge_weights[tuple(sorted([registration, neighbor]))]
                    for neighbor in adjacency[registration]
                ),
                "audit_group_id": communities.get(registration, -1),
            }
        )
    nodes.sort(key=lambda row: -row["weighted_degree"])

    OUTS.mkdir(parents=True, exist_ok=True)
    with (OUTS / "audit_network_edges.csv").open("w", newline="") as handle:
        writer = csv.writer(handle, quoting=csv.QUOTE_ALL)
        writer.writerow(
            [
                "aircraft_a",
                "aircraft_b",
                "n_cooccurrences",
                "owner_a",
                "owner_b",
                "audit_group_a",
                "audit_group_b",
                "relationship_state",
            ]
        )
        for left, right, weight in edges:
            writer.writerow(
                [
                    left,
                    right,
                    weight,
                    owner_by_reg.get(left, "?"),
                    owner_by_reg.get(right, "?"),
                    communities.get(left, -1),
                    communities.get(right, -1),
                    "CO_OCCURRENCE_ONLY",
                ]
            )

    node_fields = [
        "registration",
        "owner",
        "model",
        "sightings",
        "degree",
        "weighted_degree",
        "audit_group_id",
    ]
    with (OUTS / "audit_network_nodes.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=node_fields, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(nodes)

    by_group = defaultdict(list)
    for node in nodes:
        by_group[node["audit_group_id"]].append(node)
    with (OUTS / "audit_network_groups.csv").open("w", newline="") as handle:
        writer = csv.writer(handle, quoting=csv.QUOTE_ALL)
        writer.writerow(
            ["audit_group_id", "n_aircraft", "total_sightings", "top_aircraft", "owners"]
        )
        for group_id, group_nodes in sorted(
            by_group.items(),
            key=lambda item: -sum(node["sightings"] for node in item[1]),
        ):
            top = ", ".join(
                f"{node['registration']}({node['sightings']})"
                for node in sorted(
                    group_nodes, key=lambda item: -item["sightings"]
                )[:5]
            )
            owners = ", ".join(
                f"{owner}({count})"
                for owner, count in Counter(
                    node["owner"] for node in group_nodes
                ).most_common(5)
            )
            writer.writerow(
                [
                    group_id,
                    len(group_nodes),
                    sum(node["sightings"] for node in group_nodes),
                    top,
                    owners,
                ]
            )

    conn.close()
    result = {
        "classification": "NONCANONICAL",
        "certification_state": "AUDIT_ONLY",
        "relationship_state": "CO_OCCURRENCE_ONLY",
        "edges_emitted": len(edges),
        "nodes_in_network": len(adjacency),
        "audit_groups_found": len(set(communities.values())) if communities else 0,
        "outputs": [
            str((OUTS / "audit_network_edges.csv").relative_to(REPO)),
            str((OUTS / "audit_network_nodes.csv").relative_to(REPO)),
            str((OUTS / "audit_network_groups.csv").relative_to(REPO)),
        ],
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
