"""FLIGHTRADAR24 OCR ABSTRACTION (mission responsibility 4)

Single import surface for FR24 OCR. Historically OCR lived in several modules
(``fr24.region_ocr``, ``fr24.rlsm_ocr``, ``fr24.ocr_probe``,
``fr24.zone_label_harvest``, ``fr24.ui_segmenter``). This module defines a small
``OCREngine`` protocol and a default Tesseract-backed engine, and re-exports the
existing region/zone OCR entry points.

Heavy third-party OCR/image dependencies (``pytesseract``, ``PIL``, ``cv2``) are
imported lazily *inside* methods so that importing this module — and the whole
``skywatcher.fr24`` package — never requires the OCR stack to be installed. This
keeps unit tests (which use synthetic OCR strings) dependency-free.

CODE-ONLY: nothing here processes real screenshots at import time.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

__all__ = [
    "OCREngine",
    "TesseractOCREngine",
    "run_region_ocr",
    "extract_text_region",
]


@runtime_checkable
class OCREngine(Protocol):
    """Minimal OCR engine contract: turn an image (path or array) + optional
    region into recognized text plus a confidence estimate."""

    def image_to_text(self, image: Any, *, psm: int = 6) -> str: ...

    def image_to_text_with_confidence(
        self, image: Any, *, psm: int = 6
    ) -> tuple[str, float]: ...


class TesseractOCREngine:
    """Default OCR engine backed by Tesseract via ``pytesseract``.

    ``pytesseract`` is imported lazily on first use; construction is free of the
    OCR dependency so the class can be referenced/mocked in tests.
    """

    def __init__(self, lang: str = "eng"):
        self.lang = lang

    def _pytesseract(self):  # pragma: no cover - requires optional dep
        import pytesseract  # noqa: WPS433 (lazy on purpose)

        return pytesseract

    def image_to_text(self, image: Any, *, psm: int = 6) -> str:  # pragma: no cover
        pt = self._pytesseract()
        return pt.image_to_string(image, config=f"--psm {psm}")

    def image_to_text_with_confidence(  # pragma: no cover
        self, image: Any, *, psm: int = 6
    ) -> tuple[str, float]:
        pt = self._pytesseract()
        data = pt.image_to_data(image, config=f"--psm {psm}", output_type=pt.Output.DICT)
        confs = [int(c) for c in data.get("conf", []) if str(c).lstrip("-").isdigit() and int(c) >= 0]
        text = " ".join(w for w in data.get("text", []) if w and w.strip())
        conf = (sum(confs) / len(confs) / 100.0) if confs else 0.0
        return text, conf


def run_region_ocr(*args, **kwargs):
    """Delegate to the existing region OCR runner (lazy import)."""
    from fr24.region_ocr import run_region_ocr as _impl  # noqa: WPS433

    return _impl(*args, **kwargs)


def extract_text_region(*args, **kwargs):
    """Delegate to the existing region text extractor (lazy import)."""
    from fr24.region_ocr import extract_text_region as _impl  # noqa: WPS433

    return _impl(*args, **kwargs)
