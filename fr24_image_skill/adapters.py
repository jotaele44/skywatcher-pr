from __future__ import annotations

"""Import-safe capability registry for the FR24 two-stage image-analysis skill.

The registry never executes a module's CLI or parses ``--help`` output.  It
imports known Python symbols and reports a typed capability state.  Callers may
then use the repository-native implementation or record an explicit degraded
status without synthesizing analytical findings.
"""

from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from typing import Any


@dataclass(frozen=True)
class AdapterCapability:
    name: str
    module: str
    symbol: str
    available: bool
    implementation: Any | None = None
    error: str | None = None


def _load(name: str, module: str, symbols: tuple[str, ...]) -> AdapterCapability:
    try:
        loaded = import_module(module)
    except Exception as exc:  # dependency/import failure is an explicit state
        return AdapterCapability(name, module, symbols[0], False, error=f"{type(exc).__name__}: {exc}")
    for symbol in symbols:
        implementation = getattr(loaded, symbol, None)
        if implementation is not None:
            return AdapterCapability(name, module, symbol, True, implementation)
    return AdapterCapability(name, module, symbols[0], False, error=f"none of {symbols!r} exported")


def discover_capabilities() -> dict[str, AdapterCapability]:
    """Return all required workflow adapters without invoking analytical work."""
    specifications = {
        "ui_segmenter": ("fr24.ui_segmenter", ("FR24UISegmenter",)),
        "region_ocr": ("fr24.region_ocr", ("extract_regions", "RegionOCR", "run_region_ocr")),
        "rlsm_ocr": ("fr24.rlsm_ocr", ("extract", "run", "RLSMOCR")),
        "flight_fusion": ("fr24.flight_fusion", ("fuse_flight_wave", "fuse_observations", "FlightFusion")),
        "track_vectorizer": ("fr24.track_vectorizer", ("vectorize_image", "TrackVectorizer")),
        "affine_georegistration": ("fr24.rlsm_geo_anchors", ("fit_affine", "geocode_frame", "AffineCalibration")),
        "satim_engine": ("fr24.satim_engine", ("run", "SATIMEngine", "main")),
        "tile_seam_classifier": ("satim_tile_seam_classifier", ("classify", "classify_tile_seam", "TileSeamClassifier")),
    }
    return {
        name: _load(name, module, symbols)
        for name, (module, symbols) in specifications.items()
    }


def capability_report() -> list[dict[str, object]]:
    """JSON-serializable capability report suitable for a run manifest."""
    return [
        {
            "name": capability.name,
            "module": capability.module,
            "symbol": capability.symbol,
            "available": capability.available,
            "error": capability.error,
        }
        for capability in discover_capabilities().values()
    ]


def require_capability(name: str) -> Callable[..., Any] | type[Any]:
    capabilities = discover_capabilities()
    if name not in capabilities:
        raise KeyError(name)
    capability = capabilities[name]
    if not capability.available or capability.implementation is None:
        raise RuntimeError(f"adapter {name!r} unavailable: {capability.error}")
    return capability.implementation
