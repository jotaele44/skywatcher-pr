"""
Word-level OCR boxes for RLSM ``ocr_observations.raw_lines_json``.

Both OCR runners already call ``pytesseract.image_to_data``, which returns a
bounding box and a confidence for every word — and both then threw all of it
away, joining the words into a flat string and writing ``json.dumps([])`` into
the ``raw_lines_json`` column that has existed in ``data/rlsm/schema.sql`` since
the schema was written.

That discarded geometry is exactly what the label extractor needs. Keeping it
costs no extra OCR: same call, same crop, we simply stop dropping the result.
It also makes ``scripts/rlsm_reocr_label_layer.py`` — a whole separate
corpus-wide re-OCR pass whose only job was to recover these boxes — unnecessary.

Storage format (list of dicts, short keys because this is stored per zone per
screenshot and the corpus is ~13.3k images):

    t  text        the word as Tesseract read it
    x  left        full-image pixel coordinate, zone origin already added
    y  top         full-image pixel coordinate, zone origin already added
    w  width       pixels
    h  height      pixels
    c  confidence  0-100

Coordinates are translated out of the crop and into full-image space at write
time, so consumers never need to know which zone a word came from to place it.
"""
from __future__ import annotations

import json
from typing import Any

# Words below these thresholds are dropped before storage. Tesseract emits a lot
# of single-character noise off map textures and UI glyphs; keeping it would
# roughly double the stored JSON for no gain.
MIN_WORD_CONF = 30.0
MIN_WORD_LEN = 2


def words_from_tesseract_data(data: dict[str, Any], x_off: int = 0,
                              y_off: int = 0, scale: float = 1.0) -> list[dict]:
    """
    Build the stored word list from a ``pytesseract.Output.DICT`` result.

    ``x_off``/``y_off`` are the crop origin, added so the boxes land in
    full-image coordinates.

    ``scale`` is the factor the crop was upscaled by before OCR (see
    fr24/rlsm_preprocess.py). Tesseract reports boxes in the coordinates of the
    image it was handed, so the factor is divided out *before* the offset is
    added — the offset is in source pixels, not scaled ones. Getting this wrong
    does not raise; it silently multiplies every pin coordinate, which the
    affine geocoder then fits happily and wrongly.
    """
    sc = float(scale) or 1.0  # `or 1.0` so a 0.0 scale degrades to identity
    out: list[dict] = []
    texts = data.get("text") or []
    for i, raw in enumerate(texts):
        text = (raw or "").strip()
        if len(text) < MIN_WORD_LEN:
            continue
        try:
            conf = float(data["conf"][i])
            x = int(data["left"][i])
            y = int(data["top"][i])
            w = int(data["width"][i])
            h = int(data["height"][i])
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        if conf < MIN_WORD_CONF:
            continue
        out.append({"t": text,
                    "x": int(x / sc) + x_off, "y": int(y / sc) + y_off,
                    "w": int(w / sc), "h": int(h / sc),
                    "c": round(conf, 1)})
    return out


def load_words(raw_lines_json: str | None) -> list[dict]:
    """Parse a stored ``raw_lines_json`` value; tolerant of legacy/empty rows."""
    if not raw_lines_json:
        return []
    try:
        parsed = json.loads(raw_lines_json)
    except (ValueError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [w for w in parsed if isinstance(w, dict) and "t" in w]


def union_box(words: list[dict]) -> tuple[int, int, int, int] | None:
    """Union bounding box over a group of words → ``(x, y, w, h)``."""
    if not words:
        return None
    x0 = min(w["x"] for w in words)
    y0 = min(w["y"] for w in words)
    x1 = max(w["x"] + w["w"] for w in words)
    y1 = max(w["y"] + w["h"] for w in words)
    return x0, y0, x1 - x0, y1 - y0
