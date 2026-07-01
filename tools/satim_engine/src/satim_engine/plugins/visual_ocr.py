from __future__ import annotations
from pathlib import Path
from typing import Dict, Any

def extract_visual_metadata(path: str) -> Dict[str, Any]:
    """Lightweight OCR plugin placeholder.
    Uses filename metadata by default; can be replaced with pytesseract/easyocr adapter.
    Never fails the pipeline: returns status and provenance.
    """
    p = Path(path)
    name = p.stem
    return {
        "visual_path": str(p),
        "ocr_status": "FILENAME_ONLY",
        "text": name,
        "callsign_hint": None,
        "timestamp_hint": None,
        "tail_hint": None,
        "plugin": "visual_ocr.default_filename_adapter"
    }
