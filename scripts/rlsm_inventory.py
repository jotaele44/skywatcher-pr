#!/usr/bin/env python3
"""Compatibility entry point for the provenance-first RLSM corpus freeze.

The historical inventory path is retained because ``fr24.rlsm_pipeline`` and
operator runbooks invoke this script directly.  The implementation now lives in
``fr24.rlsm_corpus_ingest`` so the pipeline cannot silently use the former
SHA-deduplicating inventory behavior.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from fr24.rlsm_corpus_ingest import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
