"""Native, dependency-free GeoJSON → KML export (T7-58).

KML is plain XML, so we emit it directly rather than depending on ``simplekml``
or shelling out to ``ogr2ogr`` (which the GIS guide previously recommended —
now deprecated, T7-63). Supports the two geometry types the airspace bridges
produce: ``Point`` and ``LineString``. Feature ``properties`` are written as
``<ExtendedData>`` so attributes survive the round-trip into Google Earth/QGIS.

KML coordinates are ``lon,lat[,alt]`` — the same axis order as GeoJSON, so no
reprojection is needed (everything is EPSG:4326).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple
from xml.sax.saxutils import escape

# Property keys skipped from ExtendedData (nested/structural, not flat scalars).
_SKIP_PROPS = {"_meta"}


def _coord(pt: List[float]) -> str:
    lon, lat = pt[0], pt[1]
    return f"{lon},{lat}"


def _placemark(feature: Dict[str, Any]) -> str:
    geom = feature.get("geometry") or {}
    gtype = geom.get("type")
    coords = geom.get("coordinates")
    props = feature.get("properties") or {}

    if gtype == "Point" and isinstance(coords, (list, tuple)) and len(coords) >= 2:
        geom_xml = f"<Point><coordinates>{_coord(coords)}</coordinates></Point>"
    elif gtype == "LineString" and isinstance(coords, (list, tuple)) and coords:
        line = " ".join(_coord(p) for p in coords if len(p) >= 2)
        geom_xml = f"<LineString><coordinates>{line}</coordinates></LineString>"
    else:
        return ""  # unsupported geometry — skip rather than emit invalid KML

    # A human-readable name: prefer an explicit name/label-ish property.
    name = ""
    for key in ("name", "feature_id", "flight_id", "review_priority", "corridor_label"):
        if props.get(key):
            name = str(props[key])
            break

    data_rows = []
    for k, v in props.items():
        if k in _SKIP_PROPS or isinstance(v, (dict, list)):
            continue
        data_rows.append(
            f'<Data name="{escape(str(k))}">'
            f"<value>{escape(str(v))}</value></Data>"
        )
    extended = f"<ExtendedData>{''.join(data_rows)}</ExtendedData>" if data_rows else ""
    name_xml = f"<name>{escape(name)}</name>" if name else ""
    return f"<Placemark>{name_xml}{extended}{geom_xml}</Placemark>"


def feature_collection_to_kml(geojson: Dict[str, Any], document_name: str) -> str:
    """Serialize a GeoJSON FeatureCollection dict to a KML document string."""
    placemarks = [
        pm for pm in (_placemark(f) for f in geojson.get("features", [])) if pm
    ]
    body = "".join(placemarks)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<kml xmlns="http://www.opengis.net/kml/2.2">'
        f"<Document><name>{escape(document_name)}</name>{body}</Document></kml>"
    )


def write_kml_for_geojson(geojson: Dict[str, Any], kml_path: Path) -> Tuple[str, int]:
    """Write a ``.kml`` next to a GeoJSON dict. Returns (path, placemark_count)."""
    n = sum(
        1
        for f in geojson.get("features", [])
        if (f.get("geometry") or {}).get("type") in ("Point", "LineString")
    )
    kml_path.write_text(
        feature_collection_to_kml(geojson, kml_path.stem), encoding="utf-8"
    )
    return str(kml_path), n
