"""FastAPI router for Phase 1 console capability reporting."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter

from .capabilities import build_capabilities

ROOT = Path(__file__).resolve().parents[3]
router = APIRouter(prefix="/api/console", tags=["console"])


@router.get("/capabilities")
def get_console_capabilities() -> dict[str, Any]:
    """Return explicit support status for all 24 recorded capability groups."""

    return build_capabilities(ROOT)
