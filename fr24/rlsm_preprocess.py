"""
Image preprocessing for RLSM zone OCR.

``fr24/rlsm_zones.py`` has declared a ``preprocess`` mode per zone since the
zone schema was written — ``label_mask`` for the map label layer,
``high_contrast`` for the UI chrome. Both OCR runners read the key and used
only ``psm``: crops went to Tesseract raw. This module implements the modes and
is the single source of truth for the runners and for
``scripts/rlsm_ocr_bench.py``.

Why it matters on this corpus: FR24 map labels are thin antialiased text drawn
over a moving photographic or vector basemap. Tesseract's internal thresholding
assumes document-like input and shreds them — a real read from the corpus is
``"be Baya ecibo"`` for BAYAMON / ARECIBO. Binarizing after an upscale, with the
polarity chosen per crop, is the fix.

Measured over 22 screenshots stride-sampled across every month bucket
(``scripts/rlsm_ocr_bench.py``), distinct gazetteer hits per frame:

    label_layer     raw 0.41  ->  0.86   (words recovered: 53 -> 136)
    aircraft_card   raw 0.30  ->  0.77   (mean confidence: 55.4 -> 60.8)

Preprocessing roughly doubles usable POI matches on both zones. The two gains
have different shapes: the label layer improves through recall — 2.6x the words
survive — while its mean per-word confidence barely moves, because the extra
words are marginal ones that were previously lost entirely. The aircraft card,
already legible, improves in confidence instead. Cost is near neutral: the card
gets slightly faster (1.45s -> 1.36s), the label layer slightly slower
(2.64s -> 3.04s).

Modes:
    none            crop unchanged (the pre-upgrade behaviour)
    high_contrast   grayscale, autocontrast, upscale, Otsu binarize
    label_mask      grayscale, upscale, Otsu binarize, despeckle

Pure PIL — no numpy, matching fr24/rlsm_icons.py.

IMPORTANT: preprocessing rescales the crop, so every consumer of Tesseract word
boxes must divide the returned coordinates by the same factor before storing
them. ``fr24.rlsm_wordboxes.words_from_tesseract_data`` takes a ``scale``
argument for exactly this reason; passing the wrong one silently doubles every
pin coordinate and quietly corrupts the affine geocoder.
"""
from __future__ import annotations

from PIL import Image, ImageFilter, ImageOps

MODES = ("none", "high_contrast", "label_mask")

# Upscale before binarizing: iPhone map labels sit near Tesseract's lower
# resolution limit (~20 px cap height); 2x lands them in its comfortable band.
# 3x was measured: more words, no more gazetteer hits, 1.4x the time.
DEFAULT_SCALE = {"high_contrast": 2.0, "label_mask": 2.0, "none": 1.0}


def scale_for(mode: str, override: float | None = None) -> float:
    """The factor a caller must divide word-box coordinates by."""
    if override is not None:
        return float(override)
    return float(DEFAULT_SCALE.get(mode, 1.0))


def otsu_threshold(hist: list[int]) -> int:
    """Otsu's method over a 256-bin histogram. The histogram is tiny; keep it pure."""
    total = sum(hist)
    if total == 0:
        return 128
    sum_all = sum(i * h for i, h in enumerate(hist))
    sum_b = 0.0
    w_b = 0.0
    best_var = -1.0
    best_t = 128
    for t in range(256):
        w_b += hist[t]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += t * hist[t]
        m_b = sum_b / w_b
        m_f = (sum_all - sum_b) / w_f
        var_between = w_b * w_f * (m_b - m_f) ** 2
        if var_between > best_var:
            best_var = var_between
            best_t = t
    return best_t


def _binarize_auto_polarity(img: Image.Image) -> Image.Image:
    """
    Threshold to black-text-on-white, choosing polarity per crop.

    FR24 draws light labels on dark satellite tiles and dark labels on the light
    basemap, sometimes within one session. Text is always the minority class, so
    whichever side of the Otsu split covers fewer pixels is the ink.
    """
    thresh = otsu_threshold(img.histogram())
    mask = img.point(lambda p, t=thresh: 255 if p > t else 0, mode="L")
    n_pixels = max(1, mask.size[0] * mask.size[1])
    bright_frac = sum(mask.histogram()[255:]) / n_pixels
    return ImageOps.invert(mask) if bright_frac < 0.5 else mask


def preprocess(crop: Image.Image, mode: str = "none",
               scale: float | None = None) -> Image.Image:
    """Apply a zone preprocess mode. Unknown modes pass through unchanged."""
    if mode not in MODES or mode == "none":
        return crop
    factor = scale_for(mode, scale)

    img = crop.convert("L")
    if factor and factor != 1.0:
        img = img.resize((max(1, int(img.width * factor)),
                          max(1, int(img.height * factor))), Image.LANCZOS)
    if mode == "high_contrast":
        img = ImageOps.autocontrast(img, cutoff=1)
        return _binarize_auto_polarity(img)
    img = _binarize_auto_polarity(img)
    # Drop isolated speckle from basemap texture without eroding glyph strokes.
    return img.filter(ImageFilter.MedianFilter(size=3))


def ensure_observation_columns(conn) -> list[str]:
    """
    Add the preprocess stamp columns to an existing ``ocr_observations`` table.

    ``psm`` and ``engine_version`` were already recorded per observation, but
    not which preprocessing produced the text — so nothing in the database
    distinguished a row read from a raw crop from one read after binarizing at
    2x. That matters because resume keys on ``screenshots.ocr_status``: a
    screenshot marked ``ok`` is never re-read, so rows written under an older
    preprocessing config survive indefinitely, worse than their neighbours and
    indistinguishable from them.

    Both columns are nullable, so existing rows stay valid and read as "unknown
    preprocessing" — which is exactly what they are. Returns the columns added.
    """
    have = {r[1] for r in conn.execute("PRAGMA table_info(ocr_observations)")}
    added = []
    for col, decl in (("preprocess", "TEXT"), ("preprocess_scale", "REAL")):
        if col not in have:
            conn.execute(f"ALTER TABLE ocr_observations ADD COLUMN {col} {decl}")
            added.append(col)
    if added:
        conn.commit()
    return added


def config_stamp(cfg: dict) -> tuple[str, float]:
    """The (mode, scale) a zone config resolves to — what gets stored per row."""
    mode = cfg.get("preprocess", "none")
    return mode, scale_for(mode, cfg.get("scale"))
