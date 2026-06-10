#!/usr/bin/env python3
"""
OCR Pass 5: Levenshtein-distance tail recovery.

For aircraft_observations still NULL after the single-char-substitution pass
(rlsm_recover_tails_textmine.py), use edit-distance matching to recover tails
that have INSERTION or DELETION OCR errors (e.g., 'N1I96DM' → 'N196DM' has a
phantom 'I' inserted; can't be recovered by substitution alone).

Method:
  1. For each unresolved obs's OCR'd N-prefix candidate, compute Levenshtein
     distance to every known FAA registry tail
  2. Apply OCR-aware cost (substitutions between OCR-confusable pairs are
     cheaper than random subs)
  3. Accept the best match if distance ≤ 2 AND it's unique (no ties)

Operates entirely on existing DB OCR text — no Tesseract needed.

CLI:
    python3 scripts/rlsm_recover_tails_levenshtein.py [--dry-run] [--max-distance 2]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
FAA_CSV = REPO / "data" / "faa_registry_consolidated.csv"

# OCR-confusable character pairs — substitution cost reduced
OCR_CONFUSABLES = {
    frozenset("0O"), frozenset("0Q"), frozenset("0D"),
    frozenset("1I"), frozenset("1L"), frozenset("1l"), frozenset("1|"),
    frozenset("2Z"), frozenset("3B"), frozenset("4A"),
    frozenset("5S"), frozenset("6G"), frozenset("6b"), frozenset("7T"),
    frozenset("8B"), frozenset("9g"), frozenset("9q"),
}

REG_PAT = re.compile(r"REG\.?\s*([A-Z0-9][A-Z0-9\-]{1,6})", re.IGNORECASE)


def ocr_aware_lev(a: str, b: str, max_d: int = 3) -> int:
    """Levenshtein distance with reduced cost for OCR-confusable substitutions.
    Returns infinity if exceeds max_d (early termination)."""
    if abs(len(a) - len(b)) > max_d:
        return max_d + 1
    n, m = len(a), len(b)
    if n == 0: return m
    if m == 0: return n
    prev = list(range(m + 1))
    for i in range(1, n + 1):
        curr = [i] + [0] * m
        min_in_row = curr[0]
        for j in range(1, m + 1):
            # Substitution cost: 0.5 if OCR-confusable, 1 otherwise
            sub_cost = 0
            if a[i-1] != b[j-1]:
                if frozenset([a[i-1], b[j-1]]) in OCR_CONFUSABLES:
                    sub_cost = 0.5
                else:
                    sub_cost = 1
            curr[j] = min(
                prev[j] + 1,       # deletion
                curr[j-1] + 1,     # insertion
                prev[j-1] + sub_cost,  # substitution
            )
            if curr[j] < min_in_row:
                min_in_row = curr[j]
        if min_in_row > max_d:
            return max_d + 1
        prev = curr
    return prev[m]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-distance", type=float, default=2.0,
                    help="Maximum OCR-aware edit distance (default 2)")
    args = ap.parse_args()

    # Load FAA tails (full registry from data/faa_registry_consolidated.csv)
    faa_set = set()
    if FAA_CSV.exists():
        for r in csv.DictReader(FAA_CSV.open()):
            t = (r.get("registration") or "").upper().strip()
            if t.startswith("N"): faa_set.add(t)
    print(f"[lev-recover] FAA registry size: {len(faa_set):,}")

    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cols = {r[1] for r in cur.execute("PRAGMA table_info(aircraft_observations)")}
    if "registration_provenance" not in cols:
        cur.execute("ALTER TABLE aircraft_observations ADD COLUMN registration_provenance TEXT")
        conn.commit()

    # Aggregate OCR-candidate strings across unresolved obs
    rows = cur.execute("""
        SELECT a.aircraft_obs_id,
               GROUP_CONCAT(o.raw_text, ' | ') AS text
        FROM aircraft_observations a
        JOIN ocr_observations o ON o.screenshot_id = a.screenshot_id AND o.zone = 'aircraft_card'
        WHERE a.registration IS NULL
        GROUP BY a.aircraft_obs_id
    """).fetchall()
    print(f"[lev-recover] {len(rows):,} unresolved obs to mine")

    # Build candidate → faa-match cache so we don't re-do edit-distance for same input
    cache: dict[str, tuple[str, float] | None] = {}
    n_recovered = n_ambiguous = 0
    by_match = Counter()
    recovered = []

    for obs_id, text in rows:
        if not text: continue
        for m in REG_PAT.findall(text):
            up = m.upper().replace("-", "").replace(" ", "")
            if up in ("NA", "N/A", "NONE"): continue
            if not up.startswith("N"): continue
            if not (3 <= len(up) <= 7): continue
            # Cache lookup
            if up in cache:
                hit = cache[up]
            else:
                best = None; best_d = float("inf"); second_d = float("inf")
                for faa_tail in faa_set:
                    if abs(len(faa_tail) - len(up)) > args.max_distance:
                        continue
                    d = ocr_aware_lev(up, faa_tail, max_d=int(args.max_distance) + 1)
                    if d < best_d:
                        second_d = best_d
                        best = faa_tail
                        best_d = d
                    elif d < second_d:
                        second_d = d
                # Accept only if unique enough AND ALL transformations involve OCR-confusable
                # pairs (i.e., distance must come entirely from cheap-substitution + insertion/
                # deletion of OCR-likely characters). This catches "9→4" as suspicious.
                # Heuristic: require distance fractional part > 0 (≥1 OCR-confusable sub) OR
                # only pure indel-distance, AND require second-best unique-margin ≥ 1.0.
                is_ocr_plausible = (best_d % 1 > 0) or abs(len(up) - len(best)) >= int(best_d)
                if (best_d <= args.max_distance and
                    (second_d - best_d) >= 1.0 and is_ocr_plausible):
                    hit = (best, best_d)
                else:
                    hit = None
                cache[up] = hit
            if hit:
                tail, dist = hit
                recovered.append((obs_id, up, tail, dist))
                by_match[(up, tail)] += 1
                if not args.dry_run:
                    cur.execute("""
                        UPDATE aircraft_observations
                        SET registration = ?, registration_provenance = 'levenshtein_recover'
                        WHERE aircraft_obs_id = ?
                    """, (tail, obs_id))
                n_recovered += 1
                break  # one match per obs

    if not args.dry_run:
        conn.commit()

    OUTS = REPO / "outputs"
    OUTS.mkdir(parents=True, exist_ok=True)
    with (OUTS / "intel_tail_recovery_lev.csv").open("w", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        w.writerow(["obs_id","ocr_string","recovered_tail","edit_distance"])
        for r in recovered:
            w.writerow(r)

    conn.close()
    print(json.dumps({
        "unresolved_obs": len(rows),
        "obs_recovered": n_recovered,
        "by_match_top10": [{"ocr_string": k[0], "recovered": k[1], "n_obs": v}
                            for k, v in by_match.most_common(10)],
        "dry_run": args.dry_run,
        "outputs": ["outputs/intel_tail_recovery_lev.csv"],
    }, indent=2))


if __name__ == "__main__":
    main()
