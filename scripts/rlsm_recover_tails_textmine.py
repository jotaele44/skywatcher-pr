#!/usr/bin/env python3
"""
OCR Pass 3a: Text-mining tail recovery (in-session, no Tesseract needed).

For aircraft_observations with NULL registration, mine the existing
aircraft_card OCR text for "REG. NXXXX" patterns and their OCR-corrupt
variants (e.g., N6O3GR → N603GR via O→0 substitution).

Strategy:
  1. Look for "REG.\\s+([A-Z0-9]{2,6})" in the aircraft_card OCR
  2. Skip "N/A", military serials (8-5307 style), and obvious non-tails
  3. Generate OCR-variant candidates via character-substitution
  4. Score each candidate against FAA registry — if a variant matches a real
     N-prefix FAA registration, that's the recovered tail
  5. Update aircraft_observations.registration with high-confidence matches

This handles the LOW-HANGING FRUIT. The Mac-side rlsm_ocr_retry_tails.py is
for observations where Tesseract missed the REG. line entirely.

CLI:
    python3 scripts/rlsm_recover_tails_textmine.py [--dry-run]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import time
from collections import Counter, defaultdict
from itertools import product
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
FAA_CSV = REPO / "data" / "faa_registry_consolidated.csv"

# OCR character-substitution map: actual_char -> likely_OCR_misreads
OCR_SUBS = {
    "0": ["O", "Q", "D"],
    "1": ["I", "L", "l", "T", "J", "|"],
    "2": ["Z"],
    "3": ["B"],
    "4": ["A"],
    "5": ["S"],
    "6": ["G", "b"],
    "7": ["T"],
    "8": ["B"],
    "9": ["g", "q"],
    "B": ["8", "3"],
    "D": ["0", "O"],
    "G": ["6"],
    "I": ["1", "l"],
    "L": ["1"],
    "O": ["0", "Q"],
    "Q": ["0", "O"],
    "S": ["5"],
    "T": ["1", "7"],
    "Z": ["2"],
}

REG_PAT = re.compile(r"REG\.?\s*([A-Z0-9][A-Z0-9\-]{1,6})", re.IGNORECASE)
# Reasonable N-prefix tail: N + 1-5 digits/letters
TAIL_PAT = re.compile(r"^N\d{1,5}[A-Z]{0,2}$")


def gen_ocr_variants(s: str, max_subs: int = 3):
    """Generate plausible OCR-misread variants by substituting characters.
    Limits combinatorial explosion to max_subs simultaneous swaps."""
    s = s.upper()
    positions = [(i, OCR_SUBS.get(c, [])) for i, c in enumerate(s)]
    # Keep only positions with possible swaps, cap at max_subs to keep tractable
    swap_positions = [(i, opts) for i, opts in positions if opts]
    swap_positions = swap_positions[:max_subs + 1]
    if not swap_positions:
        return [s]
    # All combinations of choosing variant or original for each swap position
    results = set([s])
    for r in range(1, len(swap_positions) + 1):
        from itertools import combinations
        for combo in combinations(swap_positions, r):
            chars_options = []
            for i, opts in combo:
                chars_options.append([s[i]] + list(opts))
            for product_tuple in product(*chars_options):
                variant = list(s)
                for (i, _), new_char in zip(combo, product_tuple):
                    variant[i] = new_char
                results.add("".join(variant))
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-variants", type=int, default=200,
                    help="Skip OCR-variant generation if too many combinations")
    args = ap.parse_args()

    # Build FAA registry set for matching
    faa_set = set()
    if FAA_CSV.exists():
        for r in csv.DictReader(FAA_CSV.open()):
            t = (r.get("registration") or "").upper().strip()
            if t: faa_set.add(t)
    print(f"[tail-recover] FAA registry size: {len(faa_set):,}")

    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    # Ensure provenance column exists BEFORE first update
    cols = {r[1] for r in cur.execute("PRAGMA table_info(aircraft_observations)")}
    if "registration_provenance" not in cols:
        cur.execute("ALTER TABLE aircraft_observations ADD COLUMN registration_provenance TEXT")
        conn.commit()

    # Pull all unresolved aircraft_observations and their aircraft_card OCR
    rows = cur.execute("""
        SELECT a.aircraft_obs_id, a.screenshot_id,
               GROUP_CONCAT(o.raw_text, ' | ') AS text
        FROM aircraft_observations a
        JOIN ocr_observations o ON o.screenshot_id = a.screenshot_id AND o.zone = 'aircraft_card'
        WHERE a.registration IS NULL
        GROUP BY a.aircraft_obs_id
    """).fetchall()
    print(f"[tail-recover] {len(rows):,} unresolved aircraft_observations to mine")

    n_with_reg_text = n_recovered = n_ambiguous = n_na = 0
    recovered = []
    ambiguous = []
    by_variant_kind = Counter()

    for obs_id, sid, text in rows:
        if not text: continue
        # Find all REG. matches
        matches = REG_PAT.findall(text)
        if not matches: continue
        n_with_reg_text += 1
        # Pick the most plausible registration token (longest with digits + N prefix)
        candidates_in_text = []
        for m in matches:
            up = m.upper().replace("-", "").replace(" ", "")
            if up in ("NA", "N/A", "NONE"):
                continue
            if not up.startswith("N"):
                continue  # Not N-prefix (military, etc.)
            if len(up) < 3 or len(up) > 7:
                continue
            candidates_in_text.append(up)
        if not candidates_in_text:
            n_na += 1
            continue
        # For each candidate, generate OCR variants and check FAA
        best_match = None
        ambiguous_matches = set()
        for cand in candidates_in_text:
            # Direct hit?
            if cand in faa_set:
                best_match = cand
                by_variant_kind["direct"] += 1
                break
            # Variant lookup
            variants = gen_ocr_variants(cand, max_subs=3)
            if len(variants) > args.max_variants:
                continue
            faa_hits = {v for v in variants if v in faa_set and TAIL_PAT.match(v)}
            if len(faa_hits) == 1:
                best_match = next(iter(faa_hits))
                by_variant_kind["variant_1sub"] += 1
                break
            elif len(faa_hits) > 1:
                ambiguous_matches |= faa_hits
        if best_match:
            recovered.append((obs_id, sid, candidates_in_text[0], best_match))
            n_recovered += 1
            if not args.dry_run:
                cur.execute("""
                    UPDATE aircraft_observations
                    SET registration = ?, registration_provenance = 'textmine_ocr_variant'
                    WHERE aircraft_obs_id = ?
                """, (best_match, obs_id))
        elif ambiguous_matches:
            ambiguous.append((obs_id, sid, candidates_in_text[0], ",".join(sorted(ambiguous_matches))[:80]))
            n_ambiguous += 1

    # Make sure column exists for provenance tracking
    cols = {r[1] for r in cur.execute("PRAGMA table_info(aircraft_observations)")}
    if "registration_provenance" not in cols and not args.dry_run:
        cur.execute("ALTER TABLE aircraft_observations ADD COLUMN registration_provenance TEXT")
        # Re-run the inserts now that column exists
        for obs_id, _sid, _raw, best in recovered:
            cur.execute("""
                UPDATE aircraft_observations
                SET registration = ?, registration_provenance = 'textmine_ocr_variant'
                WHERE aircraft_obs_id = ?
            """, (best, obs_id))

    if not args.dry_run:
        conn.commit()

    # Audit report
    OUTS = REPO / "outputs"
    OUTS.mkdir(parents=True, exist_ok=True)
    with (OUTS / "intel_tail_recovery_textmine.csv").open("w", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        w.writerow(["obs_id","screenshot_id","ocr_text","recovered_tail"])
        for r in recovered:
            w.writerow(r)
    with (OUTS / "intel_tail_recovery_ambiguous.csv").open("w", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        w.writerow(["obs_id","screenshot_id","ocr_text","faa_hits"])
        for r in ambiguous:
            w.writerow(r)

    conn.close()
    print(json.dumps({
        "unresolved_obs_total": len(rows),
        "obs_with_REG_text": n_with_reg_text,
        "obs_with_N_prefix_candidate": len(rows) - n_na,
        "recovered_tails": n_recovered,
        "ambiguous_matches": n_ambiguous,
        "by_match_kind": dict(by_variant_kind.most_common()),
        "dry_run": args.dry_run,
        "outputs": [
            "outputs/intel_tail_recovery_textmine.csv",
            "outputs/intel_tail_recovery_ambiguous.csv",
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
