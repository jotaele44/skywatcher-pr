#!/usr/bin/env python3
"""
Cluster detected FR24 map icons by perceptual hash, so the operator names each
glyph class once instead of reviewing every recurrence.

UI glyphs are pixel-identical between renders — the same heliport icon on ten
thousand frames produces the same 64-bit average hash. Clustering therefore
collapses the corpus to a few dozen classes. Naming those classes once and
letting every member inherit the type is the "review clusters, not items" rule
from docs/SCREENSHOT_DATA_STRATEGY.md §5, applied to the icon channel.

Two phases:

    # 1. cluster + emit the naming file for the operator to fill in
    python3 scripts/rlsm_icon_cluster.py

    # 2. after editing data/reference/icon_classes.json, write classes back
    python3 scripts/rlsm_icon_cluster.py --apply

Clustering is single-link over Hamming distance on the hash, with hue used as a
tie-breaker: two glyphs of identical silhouette but different colour (an active
vs inactive airport marker) are kept apart, because the hash sees shape and the
hue carries the rest.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
CLASSES_JSON = REPO / "data" / "reference" / "icon_classes.json"

# Two hashes within this Hamming distance are the same glyph. 64-bit hash, so 6
# bits is ~9% of the signal — tolerant of antialiasing, tight enough that
# distinct glyphs stay apart.
HAMMING_THRESHOLD = 6

# Hue separation (degrees) above which same-silhouette glyphs are split. Hue is
# circular, so this compares the short way round.
HUE_SPLIT_DEG = 40.0


def hamming(a: str, b: str) -> int:
    try:
        return bin(int(a, 16) ^ int(b, 16)).count("1")
    except ValueError:
        return 64


def hue_gap(a: float, b: float) -> float:
    d = abs((a or 0.0) - (b or 0.0)) % 360.0
    return min(d, 360.0 - d)


def cluster(rows: List[tuple], threshold: int = HAMMING_THRESHOLD,
            hue_split: float = HUE_SPLIT_DEG) -> Dict[str, int]:
    """
    Single-link cluster over (ahash, mean_hue) representatives.

    ``rows`` is ``(ahash, count, mean_hue, mean_sat)`` per distinct hash — the
    corpus is grouped by hash first, so this runs over a few thousand distinct
    values rather than millions of rows.

    Returns ahash -> cluster_id.
    """
    reps: List[dict] = []          # cluster representatives
    assign: Dict[str, int] = {}
    # Most frequent first, so the dominant glyph defines each cluster's centre.
    for ahash, count, mean_hue, _mean_sat in sorted(rows, key=lambda r: -r[1]):
        placed = False
        for rep in reps:
            if (hamming(ahash, rep["ahash"]) <= threshold
                    and hue_gap(mean_hue, rep["hue"]) <= hue_split):
                assign[ahash] = rep["id"]
                rep["members"] += count
                placed = True
                break
        if not placed:
            cid = len(reps) + 1
            reps.append({"id": cid, "ahash": ahash, "hue": mean_hue or 0.0,
                         "members": count})
            assign[ahash] = cid
    return assign


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="Write icon_class back from the edited naming file.")
    ap.add_argument("--threshold", type=int, default=HAMMING_THRESHOLD)
    args = ap.parse_args()

    if not DB.exists():
        print(f"[icon-cluster] no DB at {DB}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(DB), timeout=30.0)
    conn.execute("PRAGMA busy_timeout = 30000")

    has_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='icon_observations'"
    ).fetchone()
    if not has_table:
        print("[icon-cluster] icon_observations does not exist — run the icons "
              "stage first (./run-rlsm.sh --stage icons)", file=sys.stderr)
        return 1

    if args.apply:
        return _apply(conn)

    rows = conn.execute(
        """SELECT ahash, COUNT(*) AS n, AVG(hue_deg), AVG(saturation)
           FROM icon_observations
           WHERE ahash IS NOT NULL AND ahash != ''
           GROUP BY ahash ORDER BY n DESC"""
    ).fetchall()
    if not rows:
        print("[icon-cluster] no icons detected yet", file=sys.stderr)
        return 1

    assign = cluster(rows, threshold=args.threshold)

    conn.execute("UPDATE icon_observations SET cluster_id = NULL")
    for ahash, cid in assign.items():
        conn.execute("UPDATE icon_observations SET cluster_id=? WHERE ahash=?",
                     (cid, ahash))
    conn.commit()

    # Summarise each cluster for the naming file.
    summary = conn.execute(
        """SELECT cluster_id, COUNT(*) n, AVG(hue_deg), AVG(saturation), AVG(value),
                  AVG(area_px), AVG(aspect), AVG(fill_ratio),
                  COUNT(DISTINCT ahash), COUNT(DISTINCT screenshot_id)
           FROM icon_observations WHERE cluster_id IS NOT NULL
           GROUP BY cluster_id ORDER BY n DESC"""
    ).fetchall()

    existing: Dict[str, str] = {}
    if CLASSES_JSON.exists():
        try:
            prior = json.loads(CLASSES_JSON.read_text())
            existing = {str(c["cluster_id"]): c.get("icon_class", "")
                        for c in prior.get("clusters", [])}
        except (ValueError, KeyError, TypeError):
            pass

    clusters = []
    for (cid, n, hue, sat, val, area, aspect, fill, n_hash, n_shots) in summary:
        # Sample labels this glyph sits beside — the strongest hint when naming.
        labels = [r[0] for r in conn.execute(
            """SELECT p.normalized_label, COUNT(*) c
               FROM icon_observations i JOIN labeled_pins p ON p.pin_id = i.pin_id
               WHERE i.cluster_id = ? AND p.normalized_label IS NOT NULL
               GROUP BY 1 ORDER BY c DESC LIMIT 5""", (cid,))]
        types = [f"{r[0]}:{r[1]}" for r in conn.execute(
            """SELECT p.pin_type_guess, COUNT(*) c
               FROM icon_observations i JOIN labeled_pins p ON p.pin_id = i.pin_id
               WHERE i.cluster_id = ? GROUP BY 1 ORDER BY c DESC LIMIT 4""", (cid,))]
        clusters.append({
            "cluster_id": cid,
            "icon_class": existing.get(str(cid), ""),   # operator fills this in
            "count": n,
            "distinct_screenshots": n_shots,
            "distinct_hashes": n_hash,
            "hue_deg": round(hue or 0, 1),
            "saturation": round(sat or 0, 3),
            "value": round(val or 0, 3),
            "area_px": round(area or 0, 1),
            "aspect": round(aspect or 0, 2),
            "fill_ratio": round(fill or 0, 3),
            "adjacent_labels": labels,
            "adjacent_pin_types": types,
        })

    CLASSES_JSON.parent.mkdir(parents=True, exist_ok=True)
    CLASSES_JSON.write_text(json.dumps({
        "_comment": ("Fill in icon_class for each cluster, then run "
                     "`python3 scripts/rlsm_icon_cluster.py --apply`. "
                     "Suggested vocabulary: airport, heliport, aircraft, navaid, "
                     "city_dot, seaport, ui_chrome, noise."),
        "hamming_threshold": args.threshold,
        "hue_split_deg": HUE_SPLIT_DEG,
        "clusters": clusters,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    total = sum(c["count"] for c in clusters)
    named = sum(1 for c in clusters if c["icon_class"])
    print(json.dumps({
        "distinct_hashes": len(rows),
        "clusters": len(clusters),
        "icons_total": total,
        "already_named": named,
        "naming_file": str(CLASSES_JSON.relative_to(REPO)),
        "top_clusters": [
            {"cluster_id": c["cluster_id"], "count": c["count"],
             "hue_deg": c["hue_deg"], "adjacent_pin_types": c["adjacent_pin_types"]}
            for c in clusters[:10]
        ],
    }, indent=2))
    conn.close()
    return 0


def _apply(conn: sqlite3.Connection) -> int:
    if not CLASSES_JSON.exists():
        print(f"[icon-cluster] {CLASSES_JSON} not found — run without --apply first",
              file=sys.stderr)
        return 1
    data = json.loads(CLASSES_JSON.read_text())
    n = 0
    for c in data.get("clusters", []):
        name = (c.get("icon_class") or "").strip()
        if not name:
            continue
        conn.execute("UPDATE icon_observations SET icon_class=? WHERE cluster_id=?",
                     (name, c["cluster_id"]))
        n += conn.execute("SELECT changes()").fetchone()[0]
    conn.commit()

    unnamed = conn.execute(
        "SELECT COUNT(*) FROM icon_observations WHERE icon_class IS NULL OR icon_class=''"
    ).fetchone()[0]
    print(json.dumps({"icons_classified": n, "icons_still_unnamed": unnamed}, indent=2))
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
