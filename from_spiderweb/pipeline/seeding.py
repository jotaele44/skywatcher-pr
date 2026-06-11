"""Deterministic global seeding for reproducible runs (T10-86).

Stochastic steps (sampling, shuffling, any numpy RNG) must be seeded so a run is
reproducible — a requirement of the release gate's reproducibility block (D3).
Call :func:`set_global_seed` once at the start of a run; it seeds Python's
``random`` and, when available, ``numpy.random``. ``numpy`` is optional so this
module stays import-safe in environments without the scientific stack.
"""

from __future__ import annotations

import random

DEFAULT_SEED = 1729


def set_global_seed(seed: int = DEFAULT_SEED) -> int:
    """Seed Python ``random`` and (if importable) ``numpy.random``.

    Returns the seed used, so callers can record it in a manifest.
    """
    random.seed(seed)
    try:
        import numpy as np
    except ImportError:  # pragma: no cover - numpy is normally present
        pass
    else:
        np.random.seed(seed)
    return seed
