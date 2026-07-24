"""SCREENSHOT SOURCE ABSTRACTION (mission responsibilities 1 & 2)

A screenshot *source* enumerates candidate FR24 screenshot files and validates
their extensions. This module unifies the two historically divergent supported-
extension sets (``fr24.screenshot_inventory.SUPPORTED_EXTS`` and
``scripts.ingest_fr24_screenshot_packet.SUPPORTED_EXTENSIONS``) into one
canonical set and provides a small, testable source abstraction.

CODE-ONLY: this module never processes screenshot *contents*; ``iter_screenshots``
only lists paths whose suffix is a supported image extension. Directory discovery
is explicit (caller supplies the directory); there is no auto-discovery of user
screenshot folders.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Union

# Canonical union of the previously divergent extension sets. ``.pdf`` and
# ``.heif`` come from the packet ingester; the rest from the inventory scanner.
SUPPORTED_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff", ".tif", ".heic", ".heif"}
)

__all__ = [
    "SUPPORTED_EXTENSIONS",
    "is_supported_extension",
    "ScreenshotSource",
    "DirectoryScreenshotSource",
]


def is_supported_extension(path: Union[str, Path]) -> bool:
    """True if ``path`` has a supported image extension (case-insensitive)."""
    return Path(path).suffix.lower() in SUPPORTED_EXTENSIONS


@dataclass(frozen=True)
class ScreenshotSource:
    """Base description of where screenshots come from. Subclasses implement
    :meth:`iter_screenshots`. Kept minimal and dependency-free so it can be
    unit-tested against synthetic temp directories."""

    root: Path

    def iter_screenshots(self) -> Iterator[Path]:  # pragma: no cover - abstract
        raise NotImplementedError


class DirectoryScreenshotSource(ScreenshotSource):
    """A screenshot source backed by a filesystem directory.

    ``available()`` reports whether the configured directory exists, so callers
    (e.g. the CLI) can emit an actionable error instead of silently processing
    zero images. ``iter_screenshots`` yields supported files in deterministic
    (sorted) order and does NOT read file contents.
    """

    def __init__(self, root: Union[str, Path], recursive: bool = True):
        object.__setattr__(self, "root", Path(root))
        object.__setattr__(self, "recursive", recursive)

    def available(self) -> bool:
        return self.root.is_dir()

    def iter_screenshots(self) -> Iterator[Path]:
        if not self.root.is_dir():
            return
        walker = self.root.rglob("*") if self.recursive else self.root.glob("*")
        for path in sorted(walker):
            if path.is_file() and is_supported_extension(path):
                yield path

    def count(self) -> int:
        return sum(1 for _ in self.iter_screenshots())
