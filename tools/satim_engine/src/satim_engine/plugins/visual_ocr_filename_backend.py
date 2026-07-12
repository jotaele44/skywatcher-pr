"""Deterministic filename-hint ``VisualOcrBackend`` (bundled, opt-in).

This is a conservative, offline OCR *backend* for the seam exposed by
:func:`satim_engine.plugins.visual_ocr.extract_visual_metadata`. It performs **no**
pixel analysis: it parses callsign / tail / timestamp tokens out of the file
*name* only, using tight regexes so it emits a hint only when a token is
unambiguous.

It is deliberately **not** wired into the default path. The default
``extract_visual_metadata(path)`` (no backend) keeps its byte-for-byte
``FILENAME_ONLY`` / ``None``-hints contract. To use this parser, pass it
explicitly::

    from satim_engine.plugins.visual_ocr import extract_visual_metadata
    from satim_engine.plugins.visual_ocr_filename_backend import filename_hint_backend

    meta = extract_visual_metadata(path, backend=filename_hint_backend)

When a real pixel OCR engine (pytesseract / easyocr / a hosted vision model)
becomes available, inject it the same way; this module is the reference
implementation of the backend shape, not a substitute for real OCR.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional

PLUGIN = "visual_ocr.filename_hint"

# Token boundary: a filename separator or a string edge. Hyphens/colons are
# separators too, so tail/callsign tokens are bounded but ISO timestamps (which
# embed ':' and '-') are matched as a whole by their own dedicated patterns.
_BEFORE = r"(?<![A-Za-z0-9])"
_AFTER = r"(?![A-Za-z0-9])"

# US registration / tail: 'N' + 1-5 digits + up to 2 trailing letters (FAA
# N-number shape). The single leading letter keeps N-numbers out of the
# callsign bucket (which needs a 2-4 letter prefix).
_RE_TAIL_N = re.compile(_BEFORE + r"N[0-9]{1,5}[A-Z]{0,2}" + _AFTER)
# Canada-style tail, e.g. C-GXYZ.
_RE_TAIL_C = re.compile(_BEFORE + r"C-[A-Z]{4}" + _AFTER)

# Airline-style callsign: 2-4 letters then 1-4 digits with an optional trailing
# letter (AAL123, DAL45, FURA1).
_RE_CALLSIGN = re.compile(_BEFORE + r"[A-Z]{2,4}[0-9]{1,4}[A-Z]?" + _AFTER)

# Timestamp forms, most specific first. Each is bounded so it is not a fragment
# of a longer alphanumeric run:
#   2026-01-01T18:42:05Z / 2026-01-01T18-42 / 2026-01-01_18:42
#   2026-01-01
#   20260101T184205Z / 20260101
#   18:42:05Z / 18:42Z (bare clock time)
_TIMESTAMP_PATTERNS = tuple(
    re.compile(_BEFORE + body + _AFTER)
    for body in (
        r"\d{4}-\d{2}-\d{2}[T_]\d{2}[:\-]\d{2}(?:[:\-]\d{2})?Z?",
        r"\d{4}-\d{2}-\d{2}",
        r"\d{8}T\d{4,6}Z?",
        r"\d{8}",
        r"\d{2}:\d{2}(?::\d{2})?Z?",
    )
)

# Source/app tags that are structurally callsign-shaped but are never real
# callsigns. Kept tiny and explicit so the parser stays conservative.
_CALLSIGN_STOPWORDS = frozenset({"FR24", "FLIGHTRADAR24"})


def _first_timestamp(stem: str) -> Optional[str]:
    for pat in _TIMESTAMP_PATTERNS:
        match = pat.search(stem)
        if match:
            return match.group(0)
    return None


def parse_filename_hints(name: str) -> Dict[str, Optional[str]]:
    """Parse callsign / tail / timestamp hints out of a filename (or stem).

    Returns a mapping with exactly ``callsign_hint`` / ``tail_hint`` /
    ``timestamp_hint`` keys; each is the first confident match or ``None``.
    Deterministic and side-effect free — the unit of behavior under test.
    """
    stem = Path(name).stem if ("/" in name or "\\" in name or "." in name) else name
    upper = stem.upper()

    hints: Dict[str, Optional[str]] = {
        "callsign_hint": None,
        "tail_hint": None,
        "timestamp_hint": _first_timestamp(stem),
    }

    tail_match = _RE_TAIL_N.search(upper) or _RE_TAIL_C.search(upper)
    if tail_match:
        hints["tail_hint"] = tail_match.group(0)

    for candidate in _RE_CALLSIGN.finditer(upper):
        token = candidate.group(0)
        if token == hints["tail_hint"] or token in _CALLSIGN_STOPWORDS:
            continue
        hints["callsign_hint"] = token
        break
    return hints


def filename_hint_backend(path: str) -> Dict[str, Any]:
    """A ``VisualOcrBackend``: map an image path to filename-derived hints.

    Only the hint fields that were confidently parsed are returned (plus the
    plugin/status labels), so the ``extract_visual_metadata`` seam keeps the
    filename defaults for anything this parser could not resolve.
    """
    hints = parse_filename_hints(path)
    result: Dict[str, Any] = {"plugin": PLUGIN, "ocr_status": "FILENAME_HINT"}
    for field, value in hints.items():
        if value is not None:
            result[field] = value
    return result
