"""
Imagery — lightweight change detection.

Deliberately GDAL-free: decode two PNG/JPEG images with Pillow, resize to a
common grid, convert to grayscale, and compute the fraction of pixels whose
normalized absolute difference exceeds a threshold. Good enough for a first-pass
"did this footprint change between two dates" signal, not a calibrated product.
"""

from __future__ import annotations

import io

from . import config
from .models import ChangeResult, ImageryResult


def _grayscale_array(data: bytes):
    from PIL import Image  # local import: Pillow is an imagery extra

    import numpy as np

    with Image.open(io.BytesIO(data)) as img:
        arr = np.asarray(img.convert("L"), dtype="float32") / 255.0
    return arr


def changed_fraction(
    result1: ImageryResult,
    result2: ImageryResult,
    threshold: float | None = None,
) -> ChangeResult:
    """Compare two fetched images; return a :class:`ChangeResult`."""
    import numpy as np

    thr = config.CHANGE_PIXEL_THRESHOLD if threshold is None else threshold

    a = _grayscale_array(result1.image_bytes)
    b = _grayscale_array(result2.image_bytes)

    # Resize to the smaller common shape so differing tile sizes still compare.
    if a.shape != b.shape:
        from PIL import Image

        h = min(a.shape[0], b.shape[0])
        w = min(a.shape[1], b.shape[1])
        a = np.asarray(
            Image.fromarray((a * 255).astype("uint8")).resize((w, h)), dtype="float32"
        ) / 255.0
        b = np.asarray(
            Image.fromarray((b * 255).astype("uint8")).resize((w, h)), dtype="float32"
        ) / 255.0

    diff = np.abs(a - b)
    frac = float((diff > thr).mean())

    return ChangeResult(
        provider=result1.provider,
        bbox=result1.bbox,
        date1=result1.acquired_at or "",
        date2=result2.acquired_at or "",
        changed_fraction=frac,
        changed_pct=round(frac * 100.0, 2),
        threshold=thr,
        result1=result1,
        result2=result2,
    )
