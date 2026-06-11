"""Map ``--verbose`` / ``--quiet`` CLI flags to a logging level (T10-82).

Kept tiny and dependency-free so every runner can share the same precedence
rule: ``--verbose`` wins over ``--quiet`` if both are passed.
"""

from __future__ import annotations

import logging


def resolve_log_level(
    *, verbose: bool = False, quiet: bool = False, default: int = logging.INFO
) -> int:
    """Return the logging level for the given verbosity flags.

    Precedence: ``verbose`` (DEBUG) > ``quiet`` (WARNING) > ``default``.
    """
    if verbose:
        return logging.DEBUG
    if quiet:
        return logging.WARNING
    return default
