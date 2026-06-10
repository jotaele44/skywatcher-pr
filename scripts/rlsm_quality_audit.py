#!/usr/bin/env python3
"""
Phase I: Quality meta-analysis. Audits the corpus along seven dimensions:

  1. OCR coverage      what % of screenshots have ANY OCR text per zone
  2. Tail resolution   labeled vs unlabeled aircraft observations
  3. Operator coverage what % of sightings have a manual-resolved operator
  4. FAA coverage      what % of US-prefix tails resolve to an FAA owner
  5. Timestamp source  filename vs FR24-timeline distribution
  6. Manual log link   what % of 2025 log entries link to screenshots
  7. Per-month density screenshots/day rolled by month

Output: outputs/intel_quality_report.md
"""
from __future__ import annotations

import csv
import json
import sqlite3
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
OUTS = REPO / "outputs"
FAA_CSV = REPO / "data" / "faa_registry_consolidated.csv"


def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    n_ss = cur.execute("SELECT COUNT(*) FROM screenshots").fetchone()[0]

    # OCR coverage per zone
    zone_counts = dict(cur.execute("""
        SELECT zone, COUNT(DISTINCT screenshot_id) FROM ocr_observations GROUP BY zone
    """).fetchall())

    # Aircraft observations: labeled vs unlabeled
    n_aobs = cur.execute("SELECT COUNT(*) FROM aircraft_observations").fetchone()[0]
    n_with_reg = cur.execute(
        "SELECT COUNT(*) FROM aircraft_observations WHERE registration IS NOT NULL").fetchone()[0]
    n_unique_reg = cur.execute(
        "SELECT COUNT(DISTINCT registration) FROM aircraft_observations WHERE registration IS NOT NULL").fetchone()[0]

    # Manual-operator coverage
    cols = {r[1] for r in cur.execute("PRAGMA table_info(aircraft_observations)")}
    n_with_manual_op = 0
    if "operator_text_manual" in cols:
        n_with_manual_op = cur.execute(
            "SELECT COUNT(*) FROM aircraft_observations WHERE operator_text_manual IS NOT NULL"
        ).fetchone()[0]

    # FAA coverage
    us_tails = {r[0] for r in cur.execute(
        "SELECT DISTINCT registration FROM aircraft_observations WHERE registration LIKE 'N%'"
    )}
    faa_tails = set()
    if FAA_CSV.exists():
        for r in csv.DictReader(FAA_CSV.open()):
            t = (r.get("registration") or "").upper().strip()
            if t and r.get("match_status", "matched") in ("matched","resolved",""):
                faa_tails.add(t)
    n_faa_resolved = len(us_tails & faa_tails)

    # Timestamp source distribution
    ts_source_dist = {}
    if "true_flight_ts_source" in {r[1] for r in cur.execute("PRAGMA table_info(screenshots)")}:
        ts_source_dist = dict(cur.execute("""
            SELECT COALESCE(true_flight_ts_source, 'unset'), COUNT(*)
            FROM screenshots GROUP BY true_flight_ts_source
        """).fetchall())

    # Manual log linking
    n_log = n_log_linked = 0
    try:
        n_log = cur.execute("SELECT COUNT(*) FROM manual_flight_log").fetchone()[0]
        n_log_linked = cur.execute(
            "SELECT COUNT(DISTINCT log_id) FROM manual_flight_log_link").fetchone()[0]
    except sqlite3.OperationalError:
        pass

    # Per-month density
    month_density = dict(cur.execute("""
        SELECT month_bucket, COUNT(*) FROM screenshots
        WHERE month_bucket IS NOT NULL
        GROUP BY month_bucket ORDER BY month_bucket
    """).fetchall())

    # Side-mining coverage (Phase F)
    side_mined = {}
    if "side_mined_at" in cols:
        side_mined["with_side_mining"] = cur.execute(
            "SELECT COUNT(*) FROM aircraft_observations WHERE side_mined_at IS NOT NULL").fetchone()[0]
        side_mined["with_iata_route"] = cur.execute(
            "SELECT COUNT(*) FROM aircraft_observations WHERE origin_iata IS NOT NULL").fetchone()[0]
        side_mined["with_heading"] = cur.execute(
            "SELECT COUNT(*) FROM aircraft_observations WHERE heading_deg_sidemined IS NOT NULL").fetchone()[0]
        side_mined["with_timeline"] = cur.execute(
            "SELECT COUNT(*) FROM aircraft_observations WHERE timeline_hours_visible IS NOT NULL").fetchone()[0]

    OUTS.mkdir(parents=True, exist_ok=True)
    md = [f"# RLSM Quality Audit\n",
          f"Total screenshots in corpus: **{n_ss:,}**\n",
          "## 1 — OCR coverage per zone\n",
          "| Zone | Screenshots with OCR text | % |", "|---|---|---|"]
    for z, c in sorted(zone_counts.items(), key=lambda x: -x[1]):
        md.append(f"| {z} | {c:,} | {100*c/max(n_ss,1):.1f}% |")
    md += ["\n## 2 — Aircraft observation resolution\n",
           f"- Aircraft observations total: **{n_aobs:,}**",
           f"- With resolved registration: **{n_with_reg:,}** ({100*n_with_reg/max(n_aobs,1):.1f}%)",
           f"- Distinct registrations: **{n_unique_reg:,}**\n",
           "## 3 — Manual operator enrichment\n",
           f"- Observations with manual operator label: **{n_with_manual_op:,}** ({100*n_with_manual_op/max(n_aobs,1):.1f}%)\n",
           "## 4 — FAA registry coverage\n",
           f"- US (N-prefix) distinct tails in corpus: **{len(us_tails):,}**",
           f"- Resolved to FAA owner: **{n_faa_resolved:,}** ({100*n_faa_resolved/max(len(us_tails),1):.1f}%)",
           f"- Unresolved US tails: {sorted(us_tails - faa_tails)[:15]}...\n",
           "## 5 — Timestamp source distribution (true_flight_ts)\n",
           "| Source | Count |", "|---|---|"]
    for src, c in sorted(ts_source_dist.items(), key=lambda x: -x[1]):
        md.append(f"| {src} | {c:,} |")
    md += ["\n## 6 — Manual log link rate\n",
           f"- Manual log entries (2025): **{n_log:,}**",
           f"- Linked to ≥1 screenshot: **{n_log_linked:,}** ({100*n_log_linked/max(n_log,1):.1f}%)\n",
           "## 7 — Per-month screenshot density\n",
           "| Month | Screenshots |", "|---|---|"]
    for m in sorted(month_density):
        md.append(f"| {m} | {month_density[m]:,} |")
    if side_mined:
        md += ["\n## 8 — Phase F side-mining coverage\n"]
        for k, v in side_mined.items():
            md.append(f"- {k}: **{v:,}** ({100*v/max(n_aobs,1):.1f}%)")

    (OUTS / "intel_quality_report.md").write_text("\n".join(md) + "\n")
    conn.close()
    print(json.dumps({
        "screenshots": n_ss,
        "aircraft_obs": n_aobs,
        "aircraft_obs_with_reg": n_with_reg,
        "distinct_regs": n_unique_reg,
        "us_tails": len(us_tails),
        "faa_resolved": n_faa_resolved,
        "ts_sources": ts_source_dist,
        "manual_log_entries": n_log,
        "manual_log_linked": n_log_linked,
        "side_mined": side_mined,
        "outputs": ["outputs/intel_quality_report.md"],
    }, indent=2))


if __name__ == "__main__":
    main()
