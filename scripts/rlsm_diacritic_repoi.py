#!/usr/bin/env python3
"""
OCR Pass 1: Diacritic-aware POI re-extraction.

Two things to fix:

  (a) The spatial map join failed for BAYAMÓN / AÑASCO / etc. because
      places.geojson stores names WITH diacritics (BAYAMÓN) while
      labeled_pins stores ASCII (BAYAMON). Both should normalize the same way.

  (b) The POI extractor missed entries where Tesseract garbled the
      diacritic (e.g. MAYAGUEZ vs MAYAGIIEZ, ANASCO vs ANASCO with the ñ
      mis-OCR'd as ll/n/u). Re-mine label_layer OCR text with an expanded
      OCR-alias dictionary, write any newly-found rows into labeled_pins
      with extraction_method='diacritic_repoi'.

Then re-run spatial-map join with strip-diacritics canonicalization so
unvisited-municipality count is honest.

Output:
  - new labeled_pins rows with extraction_method='diacritic_repoi'
  - outputs/intel_diacritic_recovery_report.md (what changed)

CLI: python3 scripts/rlsm_diacritic_repoi.py
"""
from __future__ import annotations

import csv
import json
import sqlite3
import time
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
OUTS = REPO / "outputs"


def strip_diacritics(s: str) -> str:
    """BAYAMÓN -> BAYAMON, AÑASCO -> ANASCO, etc."""
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


# OCR-tolerance variants: for each canonical, list known OCR mis-renderings
# encountered in this corpus (and likely ones based on Tesseract failure modes).
OCR_VARIANTS = {
    "MAYAGUEZ":  ["MAYAGUEZ", "MAYAGIIEZ", "MAYAGUI=Z", "MAYAGÜEZ", "MAYAGUWEZ", "MAYAGIIIEZ"],
    "BAYAMON":   ["BAYAMON", "BAYAM0N", "BAYAMOM", "BAYANON", "BAYAMÓN", "BAYANO N"],
    "ANASCO":    ["ANASCO", "AÑASCO", "ANASCQ", "ANASOO", "AN]ASCO", "ANIASCO"],
    "CULEBRA":   ["CULEBRA", "CULERRA", "CULEORA", "CULEBR4"],
    "COMERIO":   ["COMERIO", "COMERÍO", "COMER1O", "COMERIQ", "CONIERIO"],
    "BOQUERON":  ["BOQUERON", "BOQUERÓN", "BOQUER0N"],
    "RINCON":    ["RINCON", "RINCÓN", "R1NCON"],
    "FAJARDO":   ["FAJARDO", "FAJAROO", "FA] ARDO"],
    "GUANICA":   ["GUANICA", "GUÁNICA"],
    "PENUELAS":  ["PENUELAS", "PEÑUELAS", "PENUELAB"],
    "CANOVANAS": ["CANOVANAS", "CANÓVANAS"],
    "JUNCOS":    ["JUNCOS", "]UNCOS"],
    "LARES":     ["LARES", "L4RES"],
    "LOIZA":     ["LOIZA", "LOÍZA"],
    "MARICAO":   ["MARICAO"],
    "MOCA":      ["MOCA", "MQCA"],
    "OROCOVIS":  ["OROCOVIS"],
    "QUEBRADILLAS": ["QUEBRADILLAS"],
    "SABANA GRANDE": ["SABANA GRANDE"],
    "SAN GERMAN":   ["SAN GERMAN", "SAN GERMÁN"],
    "SAN LORENZO":  ["SAN LORENZO"],
    "SANTA ISABEL": ["SANTA ISABEL"],
    "TRUJILLO ALTO": ["TRUJILLO ALTO"],
    "UTUADO":   ["UTUADO"],
    "VEGA BAJA":["VEGA BAJA"],
    "VEGA ALTA":["VEGA ALTA"],
    "VILLALBA": ["VILLALBA"],
    "YABUCOA":  ["YABUCOA"],
    "MONA PASSAGE": ["MONA PASSAGE", "MONA PASS", "MQNA PASSAGE"],
    "CARIBBEAN SEA": ["CARIBBEAN SEA", "CARIBEAN SEA", "C4RIBBEAN SEA"],
    "ATLANTIC OCEAN": ["ATLANTIC OCEAN", "ATL4NTIC OCEAN"],
    # ARECIBO common OCR variants
    "ARECIBO": ["ARECIBO", "ARECIBQ", "AREC1BO"],
    # PONCE common
    "PONCE": ["PONCE", "P0NCE", "PQNCE"],
    # Long airport names — short forms appear in OCR
    "LUIS MUNOZ MARIN INTERNATIONAL AIRPORT":
        ["LUIS MUNOZ MARIN", "LUIS MUÑOZ MARÍN", "MUNOZ MARIN", "LMM AIRPORT"],
    "RAFAEL HERNANDEZ AIRPORT":
        ["RAFAEL HERNANDEZ", "RAFAEL HERNÁNDEZ", "BQN AIRPORT"],
}


def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    # Pull all label_layer OCR text
    rows = cur.execute("""
        SELECT screenshot_id, raw_text FROM ocr_observations
        WHERE zone='label_layer' AND raw_text IS NOT NULL
    """).fetchall()

    # Existing labeled_pins (so we don't double-insert)
    existing = set()
    for sid, lbl in cur.execute("SELECT screenshot_id, normalized_label FROM labeled_pins"):
        existing.add((sid, lbl))

    inserted = 0
    insert_by_label = Counter()
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Ensure pin_id column exists for INSERT
    cols = {r[1] for r in cur.execute("PRAGMA table_info(labeled_pins)")}
    if "extraction_method" not in cols:
        cur.execute("ALTER TABLE labeled_pins ADD COLUMN extraction_method TEXT")
        conn.commit()

    for sid, text in rows:
        text_upper = text.upper()
        for canonical, variants in OCR_VARIANTS.items():
            if (sid, canonical) in existing:
                continue
            # Match any variant in this OCR text
            for v in variants:
                if v.upper() in text_upper:
                    # Insert row
                    cur.execute("""
                        INSERT INTO labeled_pins
                          (screenshot_id, raw_label, normalized_label, pin_type_guess,
                           confidence, observed_at, extraction_method)
                        VALUES (?, ?, ?, 'municipality_or_anchor', 0.6, ?, 'diacritic_repoi')
                    """, (sid, v, canonical, now))
                    inserted += 1
                    insert_by_label[canonical] += 1
                    existing.add((sid, canonical))
                    break

    conn.commit()

    # Re-run spatial-aware coverage with ASCII canonicalization on places.geojson
    gj = json.load((REPO / "data" / "places.geojson").open())
    pr_munis_ascii_to_orig = {}
    for f in gj.get("features", []):
        name = (f.get("properties", {}).get("NAME") or "").upper().strip()
        if name:
            pr_munis_ascii_to_orig[strip_diacritics(name)] = name

    visited_ascii = {
        strip_diacritics(r[0]).upper()
        for r in cur.execute("SELECT DISTINCT normalized_label FROM labeled_pins")
        if r[0]
    }
    visited_munis = {pr_munis_ascii_to_orig[n] for n in visited_ascii
                     if n in pr_munis_ascii_to_orig}
    unvisited_after = sorted(set(pr_munis_ascii_to_orig.values()) - visited_munis)

    OUTS.mkdir(parents=True, exist_ok=True)
    md = [f"# Diacritic-aware POI recovery report\n",
          f"Generated: {now}\n",
          f"\n## New labeled_pins rows inserted: **{inserted}**\n",
          "\n### By canonical label\n",
          "| Label | New rows |", "|---|---|"]
    for lbl, n in insert_by_label.most_common():
        md.append(f"| {lbl} | {n} |")
    md += ["\n## Coverage gap after diacritic-aware join\n",
           f"- PR municipalities total: **{len(pr_munis_ascii_to_orig)}**",
           f"- Municipalities visited (diacritic-tolerant join): **{len(visited_munis)}**",
           f"- Still unvisited: **{len(unvisited_after)}**",
           f"\n### Sample unvisited (first 30):\n",
           ", ".join(unvisited_after[:30])]
    (OUTS / "intel_diacritic_recovery_report.md").write_text("\n".join(md) + "\n")

    conn.close()
    print(json.dumps({
        "new_labeled_pins_rows": inserted,
        "by_canonical": dict(insert_by_label.most_common(20)),
        "municipalities_visited_after_fix": len(visited_munis),
        "municipalities_unvisited_after_fix": len(unvisited_after),
        "outputs": ["outputs/intel_diacritic_recovery_report.md"],
    }, indent=2))


if __name__ == "__main__":
    main()
