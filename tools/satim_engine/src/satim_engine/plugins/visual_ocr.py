"""SATIM visual OCR plugin.

Extracts visual metadata from a screenshot/imagery path. The default path is a
deterministic, offline **filename adapter**: it derives no pixel-level text and
never fails the pipeline, returning the file stem plus explicit ``FILENAME_ONLY``
provenance and ``None`` hint fields.

Real OCR requires an image engine (pytesseract / easyocr / a hosted vision
model) that is intentionally *not* a hard dependency here. Rather than fake OCR
output, this module exposes a typed extension point: pass a ``backend`` callable
that maps a path to a metadata mapping and its result is merged over the
filename defaults. That keeps the offline contract intact while giving a clean,
single seam for a production OCR backend to plug into.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional

# A backend maps an image path to a partial metadata mapping. Any subset of the
# canonical keys below may be returned; missing keys keep their filename default.
VisualOcrBackend = Callable[[str], Dict[str, Any]]

DEFAULT_PLUGIN = "visual_ocr.default_filename_adapter"

# Canonical hint fields carried by every visual-OCR row. Kept explicit so the
# downstream ledger schema stays stable whether or not a backend is supplied.
_HINT_FIELDS = ("callsign_hint", "timestamp_hint", "tail_hint")


def _filename_metadata(path: str) -> Dict[str, Any]:
    """Deterministic offline metadata derived purely from the filename."""
    p = Path(path)
    return {
        "visual_path": str(p),
        "ocr_status": "FILENAME_ONLY",
        "text": p.stem,
        "callsign_hint": None,
        "timestamp_hint": None,
        "tail_hint": None,
        "plugin": DEFAULT_PLUGIN,
    }


def extract_visual_metadata(
    path: str,
    backend: Optional[VisualOcrBackend] = None,
) -> Dict[str, Any]:
    """Return visual metadata for *path*.

    With no *backend* (the default) this is the offline filename adapter and its
    output is unchanged: ``ocr_status='FILENAME_ONLY'`` and ``None`` hints.

    When a *backend* is supplied it is invoked with the path and its mapping is
    merged over the filename defaults, so a backend may fill any of
    ``text`` / ``callsign_hint`` / ``timestamp_hint`` / ``tail_hint`` and set its
    own ``ocr_status`` / ``plugin`` label. A backend that raises does not break
    the pipeline: the row degrades to the filename adapter with an
    ``OCR_BACKEND_ERROR`` status and the error recorded under ``ocr_error``.
    """
    base = _filename_metadata(path)
    if backend is None:
        return base

    try:
        result = backend(path) or {}
    except Exception as exc:  # never fail the batch on a backend error
        base["ocr_status"] = "OCR_BACKEND_ERROR"
        base["ocr_error"] = f"{type(exc).__name__}: {exc}"
        return base

    merged = dict(base)
    merged.update(result)
    # Ensure the canonical hint fields always exist even if the backend omitted them.
    for field in _HINT_FIELDS:
        merged.setdefault(field, None)
    if "plugin" not in result:
        merged["plugin"] = "visual_ocr.backend"
    if "ocr_status" not in result:
        merged["ocr_status"] = "OCR_BACKEND"
    return merged
