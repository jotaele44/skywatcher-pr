"""Deterministically export the extended screenshot-intelligence tables."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
OUT = REPO / "outputs" / "screenshot_intelligence"

TABLES = (
    "frame_observations",
    "map_state_observations",
    "gui_artifact_observations",
    "icon_observations",
    "icon_artifacts",
    "icon_scan_receipts",
    "flight_track_features",
    "track_extraction_receipts",
    "extraction_field_provenance",
)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")]


def _json_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"encoding": "hex", "value": value.hex()}
    return value


def _write_table(
    conn: sqlite3.Connection,
    table: str,
    output_dir: Path,
) -> dict[str, Any]:
    if not _table_exists(conn, table):
        return {
            "table": table,
            "status": "unavailable",
            "rows": 0,
            "path": None,
            "sha256": None,
        }
    columns = _columns(conn, table)
    primary = next(
        (str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})") if int(row[5]) > 0),
        columns[0],
    )
    path = output_dir / f"{table}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    row_count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in conn.execute(
            f"SELECT {', '.join(columns)} FROM {table} ORDER BY {primary}"
        ):
            record = {
                column: _json_value(value)
                for column, value in zip(columns, row, strict=True)
            }
            handle.write(
                json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
                + "\n"
            )
            row_count += 1
    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "table": table,
        "status": "ok",
        "rows": row_count,
        "path": path.relative_to(REPO).as_posix(),
        "sha256": sha256,
        "columns": columns,
        "order_by": primary,
    }


def export_all(
    db_path: Path = DB,
    output_dir: Path = OUT,
) -> dict[str, Any]:
    if not db_path.exists():
        raise FileNotFoundError(f"RLSM DB not found: {db_path}")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    exports = [_write_table(conn, table, output_dir) for table in TABLES]
    conn.close()
    manifest = {
        "schema_version": "skywatcher_screenshot_intelligence_export.v1",
        "database": db_path.as_posix(),
        "output_dir": output_dir.as_posix(),
        "exports": exports,
        "available_tables": sum(1 for item in exports if item["status"] == "ok"),
        "total_rows": sum(int(item["rows"]) for item in exports),
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    manifest["manifest"] = manifest_path.relative_to(REPO).as_posix()
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DB)
    parser.add_argument("--output-dir", type=Path, default=OUT)
    args = parser.parse_args(argv)
    try:
        result = export_all(args.db, args.output_dir)
    except (FileNotFoundError, sqlite3.DatabaseError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
