"""Versioned, read-only GloTEC producer for regional model context.

No geographic identity, alerts, receiver-level ROTI, or operational readiness is
established. Existing v0.1 observation adapters and their schema stay immutable.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import replace
from datetime import datetime, timezone

from .pitirre_observation import ObservationAdapterError, _envelope

BBOX = (-70, 16, -60, 22)
NODES = {(float(-177.5 + x * 5), float(-88.75 + y * 2.5)) for x in range(72) for y in range(72)}
SOURCE_PREFIX = "https://services.swpc.noaa.gov/products/glotec/geojson_2d_urt/"


def canonical_bytes(value: dict) -> bytes:
    """Explicit package serialization; logical checksums use this convention only."""
    return (
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
        + "\n"
    ).encode("utf-8")


def build_glotec_package(raw: bytes, source_url: str, retrieved_utc: str) -> dict:
    """Project an inspected complete GloTEC grid into six context-only envelopes.

    Row identity is an immutable source manifestation plus positional index; it
    never identifies a physical station, asset, municipality, or grid polygon.
    """
    value = json.loads(raw.decode("utf-8"))
    epoch = value.get("time_tag")
    try:
        observed = datetime.fromisoformat(epoch.replace("Z", "+00:00"))
        retrieved = datetime.fromisoformat(retrieved_utc.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ObservationAdapterError("invalid source timestamp") from exc
    if observed.tzinfo is None or retrieved.tzinfo is None or observed > retrieved:
        raise ObservationAdapterError("invalid source temporal ordering")
    import re

    if not re.fullmatch(
        re.escape(SOURCE_PREFIX) + r"glotec_icao_\d{8}T\d{6}Z\.geojson", source_url
    ):
        raise ObservationAdapterError("unbound GloTEC source URL")
    expected_url = SOURCE_PREFIX + observed.astimezone(timezone.utc).strftime(
        "glotec_icao_%Y%m%dT%H%M%SZ.geojson"
    )
    if source_url != expected_url:
        raise ObservationAdapterError("source filename and epoch disagree")
    if (
        value.get("type") != "FeatureCollection"
        or value.get("product") != "GloTEC Total Electron Content"
    ):
        raise ObservationAdapterError("unexpected source product")
    if value.get("metadata", {}).get("variables", {}).get("tec", {}).get("units") != "TECU":
        raise ObservationAdapterError("TEC units changed")
    features = value.get("features")
    if not isinstance(features, list):
        raise ObservationAdapterError("missing feature list")
    raw_sha = hashlib.sha256(raw).hexdigest()
    nodes = set()
    records = []
    for index, feature in enumerate(features):
        geometry = feature.get("geometry") if isinstance(feature, dict) else None
        if (
            not isinstance(geometry, dict)
            or geometry.get("type") != "Point"
            or feature.get("type") != "Feature"
        ):
            raise ObservationAdapterError("expected source Point feature")
        coords = geometry.get("coordinates")
        if (
            not isinstance(coords, list)
            or len(coords) != 2
            or any(type(n) not in {int, float} or not math.isfinite(n) for n in coords)
        ):
            raise ObservationAdapterError("invalid source coordinates")
        pair = tuple(coords)
        if pair in nodes:
            raise ObservationAdapterError("duplicate source node")
        nodes.add(pair)
        p = feature.get("properties")
        if not isinstance(p, dict) or set(p) != {"tec", "anomaly", "hmF2", "NmF2", "quality_flag"}:
            raise ObservationAdapterError("property schema changed")
        tec, flag = p["tec"], p["quality_flag"]
        if tec is not None and (
            type(tec) not in {int, float} or not math.isfinite(tec) or not 0 <= tec <= 300
        ):
            raise ObservationAdapterError("invalid TEC value")
        if type(flag) is not int or not 0 <= flag <= 5:
            raise ObservationAdapterError("unknown quality flag")
        lon, lat = coords
        if not BBOX[0] <= lon <= BBOX[2] or not BBOX[1] <= lat <= BBOX[3]:
            continue
        payload = {
            "raw_feature": feature,
            "kind": "MODEL",
            "source_manifest": {
                "url": source_url,
                "sha256": raw_sha,
                "row_index": index,
                "observed_at": epoch,
                "retrieved_at": retrieved_utc,
            },
        }
        observation = _envelope(
            row=payload,
            observation_id=f"glotec:{raw_sha}:{index}",
            domain="SPACE",
            subdomain="SPACE_WEATHER",
            event_time_raw=epoch,
            source_ref={
                "source_id": "noaa:glotec",
                "source_type_raw": value["product"],
                "source_record_id": index,
                "lineage_id": raw_sha,
            },
            spatial={
                "mode": "SOURCE_POINT",
                "lat": lat,
                "lon": lon,
                "geometry_status_raw": "MODEL_GRID_NODE",
            },
            evidence={
                "evidence_tier_raw": None,
                "confidence_raw": None,
                "synthetic": False,
                "operational_use_allowed": False,
            },
            legacy_contract="glotec_model",
        )
        observation = replace(
            observation,
            schema_version="pitirre-observation-v0.2",
            adapter={
                "adapter_version": "pitirre-observation-adapter-v0.2",
                "legacy_contract": "glotec_model",
            },
        )
        records.append(observation.to_dict())
    if nodes != NODES or len(features) != len(NODES):
        raise ObservationAdapterError("incomplete or unexpected complete-grid coordinates")
    return {
        "schema_version": "pitirre-glotec-package-v1",
        "producer_repository_id": 1261399537,
        "source_sha256": raw_sha,
        "source_count": len(features),
        "retained_count": len(records),
        "excluded_count": len(features) - len(records),
        "selection": {"bbox": list(BBOX), "role": "DISCOVERY_CONTEXT_ONLY"},
        "operational_use_allowed": False,
        "records": records,
    }
