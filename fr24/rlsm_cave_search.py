"""Read-only, provenance-aware search over the RLSM OCR corpus.

Searches the effective (newest) OCR row per screenshot+zone and labeled_pins as
separate evidence channels. Keyword/fuzzy matches never establish identity.
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
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO / "data" / "rlsm" / "rlsm_screenshot_analysis.sqlite"
DEFAULT_BASELINE = REPO / "data" / "reference" / "caves" / "pr_cave_ocr_baseline_v2.json"
DEFAULT_ZONES = ("label_layer", "map_center", "aircraft_card")


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(c for c in value if not unicodedata.combining(c)).casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value).split())


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
    baseline: dict, *, include_generic: bool = True, include_candidate_terms: bool = False
) -> list[SearchTerm]:
    terms: list[SearchTerm] = []
    seen: set[tuple[str, str, str | None]] = set()

    def add(value: str, match_class: str, rec: dict | None = None) -> None:
        n = normalize_text(value)
        cave_id = rec.get("cave_id") if rec else None
        key = (n, match_class, cave_id)
        if not n or key in seen:
            return
        seen.add(key)
        terms.append(
            SearchTerm(
                value,
                n,
                match_class,
                cave_id,
                rec.get("canonical_name") if rec else None,
                rec.get("identity_status") if rec else None,
            )
        )

    if include_generic:
        for value in baseline.get("generic_direct_terms", []):
            add(value, "DIRECT_GENERIC_TERM")
    if include_candidate_terms:
        for value in baseline.get("generic_candidate_terms", []):
            add(value, "KARST_CANDIDATE_TERM")
    for rec in baseline["records"]:
        if not rec.get("search_eligible", True):
            continue
        add(rec["canonical_name"], "KNOWN_CAVE_NAME", rec)
        canonical = normalize_text(rec["canonical_name"])
        for alias in rec.get("aliases", []):
            if normalize_text(alias) != canonical:
                add(alias, "KNOWN_CAVE_ALIAS", rec)
    return sorted(terms, key=lambda t: (-len(t.normalized.split()), -len(t.normalized), t.normalized))


def _contains(haystack: str, needle: str) -> bool:
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack))


def _fuzzy(text: str, term: SearchTerm, threshold: float) -> float | None:
    tokens = normalize_text(text).split()
    n = len(term.normalized.split())
    if not tokens or not n:
        return None
    best = 0.0
    for width in range(max(1, n - 1), min(len(tokens), n + 1) + 1):
        for i in range(len(tokens) - width + 1):
            window = " ".join(tokens[i : i + width])
            best = max(best, difflib.SequenceMatcher(None, window, term.normalized).ratio())
    return round(best, 4) if best >= threshold else None


def _latest_ocr(conn: sqlite3.Connection, zones: Sequence[str]) -> list[tuple]:
    marks = ",".join("?" for _ in zones)
    return conn.execute(
        f"""SELECT o.obs_id,o.screenshot_id,o.zone,o.raw_text,o.confidence_mean,
                   s.filename,s.rel_path,s.filename_ts,s.source_availability,o.ocr_status
              FROM ocr_observations o JOIN screenshots s USING(screenshot_id)
             WHERE o.obs_id IN (
                 SELECT MAX(obs_id) FROM ocr_observations
                  WHERE zone IN ({marks}) GROUP BY screenshot_id,zone
             )
             ORDER BY o.screenshot_id,o.zone,o.obs_id""",
        tuple(zones),
    ).fetchall()


def _labeled_pins(conn: sqlite3.Connection) -> list[tuple]:
    return conn.execute(
        """SELECT p.pin_id,p.screenshot_id,p.raw_label,p.normalized_label,p.confidence,
                  p.bbox_x,p.bbox_y,p.bbox_w,p.bbox_h,p.centroid_x,p.centroid_y,
                  s.filename,s.rel_path,s.filename_ts,s.source_availability
             FROM labeled_pins p JOIN screenshots s USING(screenshot_id)
            ORDER BY p.screenshot_id,p.pin_id"""
    ).fetchall()


def _emit(
    out: list[Match],
    *,
    channel: str,
    sid: int,
    filename: str,
    rel_path: str,
    ts: str | None,
    availability: str | None,
    source_id: int,
    zone: str | None,
    raw: str,
    confidence: float | None,
    terms: Sequence[SearchTerm],
    fuzzy: bool,
    fuzzy_threshold: float,
    bbox: tuple[int | None, ...] = (None, None, None, None, None, None),
) -> None:
    ntext = normalize_text(raw)
    exact: set[tuple[str, str | None, str]] = set()
    bx, by, bw, bh, cx, cy = bbox
    for term in terms:
        if not _contains(ntext, term.normalized):
            continue
        exact.add((term.normalized, term.cave_id, term.match_class))
        out.append(
            Match(
                channel, sid, filename, rel_path, ts, availability, source_id, zone,
                raw, ntext, term.term, term.match_class, term.cave_id,
                term.canonical_name, term.identity_status, confidence,
                bx, by, bw, bh, cx, cy,
            )
        )
    if not fuzzy:
        return
    for term in terms:
        if (term.normalized, term.cave_id, term.match_class) in exact:
            continue
        score = _fuzzy(raw, term, fuzzy_threshold)
        if score is None:
            continue
        out.append(
            Match(
                channel, sid, filename, rel_path, ts, availability, source_id, zone,
                raw, ntext, term.term, "FUZZY_CANDIDATE", term.cave_id,
                term.canonical_name, "CANDIDATE_NOT_IDENTITY", confidence,
                bx, by, bw, bh, cx, cy, score,
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
    effective = _latest_ocr(conn, zones)

    if "ocr" in channels:
        for obs_id, sid, zone, raw, conf, filename, rel_path, ts, availability, status in effective:
            if status not in ("ok", "empty"):
                continue
            _emit(
                matches, channel="RAW_OCR", sid=sid, filename=filename, rel_path=rel_path,
                ts=ts, availability=availability, source_id=obs_id, zone=zone,
                raw=raw or "", confidence=conf, terms=terms, fuzzy=fuzzy,
                fuzzy_threshold=fuzzy_threshold,
            )
    if "labels" in channels:
        for row in _labeled_pins(conn):
            pin_id, sid, raw, normalized, conf, bx, by, bw, bh, cx, cy, filename, rel_path, ts, availability = row
            _emit(
                matches, channel="EXTRACTED_LABEL", sid=sid, filename=filename,
                rel_path=rel_path, ts=ts, availability=availability, source_id=pin_id,
                zone=None, raw=raw or normalized or "", confidence=conf, terms=terms,
                fuzzy=fuzzy, fuzzy_threshold=fuzzy_threshold,
                bbox=(bx, by, bw, bh, cx, cy),
            )

    matches.sort(
        key=lambda m: (
            m.filename_ts is None, m.filename_ts or "", m.screenshot_id,
            m.channel, m.source_record_id, m.match_class, m.matched_term.casefold(),
        )
    )
    total = int(conn.execute("SELECT COUNT(*) FROM screenshots").fetchone()[0])
    ok_sids = {sid for _, sid, *_rest, status in effective if status in ("ok", "empty")}
    failed_sids = {sid for _, sid, *_rest, status in effective if status == "failed"}
    coverage = {
        "screenshots_total": total,
        "screenshots_with_any_ocr": len(ok_sids),
        "screenshots_with_failed_ocr_observation": len(failed_sids),
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
    writer = csv.DictWriter(stream, fieldnames=list(Match.__dataclass_fields__))
    writer.writeheader()
    writer.writerows(asdict(m) for m in matches)


def _args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Search effective FR24 OCR/labeled-pin corpus.")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--query")
    group.add_argument("--theme", choices=["caves"])
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    p.add_argument("--channels", default="ocr,labels")
    p.add_argument("--zones", default=",".join(DEFAULT_ZONES))
    p.add_argument("--include-karst-candidates", action="store_true")
    p.add_argument("--fuzzy", action="store_true")
    p.add_argument("--fuzzy-threshold", type=float, default=0.86)
    p.add_argument("--output", choices=["table", "json", "csv"], default="table")
    p.add_argument("--out", type=Path)
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _args(argv)
    channels = tuple(x.strip() for x in args.channels.split(",") if x.strip())
    zones = tuple(x.strip() for x in args.zones.split(",") if x.strip())
    if not channels or not set(channels) <= {"ocr", "labels"}:
        raise SystemExit("--channels must contain only ocr and/or labels")
    if not zones:
        raise SystemExit("--zones cannot be empty")
    if not 0 < args.fuzzy_threshold <= 1:
        raise SystemExit("--fuzzy-threshold must be in (0,1]")

    if args.query:
        terms = query_terms(args.query)
    else:
        terms = build_terms(
            load_baseline(args.baseline),
            include_candidate_terms=args.include_karst_candidates,
        )

    with sqlite3.connect(args.db) as conn:
        matches, coverage = search_corpus(
            conn, terms=terms, zones=zones, channels=channels,
            fuzzy=args.fuzzy, fuzzy_threshold=args.fuzzy_threshold,
        )

    if args.output == "json":
        text = json.dumps(
            {"coverage": coverage, "matches": [asdict(m) for m in matches]},
            ensure_ascii=False, indent=2,
        )
        args.out.write_text(text, encoding="utf-8") if args.out else print(text)
    elif args.output == "csv":
        stream = args.out.open("w", encoding="utf-8", newline="") if args.out else sys.stdout
        try:
            _write_csv(matches, stream)
        finally:
            if args.out:
                stream.close()
    else:
        print(json.dumps(coverage, ensure_ascii=False, sort_keys=True))
        for m in matches:
            print(
                f"{m.filename_ts or '-'}\t{m.screenshot_id}\t{m.channel}\t"
                f"{m.match_class}\t{m.matched_term}\t{m.raw_text[:100]}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
