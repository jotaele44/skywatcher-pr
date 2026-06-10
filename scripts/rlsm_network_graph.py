#!/usr/bin/env python3
"""
Phase B: Aircraft co-occurrence network.

Edges = two aircraft seen within ±10 min on the same date.
Nodes  = aircraft (registration), enriched with FAA owner + sightings volume.

Outputs:
  - outputs/intel_network_edges.csv     pairwise co-occurrence counts
  - outputs/intel_network_nodes.csv     aircraft nodes with degree/centrality
  - outputs/intel_network_communities.csv  community labels (greedy modularity)
  - outputs/intel_network.html          interactive network (vis-network CDN)

CLI:
    python3 scripts/rlsm_network_graph.py
    python3 scripts/rlsm_network_graph.py --window-min 15 --min-cooccur 2
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
OUTS = REPO / "outputs"
FAA_CSV = REPO / "data" / "faa_registry_consolidated.csv"


def parse_ts(s):
    if not s or len(s) < 16: return None
    try: return datetime.fromisoformat(s.replace("Z","+00:00"))
    except ValueError: return None


def greedy_communities(adj: dict, edge_weights: dict) -> dict:
    """Cheap greedy community detection: assign each node to the community of
    its highest-weighted neighbor. Iterate until stable."""
    # Initial: each node its own community
    comm = {n: i for i, n in enumerate(adj.keys())}
    changed = True
    iterations = 0
    while changed and iterations < 20:
        changed = False
        iterations += 1
        for n in adj:
            neighbor_weights = Counter()
            for m in adj[n]:
                w = edge_weights.get(tuple(sorted([n, m])), 0)
                neighbor_weights[comm[m]] += w
            if neighbor_weights:
                best = neighbor_weights.most_common(1)[0][0]
                if best != comm[n]:
                    comm[n] = best
                    changed = True
    # Compact community IDs
    remap = {c: i for i, c in enumerate(sorted(set(comm.values())))}
    return {n: remap[c] for n, c in comm.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window-min", type=int, default=10,
                    help="Two aircraft co-occur if same-date & within this many min")
    ap.add_argument("--min-cooccur", type=int, default=2,
                    help="Drop edges weaker than this")
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(screenshots)")}
    ts_expr = "COALESCE(s.true_flight_ts, s.filename_ts)" if "true_flight_ts" in cols else "s.filename_ts"

    rows = conn.execute(f"""
        SELECT a.registration, {ts_expr} AS ts
        FROM aircraft_observations a
        JOIN screenshots s USING(screenshot_id)
        WHERE a.registration IS NOT NULL AND {ts_expr} IS NOT NULL
        ORDER BY ts
    """).fetchall()

    # FAA enrichment
    owner_by_reg = {}
    model_by_reg = {}
    if FAA_CSV.exists():
        for r in csv.DictReader(FAA_CSV.open()):
            tail = (r.get("registration") or r.get("n_number") or "").upper().strip()
            if not tail.startswith("N"):
                tail = "N" + tail if tail else tail
            owner = (r.get("owner") or r.get("owner_name") or r.get("name") or "").strip()
            model = (r.get("model") or "").strip()
            mfr   = (r.get("manufacturer") or "").strip()
            if tail:
                owner_by_reg[tail] = owner
                model_by_reg[tail] = f"{mfr} {model}".strip() or model

    # Build (date, reg) -> list of timestamps
    by_date_reg = defaultdict(list)
    for reg, ts in rows:
        dt = parse_ts(ts)
        if dt:
            by_date_reg[(dt.date().isoformat(), reg)].append(dt)

    # Find co-occurrences within window: pivot to per-date list of (reg, ts) sorted
    by_date = defaultdict(list)
    for (d, reg), ts_list in by_date_reg.items():
        for ts in ts_list:
            by_date[d].append((reg, ts))

    edge_weights = Counter()
    aircraft_sightings = Counter(r for r, _ in rows)
    window = timedelta(minutes=args.window_min)

    for d, items in by_date.items():
        items.sort(key=lambda x: x[1])
        # Sliding window
        n = len(items)
        for i in range(n):
            reg_i, ts_i = items[i]
            for j in range(i + 1, n):
                reg_j, ts_j = items[j]
                if ts_j - ts_i > window:
                    break
                if reg_i != reg_j:
                    key = tuple(sorted([reg_i, reg_j]))
                    edge_weights[key] += 1

    # Filter weak edges
    edges = [(a, b, w) for (a, b), w in edge_weights.items() if w >= args.min_cooccur]
    edges.sort(key=lambda x: -x[2])

    # Build adjacency
    adj = defaultdict(set)
    for a, b, w in edges:
        adj[a].add(b); adj[b].add(a)

    # Community detection
    communities = greedy_communities(adj, {tuple(sorted([a,b])): w for a,b,w in edges}) if adj else {}

    # Node-level metrics
    nodes_csv = []
    for reg in adj:
        nodes_csv.append({
            "registration": reg,
            "owner": owner_by_reg.get(reg, "?"),
            "model": model_by_reg.get(reg, "?"),
            "sightings": aircraft_sightings.get(reg, 0),
            "degree": len(adj[reg]),
            "weighted_degree": sum(edge_weights[tuple(sorted([reg, n]))] for n in adj[reg]),
            "community_id": communities.get(reg, -1),
        })
    nodes_csv.sort(key=lambda x: -x["weighted_degree"])

    OUTS.mkdir(parents=True, exist_ok=True)
    with (OUTS / "intel_network_edges.csv").open("w", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        w.writerow(["aircraft_a", "aircraft_b", "n_cooccurrences",
                    "owner_a", "owner_b", "community_a", "community_b"])
        for a, b, weight in edges:
            w.writerow([a, b, weight,
                        owner_by_reg.get(a, "?"), owner_by_reg.get(b, "?"),
                        communities.get(a, -1), communities.get(b, -1)])

    with (OUTS / "intel_network_nodes.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["registration","owner","model","sightings",
                                           "degree","weighted_degree","community_id"],
                           quoting=csv.QUOTE_ALL)
        w.writeheader()
        for n in nodes_csv:
            w.writerow(n)

    # Per-community rollup
    by_comm = defaultdict(list)
    for n in nodes_csv:
        by_comm[n["community_id"]].append(n)
    with (OUTS / "intel_network_communities.csv").open("w", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        w.writerow(["community_id", "n_aircraft", "total_sightings",
                    "top_aircraft", "owners"])
        for cid, nlist in sorted(by_comm.items(), key=lambda x: -sum(n["sightings"] for n in x[1])):
            top = ", ".join(f"{n['registration']}({n['sightings']})"
                            for n in sorted(nlist, key=lambda x: -x["sightings"])[:5])
            owners = ", ".join(f"{o}({c})" for o, c in
                               Counter(n["owner"] for n in nlist).most_common(5))
            w.writerow([cid, len(nlist), sum(n["sightings"] for n in nlist), top, owners])

    # HTML network — vis-network CDN
    palette = ["#1f77b4","#ff7f0e","#2ca02c","#d62728","#9467bd","#8c564b",
               "#e377c2","#7f7f7f","#bcbd22","#17becf","#0066cc","#cc6600",
               "#660066","#009933","#cc3399","#003366","#996633","#669900"]
    node_objs = []
    for n in nodes_csv[:120]:  # cap for browser
        size = 8 + min(40, n["weighted_degree"] * 0.5)
        color = palette[n["community_id"] % len(palette)] if n["community_id"] >= 0 else "#cccccc"
        node_objs.append({
            "id": n["registration"],
            "label": n["registration"],
            "title": (f"{n['registration']}\nOwner: {n['owner']}\nModel: {n['model']}\n"
                      f"Sightings: {n['sightings']}\nCo-occur partners: {n['degree']}\n"
                      f"Community: {n['community_id']}"),
            "value": n["weighted_degree"],
            "color": color,
            "shape": "dot",
        })
    keep_ids = {n["id"] for n in node_objs}
    edge_objs = [{"from": a, "to": b, "value": weight, "title": f"{weight} co-occurrences"}
                 for a, b, weight in edges[:400] if a in keep_ids and b in keep_ids]

    html = f"""<!DOCTYPE html>
<html><head>
<title>RLSM Aircraft Co-occurrence Network</title>
<meta charset="utf-8">
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>
  body{{margin:0;font-family:-apple-system,sans-serif;}}
  #net{{width:100%;height:100vh;border:1px solid #ddd;}}
  h1{{position:fixed;top:10px;left:50px;background:rgba(255,255,255,0.9);padding:6px 12px;border-radius:6px;z-index:1000;font-size:14px;margin:0;}}
  #info{{position:fixed;bottom:10px;left:10px;background:rgba(255,255,255,0.95);padding:8px;font-size:11px;max-width:380px;border:1px solid #888;border-radius:6px;}}
</style>
</head><body>
<h1>RLSM aircraft co-occurrence network — {len(node_objs)} top aircraft, {len(edge_objs)} edges (window ±{args.window_min}min, ≥{args.min_cooccur} co-occur)</h1>
<div id="net"></div>
<div id="info">Hover a node for FAA owner & model. Colors = greedy communities. Node size ∝ weighted degree.</div>
<script>
var nodes = new vis.DataSet({json.dumps(node_objs)});
var edges = new vis.DataSet({json.dumps(edge_objs)});
var container = document.getElementById('net');
var data = {{nodes: nodes, edges: edges}};
var options = {{
  nodes: {{font:{{size:11}}, scaling:{{min:8, max:40}}}},
  edges: {{scaling:{{min:1, max:6}}, color:{{color:"#bbb", opacity:0.5}}, smooth:false}},
  physics: {{barnesHut: {{gravitationalConstant:-3000, springLength:120}}, stabilization:{{iterations:200}}}}
}};
new vis.Network(container, data, options);
</script>
</body></html>"""
    (OUTS / "intel_network.html").write_text(html)

    conn.close()
    print(json.dumps({
        "edges_emitted": len(edges),
        "nodes_in_network": len(adj),
        "communities_found": len(set(communities.values())) if communities else 0,
        "top_edges": [{"a": a, "b": b, "weight": weight,
                        "owner_a": owner_by_reg.get(a, "?"),
                        "owner_b": owner_by_reg.get(b, "?")} for a, b, weight in edges[:10]],
        "outputs": [
            "outputs/intel_network_edges.csv",
            "outputs/intel_network_nodes.csv",
            "outputs/intel_network_communities.csv",
            "outputs/intel_network.html",
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
