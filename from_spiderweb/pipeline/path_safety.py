"""Path-traversal-safe filesystem helpers (T11-90).

File-ingest code that joins a base directory with an externally-influenced
relative path (a filename from OCR, a manifest entry, an upload name) must not be
tricked into escaping the base with ``..`` or an absolute path. Route those joins
through :func:`safe_join`, which resolves the result and confirms it stays inside
the base directory.
"""

from __future__ import annotations

from pathlib import Path


class PathTraversalError(ValueError):
    """Raised when a resolved path escapes its intended base directory."""


def is_within(base: Path, target: Path) -> bool:
    """True if *target* (resolved) is *base* itself or lives under it."""
    base_r = base.resolve()
    target_r = target.resolve()
    return base_r == target_r or base_r in target_r.parents


def safe_join(base: str | Path, *parts: str) -> Path:
    """Join *parts* onto *base* and confirm the result stays within *base*.

    Args:
        base: the trusted base directory.
        parts: untrusted path components (filenames, relative paths).

    Returns:
        The resolved path inside *base*.

    Raises:
        PathTraversalError: if the joined path escapes *base* (e.g. via ``..``
            or an absolute component).
    """
    base_path = Path(base)
    candidate = base_path.joinpath(*parts)
    if not is_within(base_path, candidate):
        raise PathTraversalError(
            f"path escapes base directory: base={base_path!s} parts={parts!r}"
        )
    return candidate.resolve()
