"""Imaging-filter hints for Sky Target Finder targets (a heuristic, not a measurement).

Line-emitting objects (H-alpha/OIII) suit a dual-band ("Duo-Band") filter;
continuum sources such as galaxies and star clusters suit broadband imaging.
Stars, solar-system bodies and satellites get no hint.
"""

from __future__ import annotations

_DUO_BAND = frozenset(
    {"emission_nebula", "supernova_remnant", "planetary_nebula", "cluster_with_nebula"}
)
_BROADBAND = frozenset(
    {
        "galaxy",
        "open_cluster",
        "globular_cluster",
        "reflection_nebula",
        "star_cloud",
        "asterism",
        "double_star",
        "dark_nebula",
    }
)


def filter_hint(object_type: str | None) -> dict[str, str] | None:
    """{"label": ..., "basis": "heuristic"} for a catalog object_type, or None."""
    if object_type in _DUO_BAND:
        return {"label": "Duo-Band", "basis": "heuristic"}
    if object_type in _BROADBAND:
        return {"label": "Broadband", "basis": "heuristic"}
    return None
