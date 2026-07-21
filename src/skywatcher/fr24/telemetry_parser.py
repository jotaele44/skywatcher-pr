"""TELEMETRY FIELD PARSING + COORDINATE PARSING (mission responsibilities 6 & 7)

Parses telemetry fields (callsign, registration, aircraft type, altitude, speed,
origin/destination airport codes) from normalized OCR text, and resolves
per-screenshot pixel->geo coordinates with an explicit coordinate method and
confidence.

Telemetry regex parsing wraps ``fr24.region_parse`` (pure stdlib + ``re``) and
field selection wraps ``fr24.field_select``; both are safe to import eagerly.
Coordinate parsing wraps ``integration.geo_calibration`` (which may pull in
``numpy``) and is therefore imported lazily inside the coordinate helpers so the
package imports without geospatial deps.
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

from fr24.field_select import FIELD_SELECT_VERSION, choose_field, select_row, values_disagree
from fr24.region_parse import (
    ALLOWED_REVIEW_STATUSES,
    PARSER_VERSION,
    parse_region_record,
)

__all__ = [
    "PARSER_VERSION",
    "FIELD_SELECT_VERSION",
    "ALLOWED_REVIEW_STATUSES",
    "parse_region_record",
    "select_row",
    "choose_field",
    "values_disagree",
    "parse_telemetry",
    "coordinate_from_pixel",
    "CoordResult",
]


def parse_telemetry(record: dict) -> dict:
    """Parse telemetry fields from a region OCR record.

    Direct alias of :func:`fr24.region_parse.parse_region_record`, surfaced here
    as the canonical telemetry entry point.
    """
    return parse_region_record(record)


def __getattr__(name: str) -> Any:  # PEP 562 lazy attribute
    # ``CoordResult`` is re-exported lazily (its real home is
    # ``integration.geo_calibration.CoordResult``) so importing this module does
    # not pull in numpy. No placeholder class is defined for the name, otherwise
    # module __getattr__ would never fire for it.
    if name == "CoordResult":
        from integration.geo_calibration import CoordResult as _CoordResult  # noqa: WPS433

        return _CoordResult
    raise AttributeError(name)


def coordinate_from_pixel(
    pixel_x: float,
    pixel_y: float,
    image_width: int,
    image_height: int,
    *,
    calibration: Optional[object] = None,
) -> "Any":
    """Resolve a pixel coordinate to lat/lon with method + confidence.

    Delegates to ``integration.geo_calibration.GeoCalibration`` (lazy import).
    Returns a ``CoordResult`` carrying ``coordinate_method`` and
    ``coordinate_confidence`` so downstream persistence records provenance.
    """
    from integration.geo_calibration import GeoCalibration  # noqa: WPS433

    calib = calibration or GeoCalibration()
    return calib.pixel_to_coord(pixel_x, pixel_y, image_width, image_height)
