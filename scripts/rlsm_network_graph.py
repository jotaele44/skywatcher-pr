#!/usr/bin/env python3
"""Phase B: deterministic aircraft co-occurrence network.

Edges are two aircraft seen within a configured time window on the same date.
Nodes are aircraft registrations enriched with FAA owner and sighting volume.
The HTML output uses only inline SVG and JavaScript; it has no CDN or hosted
runtime dependency.
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

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
    """Assign each node to its highest-weight neighboring community."""
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


def _json_for_inline_script(value: Any) -> str:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        .replace("</", "<\\/")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def render_network_html(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    window_min: int,
    min_cooccur: int,
) -> str:
    """Render a deterministic, self-contained SVG network."""
    node_json = _json_for_inline_script(nodes)
    edge_json = _json_for_inline_script(edges)
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<title>RLSM Aircraft Co-occurrence Network</title>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  :root{{color-scheme:light dark;font-family:system-ui,-apple-system,sans-serif}}
  body{{margin:0;background:#111827;color:#e5e7eb}}
  header{{padding:12px 18px;border-bottom:1px solid #374151}}
  h1{{font-size:18px;margin:0 0 4px}}
  .note{{font-size:12px;color:#9ca3af}}
  .layout{{display:grid;grid-template-columns:minmax(0,1fr) 340px;min-height:calc(100vh - 76px)}}
  #network{{width:100%;height:calc(100vh - 76px);background:#0f172a}}
  aside{{padding:14px;border-left:1px solid #374151;overflow:auto}}
  #info{{white-space:pre-wrap;font-size:13px;line-height:1.45}}
  .edge{{stroke:#64748b;stroke-opacity:.38}}
  .node{{stroke:#f8fafc;stroke-width:.8;cursor:pointer}}
  .node:focus{{outline:none;stroke:#facc15;stroke-width:3}}
  .label{{font-size:9px;fill:#e5e7eb;pointer-events:none;text-anchor:middle}}
  @media(max-width:850px){{.layout{{grid-template-columns:1fr}}aside{{border-left:0;border-top:1px solid #374151}}#network{{height:65vh}}}}
</style>
</head><body>
<header>
  <h1>RLSM aircraft co-occurrence network — {len(nodes)} aircraft, {len(edges)} edges</h1>
  <div class="note">Window ±{window_min} min; minimum {min_cooccur} co-occurrences. Deterministic offline SVG: no CDN, remote script, or hosted graph service.</div>
</header>
<div class="layout">
  <svg id="network" viewBox="0 0 1300 820" role="img" aria-label="Aircraft co-occurrence network"></svg>
  <aside><h2>Selected aircraft</h2><div id="info">Select or focus a node. Colors represent greedy communities; size represents weighted degree.</div></aside>
</div>
<script>
"use strict";
const nodes = {node_json};
const edges = {edge_json};
const svg = document.getElementById("network");
const info = document.getElementById("info");
const NS = "http://www.w3.org/2000/svg";
const width = 1300, height = 820;
function element(name, attrs = {{}}) {{
  const node = document.createElementNS(NS, name);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
  return node;
}}
const grouped = new Map();
for (const node of nodes) {{
  const key = Number(node.community_id);
  if (!grouped.has(key)) grouped.set(key, []);
  grouped.get(key).push(node);
}}
const communityIds = Array.from(grouped.keys()).sort((a,b) => a-b);
const positions = new Map();
communityIds.forEach((communityId, communityIndex) => {{
  const members = grouped.get(communityId).slice().sort((a,b) => String(a.id).localeCompare(String(b.id)));
  const communityAngle = communityIds.length === 1 ? 0 : 2 * Math.PI * communityIndex / communityIds.length;
  const centerX = width / 2 + Math.cos(communityAngle) * Math.min(390, 70 * communityIds.length);
  const centerY = height / 2 + Math.sin(communityAngle) * Math.min(260, 48 * communityIds.length);
  const localRadius = Math.max(34, Math.min(145, members.length * 7));
  members.forEach((node, memberIndex) => {{
    const angle = members.length === 1 ? 0 : 2 * Math.PI * memberIndex / members.length;
    const radius = members.length === 1 ? 0 : localRadius;
    positions.set(node.id, {{x:centerX + Math.cos(angle) * radius, y:centerY + Math.sin(angle) * radius}});
  }});
}});
for (const edge of edges) {{
  const start = positions.get(edge.from), end = positions.get(edge.to);
  if (!start || !end) continue;
  const line = element("line", {{
    x1:start.x,y1:start.y,x2:end.x,y2:end.y,class:"edge",
    "stroke-width":Math.max(1, Math.min(7, 1 + Math.log1p(Number(edge.value)))),
  }});
  const title = element("title"); title.textContent = edge.title; line.append(title); svg.append(line);
}}
function describe(node) {{
  return [
    node.id,
    "Owner: " + (node.owner || "?"),
    "Model: " + (node.model || "?"),
    "Sightings: " + node.sightings,
    "Co-occurrence partners: " + node.degree,
    "Weighted degree: " + node.value,
    "Community: " + node.community_id,
  ].join("\\n");
}}
for (const node of nodes) {{
  const position = positions.get(node.id);
  if (!position) continue;
  const radius = Math.max(6, Math.min(23, 6 + Math.log1p(Number(node.value)) * 2.8));
  const circle = element("circle", {{
    cx:position.x,cy:position.y,r:radius,fill:node.color,class:"node",tabindex:0,
    role:"button","aria-label":node.id,
  }});
  const title = element("title"); title.textContent = describe(node); circle.append(title);
  const select = () => {{ info.textContent = describe(node); }};
  circle.addEventListener("click", select); circle.addEventListener("focus", select); svg.append(circle);
  const label = element("text", {{x:position.x,y:position.y+radius+12,class:"label"}});
  label.textContent = node.label; svg.append(label);
}}
</script>
</body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--window-min",
        type=int,
        default=10,
        help="Two aircraft co-occur if same-date and within this many minutes",
    )
    parser.add_argument("--min-cooccur", type=int, default=2, help="Drop weaker edges")
    args = parser.parse_args()

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

    owner_by_registration = {}
    model_by_registration = {}
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
                owner_by_registration[tail] = owner
                model_by_registration[tail] = f"{manufacturer} {model}".strip() or model

    by_date_registration = defaultdict(list)
    for registration, timestamp in rows:
        parsed = parse_ts(timestamp)
        if parsed:
            by_date_registration[(parsed.date().isoformat(), registration)].append(parsed)

    by_date = defaultdict(list)
    for (date, registration), timestamps in by_date_registration.items():
        for timestamp in timestamps:
            by_date[date].append((registration, timestamp))

    edge_weights = Counter()
    aircraft_sightings = Counter(registration for registration, _ in rows)
    window = timedelta(minutes=args.window_min)
    for items in by_date.values():
        items.sort(key=lambda item: item[1])
        for index, (registration, timestamp) in enumerate(items):
            for other_registration, other_timestamp in items[index + 1 :]:
                if other_timestamp - timestamp > window:
                    break
                if registration != other_registration:
                    edge_weights[tuple(sorted([registration, other_registration]))] += 1

    edges = [
        (left, right, weight)
        for (left, right), weight in edge_weights.items()
        if weight >= args.min_cooccur
    ]
    edges.sort(key=lambda item: -item[2])

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

    nodes_csv = []
    for registration in adjacency:
        nodes_csv.append(
            {
                "registration": registration,
                "owner": owner_by_registration.get(registration, "?"),
                "model": model_by_registration.get(registration, "?"),
                "sightings": aircraft_sightings.get(registration, 0),
                "degree": len(adjacency[registration]),
                "weighted_degree": sum(
                    edge_weights[tuple(sorted([registration, neighbor]))]
                    for neighbor in adjacency[registration]
                ),
                "community_id": communities.get(registration, -1),
            }
        )
    nodes_csv.sort(key=lambda item: -item["weighted_degree"])

    OUTS.mkdir(parents=True, exist_ok=True)
    with (OUTS / "intel_network_edges.csv").open("w", newline="") as handle:
        writer = csv.writer(handle, quoting=csv.QUOTE_ALL)
        writer.writerow(
            [
                "aircraft_a",
                "aircraft_b",
                "n_cooccurrences",
                "owner_a",
                "owner_b",
                "community_a",
                "community_b",
            ]
        )
        for left, right, weight in edges:
            writer.writerow(
                [
                    left,
                    right,
                    weight,
                    owner_by_registration.get(left, "?"),
                    owner_by_registration.get(right, "?"),
                    communities.get(left, -1),
                    communities.get(right, -1),
                ]
            )

    with (OUTS / "intel_network_nodes.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "registration",
                "owner",
                "model",
                "sightings",
                "degree",
                "weighted_degree",
                "community_id",
            ],
            quoting=csv.QUOTE_ALL,
        )
        writer.writeheader()
        writer.writerows(nodes_csv)

    by_community = defaultdict(list)
    for node in nodes_csv:
        by_community[node["community_id"]].append(node)
    with (OUTS / "intel_network_communities.csv").open("w", newline="") as handle:
        writer = csv.writer(handle, quoting=csv.QUOTE_ALL)
        writer.writerow(
            ["community_id", "n_aircraft", "total_sightings", "top_aircraft", "owners"]
        )
        ordered = sorted(
            by_community.items(),
            key=lambda item: -sum(node["sightings"] for node in item[1]),
        )
        for community_id, members in ordered:
            top = ", ".join(
                f"{node['registration']}({node['sightings']})"
                for node in sorted(members, key=lambda item: -item["sightings"])[:5]
            )
            owners = ", ".join(
                f"{owner}({count})"
                for owner, count in Counter(node["owner"] for node in members).most_common(5)
            )
            writer.writerow(
                [
                    community_id,
                    len(members),
                    sum(node["sightings"] for node in members),
                    top,
                    owners,
                ]
            )

    palette = [
        "#1f77b4",
        "#ff7f0e",
        "#2ca02c",
        "#d62728",
        "#9467bd",
        "#8c564b",
        "#e377c2",
        "#7f7f7f",
        "#bcbd22",
        "#17becf",
        "#0066cc",
        "#cc6600",
        "#660066",
        "#009933",
        "#cc3399",
        "#003366",
        "#996633",
        "#669900",
    ]
    node_objects = []
    for node in nodes_csv[:120]:
        community_id = node["community_id"]
        color = palette[community_id % len(palette)] if community_id >= 0 else "#cccccc"
        node_objects.append(
            {
                "id": node["registration"],
                "label": node["registration"],
                "owner": node["owner"],
                "model": node["model"],
                "sightings": node["sightings"],
                "degree": node["degree"],
                "value": node["weighted_degree"],
                "community_id": community_id,
                "color": color,
            }
        )
    retained_ids = {node["id"] for node in node_objects}
    edge_objects = [
        {
            "from": left,
            "to": right,
            "value": weight,
            "title": f"{weight} co-occurrences",
        }
        for left, right, weight in edges[:400]
        if left in retained_ids and right in retained_ids
    ]
    (OUTS / "intel_network.html").write_text(
        render_network_html(
            node_objects,
            edge_objects,
            window_min=args.window_min,
            min_cooccur=args.min_cooccur,
        ),
        encoding="utf-8",
    )

    conn.close()
    print(
        json.dumps(
            {
                "edges_emitted": len(edges),
                "nodes_in_network": len(adjacency),
                "communities_found": len(set(communities.values())) if communities else 0,
                "top_edges": [
                    {
                        "a": left,
                        "b": right,
                        "weight": weight,
                        "owner_a": owner_by_registration.get(left, "?"),
                        "owner_b": owner_by_registration.get(right, "?"),
                    }
                    for left, right, weight in edges[:10]
                ],
                "outputs": [
                    "outputs/intel_network_edges.csv",
                    "outputs/intel_network_nodes.csv",
                    "outputs/intel_network_communities.csv",
                    "outputs/intel_network.html",
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
