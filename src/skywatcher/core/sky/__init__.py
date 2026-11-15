"""Sky Target Finder: a read-only sky catalog, observer-frame ephemeris and chart service.

Surfaced in the GUI at /space-track/sky through the GET /api/space-track/sky/*
endpoints. Positions of stars and deep-sky objects come from the vendored catalog
in data/reference/sky; the Sun, Moon and planets from astronomy-engine; and
satellites from SGP4 over the locally frozen Space-Track ``space_objects``
materialization. Nothing in this package writes data or calls Space-Track.
"""

from .catalog import CatalogObject, SkyCatalog, load_catalog, normalize_text
from .ephemeris import Observer, SkyFrame, Visibility
from .filters import filter_hint
from .service import (
    DEFAULT_OBSERVER,
    TARGET_KINDS,
    chart_payload,
    parse_at,
    recommend_payload,
    targets_payload,
)

__all__ = [
    "DEFAULT_OBSERVER",
    "TARGET_KINDS",
    "CatalogObject",
    "Observer",
    "SkyCatalog",
    "SkyFrame",
    "Visibility",
    "chart_payload",
    "filter_hint",
    "load_catalog",
    "normalize_text",
    "parse_at",
    "recommend_payload",
    "targets_payload",
]
