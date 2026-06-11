"""Harvest place names from takeoff/landing endpoint screenshots.

First step of the zone-naming pipeline (see
docs/STRATEGY_zone_name_harvest.md). For each screenshot it:

  1. OCRs the lower band (the FR24 info panel / map-label area),
  2. classifies the frame as an FR24 flight frame or an Earth/Maps ground frame,
  3. for FR24 frames, reuses ``fr24.region_parse`` to pull origin/destination
     codes + flight status, resolves the codes to airport names, and decides
     which endpoint (takeoff vs landing) the frame represents,
  4. assigns a confidence tier and a review reason,

then writes one ``zone_label_candidates.csv`` row per frame. CONFIRMED/PROBABLE
rows are name candidates; REVIEW rows are routed for human labelling.

This is intentionally read-only: it produces candidates, it does not assign
authoritative names. Earth-frame search-bar / POI OCR over satellite imagery is
unreliable and is deferred — those frames are flagged ``ground_frame_needs_label_ocr``.
"""
from __future__ import annotations

import csv
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Optional

try:
    import cv2
    import numpy as np
    import pytesseract
    from PIL import Image
except Exception:  # pragma: no cover - import guard
    cv2 = None  # type: ignore
    np = None  # type: ignore
    pytesseract = None  # type: ignore
    Image = None  # type: ignore

HARVEST_VERSION = "zone_label_harvest_v0.1.0"

REPO = Path(__file__).resolve().parents[1]
PR_LANDING_ZONES_GPKG = REPO / "data" / "reference" / "PR_Landing_Zones_Master.gpkg"
MIL_AVIATION_GPKG = REPO / "data" / "reference" / "Military_and_Aviation.gpkg"
PR_AIRPORTS_JSONL = REPO / "data" / "reference" / "pr_airports.jsonl"  # legacy fallback

# Verification classes (from PR_Landing_Zones_Master) that we trust enough to
# auto-name. Candidate-Low and unverified zones are routed to review instead.
_TRUSTED_VCLASS = {"Active-Verified", "Military-Aviation", "ExternalStatic"}

# Small static gazetteer for the off-PR endpoints that appear in the corpus but
# are not in the PR airport registry. Extend as new codes surface in REVIEW.
EXTRA_AIRPORTS: Dict[str, str] = {
    "MIA": "Miami International Airport",
    "FLL": "Fort Lauderdale-Hollywood International Airport",
    "OPF": "Miami-Opa Locka Executive Airport",
    "FXE": "Fort Lauderdale Executive Airport",
    "MCO": "Orlando International Airport",
    "TPA": "Tampa International Airport",
    "LAL": "Lakeland Linder International Airport",
    "JFK": "John F. Kennedy International Airport",
    "EWR": "Newark Liberty International Airport",
    "IAD": "Washington Dulles International Airport",
    "BGI": "Grantley Adams International Airport (Bridgetown)",
    "SDQ": "Las Américas International Airport (Santo Domingo)",
    "STT": "Cyril E. King Airport (St. Thomas)",
    "STX": "Henry E. Rohlsen Airport (St. Croix)",
    "EIS": "Terrance B. Lettsome Airport (Tortola)",
}

# FR24 selected-flight panels always carry at least two of these tokens.
_FR24_MARKERS = (
    "flightradar", "barometric", "ground speed", "3d view", "more info",
    "departed", "arriving", "arrived", "not available", "altitude", "reg.",
)

_CODE_RE = re.compile(r"\b[A-Z]{3}\b")
# 3-letter tokens that show up in FR24 panels but are NOT airport codes.
_CODE_STOP = {
    "ALT", "REG", "MPH", "NOT", "FOR", "AND", "THE", "VIEW", "KTS", "GLF",
    "SAN", "LOS", "NAT", "FT", "UTC", "EST", "AST", "BAR", "INF",
}
_STATUS_RE = re.compile(
    r"\b(landed|arriving|arrived|departed|estimated|scheduled|en ?route|delayed)\b",
    re.I,
)


def _extract_endpoints(text: str, gaz: Dict[str, str]) -> tuple[str, str, str, str]:
    """Return (origin_code, dest_code, status_hint, code_source).

    ``code_source`` is "gazetteer" (matched known airports — trustworthy),
    "fallback" (clean 3-letter tokens we don't recognise — surface for review),
    or "none". Order of appearance = origin then destination.
    """
    upper = text.upper()
    # 1) high-precision: known airport codes, in order of appearance, de-duped
    seen: list[str] = []
    for m in _CODE_RE.finditer(upper):
        tok = m.group(0)
        if tok in gaz and tok not in seen:
            seen.append(tok)
    source = "none"
    if seen:
        source = "gazetteer"
        origin = seen[0]
        dest = seen[1] if len(seen) > 1 else ""
    else:
        # 2) fallback: the first line carrying two clean 3-letter tokens
        origin = dest = ""
        for line in upper.splitlines():
            toks = [t for t in _CODE_RE.findall(line) if t not in _CODE_STOP]
            if len(toks) >= 2:
                origin, dest, source = toks[0], toks[1], "fallback"
                break
    status = ""
    m = _STATUS_RE.search(text)
    if m:
        status = m.group(1).lower()
    elif "not available" in text.lower() or "n/a" in text.lower():
        status = "not_available"
    return origin, dest, status, source


def _to_review(image_name: str, frame_type: str, reason: str, ocr_chars: int,
               text: str = "") -> dict:
    return _row(image_name, frame_type, "unknown", "", "", "", "", "", "",
                "REVIEW", reason, ocr_chars, text)


def _row(image_name, frame_type, endpoint_kind, t_code, t_name, l_code, l_name,
         flight_status, name_source, tier, review_reason, ocr_chars, text) -> dict:
    return {
        "image_name": image_name,
        "frame_type": frame_type,
        "endpoint_kind": endpoint_kind,
        "takeoff_code": t_code,
        "takeoff_name": t_name,
        "landing_code": l_code,
        "landing_name": l_name,
        "flight_status": flight_status,
        "name_source": name_source,
        "confidence_tier": tier,
        "review_reason": review_reason,
        "ocr_chars": ocr_chars,
        "ocr_excerpt": (text or "")[:160].replace("\n", " "),
        "harvest_version": HARVEST_VERSION,
    }


def load_registry() -> Dict[str, object]:
    """Build the resolution authority from the PR Landing Zones + Military
    GeoPackages (with the legacy JSONL as fallback).

    Returns {"names": code->name, "vclass": code->Verification_Class,
    "places": [ {name, lat, lon, type, status, vclass, icao, iata} ]}.
    The ``places`` list (with lat/lon) is what a later geo-nearest step resolves
    clustered endpoint coordinates against.
    """
    names: Dict[str, str] = {}
    vclass: Dict[str, str] = {}
    places: List[dict] = []
    for c, n in EXTRA_AIRPORTS.items():
        names[c] = n
        vclass[c] = "ExternalStatic"

    if PR_LANDING_ZONES_GPKG.exists():
        con = sqlite3.connect(str(PR_LANDING_ZONES_GPKG))
        try:
            q = ("SELECT Name, Canonical_Name, ICAO, IATA, Latitude, Longitude, "
                 "Landing_Type, Operational_Status, Verification_Class "
                 "FROM all_landing_zones")
            for r in con.execute(q):
                nm = (r[1] or r[0] or "").strip()
                icao = (r[2] or "").strip().upper()
                iata = (r[3] or "").strip().upper()
                vc = (r[8] or "").strip()
                for code in (icao, iata):
                    if code:
                        names[code] = nm
                        vclass[code] = vc
                places.append({"name": nm, "lat": r[4], "lon": r[5], "type": r[6],
                               "status": r[7], "vclass": vc, "icao": icao, "iata": iata})
        finally:
            con.close()
    elif PR_AIRPORTS_JSONL.exists():  # pragma: no cover - legacy path
        for line in PR_AIRPORTS_JSONL.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            nm = r.get("name", "")
            for key in (r.get("iata"), r.get("icao"), r.get("airport_id")):
                if key:
                    names[str(key).upper()] = nm
                    vclass[str(key).upper()] = "Active-Verified"

    if MIL_AVIATION_GPKG.exists():
        con = sqlite3.connect(str(MIL_AVIATION_GPKG))
        try:
            for r in con.execute("SELECT Name, ICAO, Lat, Lon, Type, Status, Owner FROM military_aviation"):
                nm = (r[0] or "").strip()
                icao = (r[1] or "").strip().upper()
                if icao and icao not in names:
                    names[icao] = nm
                    vclass[icao] = "Military-Aviation"
                places.append({"name": nm, "lat": r[2], "lon": r[3], "type": r[4],
                               "status": r[5], "vclass": "Military-Aviation",
                               "icao": icao, "iata": ""})
        finally:
            con.close()

    return {"names": names, "vclass": vclass, "places": places}


def load_gazetteer() -> Dict[str, str]:
    """Back-compat thin wrapper: code -> name."""
    return load_registry()["names"]  # type: ignore[return-value]


def resolve_code(code: str, gaz: Dict[str, str]) -> str:
    if not code:
        return ""
    return gaz.get(code.upper(), "")


def ocr_lower_band(image_path: str) -> str:
    """OCR the lower ~40% (FR24 panel / map labels) with upscaling."""
    if pytesseract is None:
        raise RuntimeError("pytesseract is required")
    im = Image.open(image_path).convert("RGB")
    w, h = im.size
    crop = im.crop((0, int(h * 0.60), w, h))
    g = np.array(crop.convert("L"))
    up = cv2.resize(g, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    return pytesseract.image_to_string(up, config="--psm 6")


def classify_frame(text: str) -> str:
    low = text.lower()
    hits = sum(1 for m in _FR24_MARKERS if m in low)
    return "fr24" if hits >= 2 else "earth_or_other"


def _endpoint_kind(status: str) -> str:
    s = (status or "").lower()
    if "depart" in s:
        return "takeoff"
    if "arriv" in s or "land" in s:
        return "landing"
    return "unknown"


def harvest_image(image_path: str, reg) -> dict:
    # ``reg`` may be the full registry dict (names + vclass) or a plain
    # code->name map (back-compat).
    if isinstance(reg, dict) and "names" in reg:
        names = reg["names"]
        vcl = reg.get("vclass", {})
    else:
        names, vcl = reg, {}
    name = Path(image_path).name
    try:
        text = ocr_lower_band(image_path)
    except Exception as exc:  # pragma: no cover
        return _to_review(name, "unknown", f"ocr_error:{type(exc).__name__}", 0)

    chars = len(text.strip())
    if chars < 15:
        return _to_review(name, "unknown", "ocr_empty_or_blank", chars, text)

    frame_type = classify_frame(text)
    if frame_type != "fr24":
        # Ground/Earth frame: the facility name is on the image but sits over
        # satellite imagery; reliable POI/search-bar OCR is a deferred step.
        return _to_review(name, frame_type, "ground_frame_needs_label_ocr", chars, text)

    origin, dest, status, code_source = _extract_endpoints(text, names)
    o_name = resolve_code(origin, names)
    d_name = resolve_code(dest, names)
    n_named = bool(o_name) + bool(d_name)
    ek = "both" if (origin and dest) else ("origin_only" if origin else
                                           "dest_only" if dest else "unknown")

    # N/A flights, or panels with no readable code, always go to review.
    if status == "not_available":
        return _row(name, "fr24", "unknown", "", "", "", "", status,
                    "fr24_panel", "REVIEW", "panel_no_airport_code", chars, text)

    if code_source == "gazetteer":
        # verification class of the resolved endpoint codes drives the tier
        resolved = [c for c, nm in ((origin, o_name), (dest, d_name)) if nm]
        vcs = {vcl.get(c, "") for c in resolved}
        if "Candidate-Low" in vcs:
            tier, reason, src = "REVIEW", "candidate_low_needs_verification", "registry_candidate"
        elif "Historic/Inactive" in vcs:
            tier, reason, src = "CONFIRMED", "historic_facility", "registry_historic"
        elif n_named < (bool(origin) + bool(dest)):
            tier, reason, src = "PROBABLE", "partial_unresolved_code", "fr24_panel_partial"
        else:
            tier, reason, src = "CONFIRMED", "", "registry_resolved"
        return _row(name, "fr24", ek, origin, o_name, dest, d_name,
                    status, src, tier, reason, chars, text)

    if code_source == "fallback":
        # plausible 3-letter codes we don't recognise: surface so the gazetteer
        # can be extended, but never auto-name from them.
        return _row(name, "fr24", ek, origin, "", dest, "", status,
                    "fr24_panel", "REVIEW", "unknown_codes_extend_gazetteer", chars, text)

    return _row(name, "fr24", "unknown", "", "", "", "", status,
                "fr24_panel", "REVIEW", "no_codes_in_panel", chars, text)


FIELDNAMES = [
    "image_name", "frame_type", "endpoint_kind", "takeoff_code", "takeoff_name",
    "landing_code", "landing_name", "flight_status", "name_source",
    "confidence_tier", "review_reason", "ocr_chars", "ocr_excerpt",
    "harvest_version",
]


def harvest_paths(paths, out_csv: Path, reg: Optional[dict] = None,
                  progress_every: int = 25) -> dict:
    reg = reg or load_registry()
    counts: Dict[str, int] = {}
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        w.writeheader()
        for i, p in enumerate(paths, 1):
            row = harvest_image(str(p), reg)
            w.writerow(row)
            counts[row["confidence_tier"]] = counts.get(row["confidence_tier"], 0) + 1
            if progress_every and i % progress_every == 0:
                print(f"  ...{i} frames", file=sys.stderr, flush=True)
    return {"total": sum(counts.values()), "by_tier": counts, "output": str(out_csv)}


def main(argv=None) -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Harvest endpoint zone-name candidates from screenshots.")
    ap.add_argument("images", nargs="+", help="image files or globs")
    ap.add_argument("--out", default="data/_manifests/fr24_audit/zone_label_candidates.csv")
    args = ap.parse_args(argv)
    paths = []
    for a in args.images:
        p = Path(a)
        paths.extend(sorted(Path().glob(a)) if any(c in a for c in "*?[") else [p])
    summary = harvest_paths(paths, Path(args.out))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
