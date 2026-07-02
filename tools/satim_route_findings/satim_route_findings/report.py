"""Report rendering for SATIM route findings."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from .cluster_summary import build_route_cluster_summary
from .fn_candidates import build_fn_candidate_summary
from .loaders import load_required_ledgers
from .review_queue import build_review_queue
from .schemas import REQUIRED_FILENAMES, validate_ledgers
from .util import require_safe_output_dir


ROUTE_CLUSTER_COLUMNS = (
    "cluster_id",
    "source",
    "spatial_bucket",
    "row_class",
    "row_count",
    "verification_score_avg",
    "verification_score_min",
    "verification_score_max",
    "first_timestamp",
    "last_timestamp",
)

FN_CANDIDATE_COLUMNS = (
    "fn_candidate_id",
    "track_node_id",
    "source",
    "label",
    "vertex_count",
    "confidence_avg",
    "confidence_min",
    "confidence_max",
)

REVIEW_QUEUE_COLUMNS = ("review_id", "source", "reason", "detail", "severity")


def write_csv(path: Path, fieldnames: Iterable[str], rows: Iterable[dict[str, object]]) -> None:
    """Write deterministic CSV output."""

    columns = tuple(fieldnames)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def render_markdown_report(
    cluster_rows: list[dict[str, object]],
    fn_rows: list[dict[str, object]],
    review_rows: list[dict[str, object]],
) -> str:
    """Render a compact provenance-bound Markdown report."""

    return "\n".join(
        [
            "# SATIM route findings report",
            "",
            "## Summary",
            "",
            f"- Route clusters: {len(cluster_rows)}",
            f"- Candidate route-network groups: {len(fn_rows)}",
            f"- Review queue rows: {len(review_rows)}",
            "",
            "## Output files",
            "",
            "- `route_cluster_summary.csv`",
            "- `fn_candidate_summary.csv`",
            "- `review_queue.csv`",
            "",
            "## Guardrails",
            "",
            "- Inputs are read only.",
            "- Outputs are written only to the requested output directory.",
            "- Findings are summaries, not ground truth claims.",
            "- Visual-estimate rows remain separated from coordinate-track rows when provenance indicates visual input.",
            "",
        ]
    )


def run_analysis(input_dir: str | Path, output_dir: str | Path) -> dict[str, int]:
    """Run the read-only route findings analysis."""

    safe_output = require_safe_output_dir(input_dir, output_dir)
    ledgers = load_required_ledgers(input_dir, REQUIRED_FILENAMES)
    validate_ledgers(ledgers)

    track_rows = ledgers["SATIM_TRACK_LEDGER.csv"].rows
    graph_nodes = ledgers["SATIM_GRAPH_NODES.csv"].rows
    graph_edges = ledgers["SATIM_GRAPH_EDGES.csv"].rows
    error_rows = ledgers["SATIM_ERROR_LEDGER.csv"].rows

    cluster_rows = build_route_cluster_summary(track_rows)
    fn_rows = build_fn_candidate_summary(graph_nodes, graph_edges)
    review_rows = build_review_queue(track_rows, error_rows)

    write_csv(safe_output / "route_cluster_summary.csv", ROUTE_CLUSTER_COLUMNS, cluster_rows)
    write_csv(safe_output / "fn_candidate_summary.csv", FN_CANDIDATE_COLUMNS, fn_rows)
    write_csv(safe_output / "review_queue.csv", REVIEW_QUEUE_COLUMNS, review_rows)
    (safe_output / "route_findings_report.md").write_text(
        render_markdown_report(cluster_rows, fn_rows, review_rows), encoding="utf-8"
    )

    return {
        "route_clusters": len(cluster_rows),
        "fn_candidates": len(fn_rows),
        "review_rows": len(review_rows),
    }
