"""Compatibility entrypoint for the canonical GATIM runner."""
from __future__ import annotations

from tools.gatim.runner import build, main

__all__ = ["build", "main"]

if __name__ == "__main__":
    main()
