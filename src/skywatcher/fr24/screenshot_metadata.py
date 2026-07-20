"""SCREENSHOT METADATA EXTRACTION (mission responsibility 8)

Extracts non-content metadata about a screenshot file: a timestamp derived from
the filename, byte size, and (optionally) pixel dimensions. Filename-timestamp
parsing is pure and unit-testable with synthetic strings; dimension probing uses
Pillow lazily so the module imports without the image stack.

CODE-ONLY: nothing here reads image *pixels* except the optional, lazy
dimension probe, which callers opt into explicitly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

# FR24 export filenames commonly embed an ISO-like timestamp, e.g.
# "FR24_2026-05-28_14-03-11.png" or "2026-05-28 14.03.11.jpg".
_FILENAME_TS_RE = re.compile(
    r"(?P<y>20\d{2})[-_]?(?P<mo>\d{2})[-_]?(?P<d>\d{2})"
    r"[ _T]?(?P<h>\d{2})[-_.:]?(?P<mi>\d{2})(?:[-_.:]?(?P<s>\d{2}))?"
)

__all__ = ["ScreenshotMetadata", "parse_filename_timestamp", "extract_metadata"]


def parse_filename_timestamp(filename: str) -> Optional[str]:
    """Return an ISO-8601 timestamp parsed from ``filename``, or None.

    Pure string parsing; does not touch the filesystem.
    """
    m = _FILENAME_TS_RE.search(Path(filename).name)
    if not m:
        return None
    g = m.groupdict()
    sec = g.get("s") or "00"
    return f"{g['y']}-{g['mo']}-{g['d']}T{g['h']}:{g['mi']}:{sec}"


@dataclass
class ScreenshotMetadata:
    path: str
    filename: str
    size_bytes: int
    filename_timestamp: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    ext: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "filename": self.filename,
            "size_bytes": self.size_bytes,
            "filename_timestamp": self.filename_timestamp,
            "width": self.width,
            "height": self.height,
            "ext": self.ext,
            **self.extra,
        }


def extract_metadata(
    path: Union[str, Path], *, probe_dimensions: bool = False
) -> ScreenshotMetadata:
    """Build :class:`ScreenshotMetadata` for ``path``.

    ``probe_dimensions=True`` opens the image with Pillow (lazy import) to read
    width/height; the default leaves dimensions ``None`` so the function stays
    free of the image dependency and never decodes pixels.
    """
    p = Path(path)
    size = p.stat().st_size if p.is_file() else 0
    meta = ScreenshotMetadata(
        path=str(p),
        filename=p.name,
        size_bytes=size,
        filename_timestamp=parse_filename_timestamp(p.name),
        ext=p.suffix.lower(),
    )
    if probe_dimensions and p.is_file():  # pragma: no cover - requires Pillow
        try:
            from PIL import Image  # noqa: WPS433

            with Image.open(p) as img:
                meta.width, meta.height = img.size
        except Exception as exc:  # noqa: BLE001
            meta.extra["dimension_error"] = str(exc)
    return meta
