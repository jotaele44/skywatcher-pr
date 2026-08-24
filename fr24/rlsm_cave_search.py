"""Provenance-aware FR24 OCR corpus search for cave/location appearances.

The search layer is deliberately downstream of OCR. It never re-runs OCR and
never promotes a keyword/fuzzy hit into canonical identity.

Default cave semantics:
* search the latest OCR observation per screenshot+zone (MAX(obs_id));
* search structured labeled_pins separately;
* preserve RAW / NORMALIZED / CANONICAL strings;
* generic cave terms are lexical evidence, not identity;
* baseline names/aliases carry the baseline's identity_status;
* fuzzy matching is discovery-only and disabled unless requested.

CLI:
    python -m fr24.rlsm_cave_search --query cueva
    python -m fr24.rlsm_cave_search --theme caves --output json
    python -m fr24.rlsm_cave_search --theme caves --output csv --out matches.csv
"""
from __future__ import annotations

import argparse
import csv
import difflib
import json
import re
import sqlite3
import sys
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
DEFAULT_BASELINE = REPO / "data" / "reference" / "caves" / "pr_cave_ocr_baseline_v2.json"

DEFAULT_ZONES = ("label_layer", "map_center", "aircraft_card")


def normalize_text(value: str) -> str:
    """ASCII-fold, casefold and collapse punctuation/whitespace for retrieval."""
    folded = unicodedata.normalize("NFKD", value or "")
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    folded = folded.casefold()
    folded = re.sub(r"[^a-z0-9]+", " ", folded)
    return " ".join(folded.split())


@dataclass(frozen=True)
class SearchTerm:
    term: str
    normalized: str
    match_class: str
    cave_id: str | None = None
    canonical_name: str | None = None
    identity_status: str | None = None


@dataclass(frozen=True)
class Match:
    channel: str
    screenshot_id: int
    filename: str
    rel_path: str
    filename_ts: str | None
    source_availability: str | None
    source_record_id: int
    source_zone: str | None
    raw_text: str
    normalized_text: str
    matched_term: str
    match_class: str
    cave_id: str | None
    canonical_name: str | None
    identity_status: str | None
    confidence: float | None
    bbox_x: int | None = None
    bbox_y: int | None = None
    bbox_w: int | None = None
    bbox_h: int | None = None
    centroid_x: int | None = None
    centroid_y: int | None = None
    fuzzy_score: float | None = None


def load_baseline(path: Path = DEFAULT_BASELINE) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload.get("records"), list):
        raise ValueError("cave baseline must contain a records list")
    return payload


def build_terms(
    baseline: dict,
    *,
    include_generic: bool = True,
    include_candidate_terms: bool = False,
) -> list[SearchTerm]:
    """Build deterministic retrieval terms without collapsing aliases to identity."""
    terms: list[SearchTerm] = []
    seen: set[tuple[str, str, str | None]] = set()

    def add(term: str, match_class: str, rec: dict | None = None) -> None:
        n = normalize_text(term)
        if not n:
            return
        cave_id = rec.get("cave_id") if rec else None
        key = (n, match_class, cave_id)
        if key in seen:
            return
        seen.add(key)
        terms.append(
            SearchTerm(
                term=term,
                normalized=n,
                match_class=match_class,
                cave_id=cave_id,
                canonical_name=rec.get("canonical_name") if rec else None,
                identity_status=rec.get("identity_status") if rec else None,
            )
        )

    if include_generic:
        for term in baseline.get("generic_direct_terms", []):
            add(term, "DIRECT_GENERIC_TERM")
    if include_candidate_terms:
        for term in baseline.get("generic_candidate_terms", []):
            add(term, "KARST_CANDIDATE_TERM")

    for rec in baseline["records"]:
        if not rec.get("search_eligible", True):
            continue
        add(rec["canonical_name"], "KNOWN_CAVE_NAME", rec)
        for alias in rec.get("aliases", []):
            if normalize_text(alias) != normalize_text(rec["canonical_name"]):
                add(alias, "KNOWN_CAVE_ALIAS", rec)

    return sorted(terms, key=lambda t: (-len(t.normalized.split()), -len(t.normalized), t.normalized))


def _contains_phrase(haystack_normalized: str, needle_normalized: str) -> bool:
    return bool(
        re.search(
            rf"(?<![a-z0-9]){re.escape(needle_normalized)}(?![a-z0-9])",
            haystack_normalized,
        )
    )


def _exact_matches(text: str, terms: Sequence[SearchTerm]) -> list[SearchTerm]:
    ntext = normalize_text(text)
    return [term for term in terms if _contains_phrase(ntext, term.normalized)]


def _fuzzy_terms(
    text: str, terms: Sequence[SearchTerm], threshold: float
) -> list[tuple[SearchTerm, float]]:
    """Discovery-only token-window fuzzy candidates."""
    tokens = normalize_text(text).split()
    out: list[tuple[SearchTerm, float]] = []
    for term in terms:
        n = len(term.normalized.split())
        if n == 0 or not tokens:
            continue
        best = 0.0
        lo = max(1, n - 1)
        hi = min(len(tokens), n + 1)
        for width in range(lo, hi + 1):
            for i in range(0, len(tokens) - width + 1):
                window = " ".join(tokens[i : i + width])
                best = max(
                    best,
                    difflib.SequenceMatcher(None, window, term.normalized).ratio(),
                )
        if best >= threshold:
            out.append((term, round(best, 4)))
    out.sort(key=lambda item: (-item[1], -len(item[0].normalized), item[0].normalized))
    return out


def latest_ocr_rows(conn: sqlite3.Connection, zones: Sequence[str]) -> list[tuple]:
    placeholders = ",".join("?" for _ in zones)
    return conn.execute(
        f"""SELECT o.obs_id, o.screenshot_id, o.zone, o.raw_text, o.confidence_mean,
                    s.filename, s.rel_path, s.filename_ts, s.source_availability
             FROM ocr_observations o
             JOIN screenshots s ON s.screenshot_id = o.screenshot_id
            WHERE o.obs_id IN (
                SELECT MAX(obs_id)
                  FROM ocr_observations
                 WHERE zone IN ({placeholders})
                 GROUP BY screenshot_id, zone
            )
            ORDER BY o.screenshot_id, o.zone, o.obs_id""",
        tuple(zones),
    ).fetchall()


def labeled_pin_rows(conn: sqlite3.Connection) -> list[tuple]:
    return conn.execute(
        """SELECT p.pin_id, p.screenshot_id, p.raw_label, p.normalized_label,
                  p.confidence, p.bbox_x, p.bbox_y, p.bbox_w, p.bbox_h,
                  p.centroid_x, p.centroid_y,
                  s.filename, s.rel_path, s.filename_ts, s.source_availability
             FROM labeled_pins p
             JOIN screenshots s ON s.screenshot_id = p.screenshot_id
            ORDER BY p.screenshot_id, p.pin_id"""
    ).fetchall()


def _append_matches(
    output: list[Match],
    *,
    channel: str,
    screenshot_id: int,
    filename: str,
    rel_path: str,
    filename_ts: str | None,
    source_availability: str | None,
    source_record_id: int,
    source_zone: str | None,
    raw_text: str,
    confidence: float | None,
    terms: Sequence[SearchTerm],
    fuzzy: bool,
    fuzzy_threshold: float,
    bbox: tuple[int | None, ...] = (None, None, None, None, None, None),
) -> None:
    ntext = normalize_text(raw_text)
    exact = _exact_matches(raw_text, terms)
    exact_keys = {(t.normalized, t.cave_id, t.match_class) for t in exact}
    bx, by, bw, bh, cx, cy = bbox

    for term in exact:
        output.append(
            Match(
                channel=channel,
                screenshot_id=screenshot_id,
                filename=filename,
                rel_path=rel_path,
                filename_ts=filename_ts,
                source_availability=source_availability,
                source_record_id=source_record_id,
                source_zone=source_zone,
                raw_text=raw_text,
                normalized_text=ntext,
                matched_term=term.term,
                match_class=term.match_class,
                cave_id=term.cave_id,
                canonical_name=term.canonical_name,
                identity_status=term.identity_status,
                confidence=confidence,
                bbox_x=bx,
                bbox_y=by,
                bbox_w=bw,
                bbox_h=bh,
                centroid_x=cx,
                centroid_y=cy,
            )
        )

    if not fuzzy:
        return
    for term, score in _fuzzy_terms(raw_text, terms, fuzzy_threshold):
        if (term.normalized, term.cave_id, term.match_class) in exact_keys:
            continue
        output.append(
            Match(
                channel=channel,
                screenshot_id=screenshot_id,
                filename=filename,
                rel_path=rel_path,
                filename_ts=filename_ts,
                source_availability=source_availability,
                source_record_id=source_record_id,
                source_zone=source_zone,
                raw_text=raw_text,
                normalized_text=ntext,
                matched_term=term.term,
                match_class="FUZZY_CANDIDATE",
                cave_id=term.cave_id,
                canonical_name=term.canonical_name,
                identity_status="CANDIDATE_NOT_IDENTITY",
                confidence=confidence,
                bbox_x=bx,
                bbox_y=by,
                bbox_w=bw,
                bbox_h=bh,
                centroid_x=cx,
                centroid_y=cy,
                fuzzy_score=score,
            )
        )


def search_corpus(
    conn: sqlite3.Connection,
    *,
    terms: Sequence[SearchTerm],
    zones: Sequence[str] = DEFAULT_ZONES,
    channels: Sequence[str] = ("ocr", "labels"),
    fuzzy: bool = False,
    fuzzy_threshold: float = 0.86,
) -> tuple[list[Match], dict]:
    matches: list[Match] = []
    if "ocr" in channels:
        for row in latest_ocr_rows(conn, zones):
            obs_id, sid, zone, raw, conf, filename, rel_path, ts, availability = row
            _append_matches(
                matches,
                channel="RAW_OCR",
                screenshot_id=sid,
                filename=filename,
                rel_path=rel_path,
                filename_ts=ts,
                source_availability=availability,
                source_record_id=obs_id,
                source_zone=zone,
                raw_text=raw or "",
                confidence=conf,
                terms=terms,
                fuzzy=fuzzy,
                fuzzy_threshold=fuzzy_threshold,
            )
    if "labels" in channels:
        for row in labeled_pin_rows(conn):
            (
                pin_id,
                sid,
                raw,
                normalized,
                conf,
                bx,
                by,
                bw,
                bh,
                cx,
                cy,
                filename,
                rel_path,
                ts,
                availability,
            ) = row
            _append_matches(
                matches,
                channel="EXTRACTED_LABEL",
                screenshot_id=sid,
                filename=filename,
                rel_path=rel_path,
                filename_ts=ts,
                source_availability=availability,
                source_record_id=pin_id,
                source_zone=None,
                raw_text=raw or normalized or "",
                confidence=conf,
                terms=terms,
                fuzzy=fuzzy,
                fuzzy_threshold=fuzzy_threshold,
                bbox=(bx, by, bw, bh, cx, cy),
            )

    matches.sort(
        key=lambda m: (
            m.filename_ts is None,
            m.filename_ts or "",
            m.screenshot_id,
            m.channel,
            m.source_record_id,
            m.match_class,
            m.matched_term.casefold(),
        )
    )

    total = conn.execute("SELECT COUNT(*) FROM screenshots").fetchone()[0]
    ocr_any = conn.execute(
        """SELECT COUNT(DISTINCT screenshot_id) FROM ocr_observations
           WHERE ocr_status IN ('ok','empty')"""
    ).fetchone()[0]
    ocr_failed = conn.execute(
        """SELECT COUNT(DISTINCT screenshot_id) FROM ocr_observations
           WHERE ocr_status='failed'"""
    ).fetchone()[0]
    coverage = {
        "screenshots_total": int(total),
        "screenshots_with_any_ocr": int(ocr_any),
        "screenshots_with_failed_ocr_observation": int(ocr_failed),
        "matched_screenshots": len({m.screenshot_id for m in matches}),
        "match_rows": len(matches),
        "certification": (
            "BOUNDED_RETRIEVAL_EXHAUSTION_OVER_EFFECTIVE_OCR_AND_LABELED_PINS;"
            "NOT_VISUAL_TEXT_EXHAUSTION"
        ),
    }
    return matches, coverage


def query_terms(query: str) -> list[SearchTerm]:
    return [SearchTerm(query, normalize_text(query), "USER_QUERY")]


def _write_csv(matches: Iterable[Match], stream) -> None:
    rows = [asdict(m) for m in matches]
    fields = list(Match.__dataclass_fields__)
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Search effective FR24 OCR/labeled-pin corpus.")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--query", help="literal phrase to search")
    g.add_argument("--theme", choices=["caves"], help="use the versioned cave baseline")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    p.add_argument("--channels", default="ocr,labels", help="ocr,labels")
    p.add_argument("--zones", default=",".join(DEFAULT_ZONES))
    p.add_argument("--include-karst-candidates", action="store_true")
    p.add_argument("--fuzzy", action="store_true", help="emit discovery-only fuzzy candidates")
    p.add_argument("--fuzzy-threshold", type=float, default=0.86)
    p.add_argument("--output", choices=["table", "json", "csv"], default="table")
    p.add_argument("--out", type=Path)
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    channels = tuple(v.strip() for v in args.channels.split(",") if v.strip())
    zones = tuple(v.strip() for v in args.zones.split(",") if v.strip())
    if not set(channels) <= {"ocr", "labels"} or not channels:
        raise SystemExit("--channels must contain only ocr and/or labels")
    if not zones:
        raise SystemExit("--zones cannot be empty")
    if not 0.0 < args.fuzzy_threshold <= 1.0:
        raise SystemExit("--fuzzy-threshold must be in (0,1]")

    if args.query:
        terms = query_terms(args.query)
    else:
        baseline = load_baseline(args.baseline)
        terms = build_terms(
            baseline,
            include_generic=True,
            include_candidate_terms=args.include_karst_candidates,
        )

    with sqlite3.connect(str(args.db)) as conn:
        matches, coverage = search_corpus(
            conn,
            terms=terms,
            zones=zones,
            channels=channels,
            fuzzy=args.fuzzy,
            fuzzy_threshold=args.fuzzy_threshold,
        )

    payload = {"coverage": coverage, "matches": [asdict(m) for m in matches]}
    if args.output == "json":
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        if args.out:
            args.out.write_text(text, encoding="utf-8")
        else:
            print(text)
    elif args.output == "csv":
        stream = args.out.open("w", encoding="utf-8", newline="") if args.out else sys.stdout
        try:
            _write_csv(matches, stream)
        finally:
            if args.out:
                stream.close()
    else:
        print(json.dumps(coverage, ensure_ascii=False, sort_keys=True))
        for match in matches:
            print(
                f"{match.filename_ts or '-'}\t{match.screenshot_id}\t{match.channel}\t"
                f"{match.match_class}\t{match.matched_term}\t{match.raw_text[:100]}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
