"""Lossless PITIRRE projection of existing normalized Space-Track GP rows.

The adapter references the frozen batch; it neither collects upstream data nor
resolves catalog candidates. Source epochs and retrieval epochs stay separate.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from skywatcher.core.pitirre_observation import (
    ObservationAdapterError,
    PitirreObservation,
    _envelope,
)

from .models import NormalizedBatch


def adapt_gp_batch_row(batch: NormalizedBatch, row_index: int) -> PitirreObservation:
    """Project one explicitly selected source row as SPACE.ORBITAL."""
    if batch.source_id not in {"gp", "gp_history"}:
        raise ObservationAdapterError("only GP orbital contracts are supported")
    if isinstance(row_index, bool) or not isinstance(row_index, int) or not 0 <= row_index < len(batch.rows):
        raise ObservationAdapterError("row_index must identify an existing whole row")
    if len(batch.raw_sha256) != 64 or any(c not in "0123456789abcdef" for c in batch.raw_sha256):
        raise ObservationAdapterError("frozen raw SHA256 is required")
    row = batch.rows[row_index]
    raw = row.get("raw")
    if not isinstance(raw, dict):
        raise ObservationAdapterError("complete raw row is required")
    catalog = raw.get("NORAD_CAT_ID")
    if isinstance(catalog, bool) or not isinstance(catalog, (str, int)):
        raise ObservationAdapterError("authoritative NORAD catalog ID is required")
    catalog_text = str(catalog)
    if not catalog_text.isascii() or not catalog_text.isdigit() or row.get("norad_cat_id") != catalog_text:
        raise ObservationAdapterError("raw and normalized catalog identifiers must agree exactly")
    epoch = raw.get("EPOCH")
    if not isinstance(epoch, str) or not epoch or row.get("epoch") != epoch:
        raise ObservationAdapterError("raw and normalized source epochs must agree exactly")
    payload: dict[str, Any] = {
        "source_manifestation": {
            "source_id": batch.source_id,
            "retrieved_utc": batch.retrieved_utc,
            "query": batch.query,
            "raw_sha256": batch.raw_sha256,
            "schema_sha256": batch.schema_sha256,
            "row_index": row_index,
        },
        "row": deepcopy(row),
    }
    return _envelope(
        row=payload,
        observation_id=f"space-track:{batch.source_id}:{batch.raw_sha256}:{row_index}",
        domain="SPACE", subdomain="ORBITAL", event_time_raw=epoch,
        source_ref={"source_id": f"space-track:{batch.source_id}", "source_type_raw": batch.source_id,
                    "source_record_id": raw.get("GP_ID"), "lineage_id": "space-track"},
        spatial={"mode": "NONE", "lat": None, "lon": None, "geometry_status_raw": None},
        evidence={"evidence_tier_raw": None, "confidence_raw": None,
                  "synthetic": None, "operational_use_allowed": None},
        legacy_contract="spacetrack_normalized_gp",
    )
