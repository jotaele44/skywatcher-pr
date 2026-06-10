#!/usr/bin/env python3
"""
RLSM tail recovery by raw_text scan.

Canonicalizes the producer of the `identity_status='recovered'` rows in
`aircraft_observations`. This script is the tracked, reproducible
implementation of what was previously a one-off REPL/notebook pass —
documented in [docs/SPIDERWEB_LANGUAGE_BRIDGE.md] and
[docs/SCHEMA_AND_EXPORT_CONTRACTS.md].

What it does
------------
For each FAA N-number in the input registry, scan every
`ocr_observations.raw_text` row for case-insensitive whole-word matches.
For each (screenshot, registration) pair that DOES NOT already have an
`aircraft_observations` row, INSERT one with:

  identity_status = 'recovered'
  source_zone     = 'recovered:<original_zone>'
  registration    = <matched N-number>
  confidence      = 0.6   (MEDIUM per docs/SCHEMA_AND_EXPORT_CONTRACTS.md)
  raw_excerpt     = matched-row raw_text, truncated to 120 chars
  observed_at     = now

Records a `processing_runs` row with `run_kind='recover_tails'` and
notes `{"<tail>": {"raw_text_hits": N, "new_aircraft_observations_inserted": M}, ...}`.

Idempotent
----------
Re-running is a no-op for any (screenshot_id, registration) pair that
already exists in `aircraft_observations` (regardless of its
`identity_status`). New tails / new screenshots produce new rows.

CLI
---
    python3 scripts/rlsm_recover_tails_by_rawtext.py [--regs PATH] [--limit N] [--dry-run]

Defaults to `input/regs.txt` if present, else `tests/fixtures/regs.txt`
(the hermetic sample) so it runs in CI without operator input.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
OUTS = REPO / "outputs"

DEFAULT_REGS_CANDIDATES = (REPO / "input" / "regs.txt",
                           REPO / "tests" / "fixtures" / "regs.txt")

# FAA N-number: 'N' + 1–5 digits, then 0–2 letters. Whole-word match — must
# be bounded by non-alphanumerics so we don't grab "N12345ABC" as N12345AB.
TAIL_RE_TEMPLATE = r"(?<![A-Za-z0-9])({tail})(?![A-Za-z0-9])"

# Per-recovery confidence — MEDIUM tier per the canonical confidence scale.
RECOVERED_CONFIDENCE = 0.6


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _resolve_regs_path(explicit: str | None) -> Path:
    """Pick an N-number file: explicit > input/regs.txt > tests/fixtures/regs.txt."""
    if explicit:
        return Path(explicit)
    for cand in DEFAULT_REGS_CANDIDATES:
        if cand.exists():
            return cand
    raise SystemExit(
        f"No regs file found. Pass --regs or create one of: "
        f"{', '.join(str(p) for p in DEFAULT_REGS_CANDIDATES)}"
    )


def _load_regs(path: Path) -> list[str]:
    """One N-number per line. Strip whitespace, skip blanks/comments, upper-case."""
    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        # Strip a leading 'N' if missing — accept both "N12345" and "12345"
        if not s.upper().startswith("N"):
            s = "N" + s
        out.append(s.upper())
    return out


def _existing_pairs(conn: sqlite3.Connection) -> set[tuple[int, str]]:
    """Return the (screenshot_id, registration) pairs already in aircraft_observations.

    Idempotency relies on this: any pair already present is skipped, regardless
    of identity_status (so this script never duplicates a 'confirmed' obs).
    """
    cur = conn.execute("""
        SELECT screenshot_id, UPPER(registration)
        FROM aircraft_observations
        WHERE registration IS NOT NULL AND TRIM(registration) != ''
    """)
    return {(sid, reg) for sid, reg in cur if sid is not None and reg}


def _scan_for_tail(conn: sqlite3.Connection, tail: str) -> list[tuple[int, str, str]]:
    """Return [(screenshot_id, zone, raw_text)] hits for *tail* in ocr_observations.

    Uses `LIKE %tail%` (case-insensitive via UPPER) for the DB-side filter,
    then a Python regex with word boundaries to reject false-positive
    substrings like 'N999ZY' matching 'N999ZY99' (which doesn't exist but
    illustrates the principle).
    """
    pat = re.compile(TAIL_RE_TEMPLATE.format(tail=re.escape(tail)),
                     flags=re.IGNORECASE)
    cur = conn.execute("""
        SELECT screenshot_id, zone, raw_text
        FROM ocr_observations
        WHERE raw_text LIKE ?
    """, (f"%{tail}%",))
    hits: list[tuple[int, str, str]] = []
    for sid, zone, raw_text in cur:
        if raw_text and pat.search(raw_text):
            hits.append((sid, zone, raw_text))
    return hits


def run(regs_path: Path, limit: int = 0, dry_run: bool = False) -> dict:
    if not DB.exists():
        raise SystemExit(f"RLSM DB not found: {DB} — run the inventory + OCR phases first.")

    conn = sqlite3.connect(str(DB), timeout=30.0)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    # Ensure aircraft-dedup unique index (idempotent migration for older DBs).
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_air_dedup "
        "ON aircraft_observations(screenshot_id, registration, source_zone) "
        "WHERE registration IS NOT NULL AND TRIM(registration) != ''"
    )

    regs = _load_regs(regs_path)
    if limit:
        regs = regs[:limit]

    if not dry_run:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO processing_runs (run_kind, started_at, status, n_inputs, n_processed, n_failed) "
            "VALUES ('recover_tails', ?, 'in_progress', ?, 0, 0)",
            (_iso_now(), len(regs)),
        )
        run_id = cur.lastrowid
        conn.commit()
    else:
        run_id = None

    existing = _existing_pairs(conn)
    stats: dict[str, dict] = {}
    csv_rows: list[tuple] = []
    total_inserted = 0
    t0 = time.time()

    for tail in regs:
        hits = _scan_for_tail(conn, tail)
        new_pairs = [(sid, zone, txt) for (sid, zone, txt) in hits
                     if (sid, tail) not in existing]
        # Dedup hits within this run too — multiple OCR rows for one
        # screenshot (one per zone) should produce ONE aircraft_observation.
        seen_in_run: set[int] = set()
        inserted_for_tail = 0
        for sid, zone, raw_text in new_pairs:
            if sid in seen_in_run:
                continue
            seen_in_run.add(sid)
            if not dry_run:
                conn.execute("""
                    INSERT INTO aircraft_observations
                        (screenshot_id, run_id, registration, identity_status,
                         source_zone, raw_excerpt, confidence, observed_at)
                    VALUES (?, ?, ?, 'recovered', ?, ?, ?, ?)
                """, (sid, run_id, tail, f"recovered:{zone}",
                      (raw_text or "")[:120], RECOVERED_CONFIDENCE, _iso_now()))
            existing.add((sid, tail))  # mark inserted so future tails skip
            inserted_for_tail += 1
            csv_rows.append((tail, sid, zone, (raw_text or "")[:120]))
        stats[tail] = {
            "raw_text_hits": len(hits),
            "new_aircraft_observations_inserted": inserted_for_tail,
        }
        total_inserted += inserted_for_tail

    if not dry_run:
        conn.execute(
            "UPDATE processing_runs SET ended_at=?, status='completed', "
            "n_processed=?, notes=? WHERE run_id=?",
            (_iso_now(), total_inserted, json.dumps(stats), run_id),
        )
        conn.commit()

    # Audit CSV — always written (even on --dry-run) so the operator can
    # preview before committing to a real run.
    OUTS.mkdir(parents=True, exist_ok=True)
    audit_path = OUTS / "intel_recover_tails_rawtext.csv"
    with audit_path.open("w", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        w.writerow(["tail", "screenshot_id", "source_zone", "raw_excerpt"])
        for row in csv_rows:
            w.writerow(row)

    conn.close()
    return {
        "run_id": run_id,
        "dry_run": dry_run,
        "regs_path": str(regs_path),
        "tails_scanned": len(regs),
        "total_inserted": total_inserted,
        "elapsed_sec": round(time.time() - t0, 2),
        "stats": stats,
        "audit_csv": str(audit_path),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--regs", default=None,
                    help="Path to N-number list (one per line). Default: input/regs.txt "
                         "or tests/fixtures/regs.txt.")
    ap.add_argument("--limit", type=int, default=0,
                    help="Only scan the first N tails (for sampling).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Do not write to the DB; produce the audit CSV only.")
    args = ap.parse_args()
    regs_path = _resolve_regs_path(args.regs)
    out = run(regs_path, limit=args.limit, dry_run=args.dry_run)
    print(json.dumps(out, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
