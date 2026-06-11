"""
EarthGPT iOS — Corridor graph stage.

Loads anomaly nodes and seams, builds corridor candidates.

Usage:
    python -m scripts.run_corridor_graph --sweep outputs/phase1_tiles.jsonl --seams outputs/seams.jsonl --out outputs/corridor_graph.jsonl
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from earthgpt.io_utils import read_jsonl, write_jsonl
from earthgpt.corridor_graph import build_corridor_candidates
from earthgpt.log_utils import log, warn
from earthgpt import config


def main() -> None:
    parser = argparse.ArgumentParser(description="Corridor graph builder")
    parser.add_argument("--sweep", required=True, help="Phase1 JSONL")
    parser.add_argument("--seams", required=True, help="Seams JSONL")
    parser.add_argument("--out", required=True, help="Output JSONL")
    parser.add_argument("--risk", type=float, default=config.RISK_THRESHOLD)
    parser.add_argument("--min_tiles", type=int, default=2)
    parser.add_argument("--max_gap", type=float, default=0.01,
                        help="Max gap in degrees between corridor nodes")
    args = parser.parse_args()

    all_nodes = read_jsonl(args.sweep)
    anomaly_nodes = [
        n for n in all_nodes
        if float(n.get("risk_final_v2_0_100", 0.0)) >= args.risk
    ]
    seams = read_jsonl(args.seams)

    log(f"Anomaly nodes: {len(anomaly_nodes)} (risk >= {args.risk})")
    log(f"Seams loaded: {len(seams)}")

    if not anomaly_nodes:
        warn("No anomaly nodes — writing empty corridor output.")
        write_jsonl(args.out, [])
        return

    corridors = build_corridor_candidates(
        anomaly_nodes,
        seams=seams,
        max_gap_deg=args.max_gap,
        min_tiles=args.min_tiles,
    )
    log(f"Corridor candidates: {len(corridors)}")

    write_jsonl(args.out, corridors)
    log(f"Corridor graph written to: {args.out}")


if __name__ == "__main__":
    main()
