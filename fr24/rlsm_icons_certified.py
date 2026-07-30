"""Run adjacent and standalone icon detection against one explicit database."""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
from pathlib import Path
from typing import Any

from fr24 import rlsm_icons as adjacent
from fr24 import rlsm_standalone_icons as standalone

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
NAMING_FILE = REPO / "outputs" / "icon_classes.generated.json"
HAMMING_THRESHOLD = 6
HUE_SPLIT_DEG = 40.0


def _count(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM icon_observations").fetchone()[0])


def _hamming(a: str, b: str) -> int:
    try:
        return bin(int(a, 16) ^ int(b, 16)).count("1")
    except (TypeError, ValueError):
        return 64


def _hue_gap(a: float | None, b: float | None) -> float:
    distance = abs(float(a or 0.0) - float(b or 0.0)) % 360.0
    return min(distance, 360.0 - distance)


def _cluster(conn: sqlite3.Connection, naming_file: Path) -> dict[str, Any]:
    rows = conn.execute(
        """SELECT ahash, COUNT(*) AS n, AVG(hue_deg), AVG(saturation)
           FROM icon_observations
           WHERE ahash IS NOT NULL AND ahash!=''
           GROUP BY ahash ORDER BY n DESC"""
    ).fetchall()
    if not rows:
        naming_file.parent.mkdir(parents=True, exist_ok=True)
        naming_file.write_text(
            json.dumps({"clusters": [], "icons_total": 0}, indent=2) + "\n",
            encoding="utf-8",
        )
        return {"distinct_hashes": 0, "clusters": 0, "icons_total": 0}

    representatives: list[dict[str, Any]] = []
    assignments: dict[str, int] = {}
    for ahash, count, mean_hue, _mean_sat in sorted(rows, key=lambda row: -int(row[1])):
        assigned = None
        for representative in representatives:
            if (
                _hamming(str(ahash), str(representative["ahash"])) <= HAMMING_THRESHOLD
                and _hue_gap(mean_hue, representative["hue"]) <= HUE_SPLIT_DEG
            ):
                assigned = int(representative["id"])
                representative["members"] += int(count)
                break
        if assigned is None:
            assigned = len(representatives) + 1
            representatives.append(
                {
                    "id": assigned,
                    "ahash": str(ahash),
                    "hue": float(mean_hue or 0.0),
                    "members": int(count),
                }
            )
        assignments[str(ahash)] = assigned

    conn.execute("UPDATE icon_observations SET cluster_id=NULL")
    for ahash, cluster_id in assignments.items():
        conn.execute(
            "UPDATE icon_observations SET cluster_id=? WHERE ahash=?",
            (cluster_id, ahash),
        )
    conn.commit()

    summary = conn.execute(
        """SELECT cluster_id, COUNT(*) n, AVG(hue_deg), AVG(saturation),
                  AVG(value), AVG(area_px), AVG(aspect), AVG(fill_ratio),
                  COUNT(DISTINCT ahash), COUNT(DISTINCT screenshot_id)
           FROM icon_observations WHERE cluster_id IS NOT NULL
           GROUP BY cluster_id ORDER BY n DESC"""
    ).fetchall()
    clusters = [
        {
            "cluster_id": int(row[0]),
            "icon_class": "",
            "count": int(row[1]),
            "hue_deg": round(float(row[2] or 0.0), 1),
            "saturation": round(float(row[3] or 0.0), 3),
            "value": round(float(row[4] or 0.0), 3),
            "area_px": round(float(row[5] or 0.0), 1),
            "aspect": round(float(row[6] or 0.0), 3),
            "fill_ratio": round(float(row[7] or 0.0), 3),
            "distinct_hashes": int(row[8]),
            "distinct_screenshots": int(row[9]),
        }
        for row in summary
    ]
    payload = {
        "_comment": "Generated review file. Name clusters before applying classes.",
        "hamming_threshold": HAMMING_THRESHOLD,
        "hue_split_deg": HUE_SPLIT_DEG,
        "icons_total": sum(item["count"] for item in clusters),
        "clusters": clusters,
    }
    naming_file.parent.mkdir(parents=True, exist_ok=True)
    naming_file.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {
        "distinct_hashes": len(rows),
        "clusters": len(clusters),
        "icons_total": payload["icons_total"],
        "naming_file": str(naming_file),
    }


def run(
    *,
    db_path: Path = DB,
    repo_root: Path = REPO,
    budget_sec: float = 86400.0,
    limit: int = 0,
    naming_file: Path = NAMING_FILE,
) -> dict[str, Any]:
    db_path = db_path.resolve()
    repo_root = repo_root.resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"RLSM DB not found: {db_path}")

    adjacent.DB = db_path
    adjacent.REPO = repo_root
    standalone.DB = db_path
    standalone.REPO = repo_root

    conn = sqlite3.connect(str(db_path), timeout=60.0)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 60000")
    adjacent.ensure_schema(conn)
    standalone.ensure_schema(conn)
    before = _count(conn)
    conn.close()

    adjacent_result = adjacent.run(budget_sec=budget_sec, limit=limit)
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    after_adjacent = _count(conn)
    conn.close()
    adjacent_delta = after_adjacent - before
    adjacent_reported = int(adjacent_result.get("icons", 0))

    standalone_result = standalone.run(budget_sec=budget_sec, limit=limit)
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    after_standalone = _count(conn)
    standalone_delta = after_standalone - after_adjacent
    standalone_reported = int(standalone_result.get("candidates", 0))
    cluster_result = _cluster(conn, naming_file)
    persisted = _count(conn)
    conn.close()

    mismatches = []
    if adjacent_delta != adjacent_reported:
        mismatches.append(
            {
                "channel": "adjacent",
                "reported": adjacent_reported,
                "persisted_delta": adjacent_delta,
            }
        )
    if standalone_delta != standalone_reported:
        mismatches.append(
            {
                "channel": "standalone",
                "reported": standalone_reported,
                "persisted_delta": standalone_delta,
            }
        )
    detector_failures = int(adjacent_result.get("failed", 0)) + int(
        standalone_result.get("failed", 0)
    )
    unprocessed = int(standalone_result.get("unprocessed", 0))
    status = "failed" if mismatches or detector_failures or unprocessed else "completed"
    return {
        "database": str(db_path),
        "repo_root": str(repo_root),
        "before": before,
        "after_adjacent": after_adjacent,
        "after_standalone": after_standalone,
        "persisted_icons": persisted,
        "adjacent": adjacent_result,
        "standalone": standalone_result,
        "clusters": cluster_result,
        "counter_mismatches": mismatches,
        "detector_failures": detector_failures,
        "unprocessed": unprocessed,
        "status": status,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DB)
    parser.add_argument("--repo-root", type=Path, default=REPO)
    parser.add_argument("--budget-sec", type=float, default=86400.0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--naming-file", type=Path, default=NAMING_FILE)
    args = parser.parse_args(argv)
    try:
        result = run(
            db_path=args.db,
            repo_root=args.repo_root,
            budget_sec=max(1.0, args.budget_sec),
            limit=max(0, args.limit),
            naming_file=args.naming_file,
        )
    except (FileNotFoundError, sqlite3.DatabaseError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
