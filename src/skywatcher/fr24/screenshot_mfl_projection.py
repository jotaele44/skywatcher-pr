"""Pure, review-only projection of screenshot observations toward MFL v1.

This is not a producer of master-flight-log-backup HTML and must never be passed
to persist_corpus_snapshot as an authoritative flight record.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

MFL_FIELDS = (
    "sourceFlightIdRaw",
    "callsignRaw",
    "pointCount",
    "startTimeUtc",
    "endTimeUtc",
    "start",
    "end",
    "sourceManifestations",
    "metrics.maxAltitudeFt",
    "metrics.maxSpeedKt",
    "metrics.trackDistanceKm",
    "metrics.prAreaPointPct",
    "metrics.maxGapSeconds",
    "metrics.gapCounts",
    "kmlEnrichment.routeRaw",
)


def project_screenshot_fields(
    fields: Mapping[str, Any],
    contradictions: list[dict],
    candidates: list[dict],
    *,
    screenshot_sha256: str | None,
) -> dict[str, Any]:
    """Return complete scoped mapping without promoting screenshot readings.

    A screenshot can display a source flight ID and callsign, but a candidate
    text extraction does not establish the original FR24 event or valid temporal
    identity. Other MFL values need native data or corroborated source records.
    """
    conflict_fields = {
        c.get("field")
        for c in contradictions
        if c.get("status") == "UNRESOLVED" and c.get("field")
    }
    # Backward-compatible fail-closed handling for legacy identity contradictions
    # that predate field-scoped receipts.
    if any(
        c.get("class") == "IDENTITY"
        and c.get("status") == "UNRESOLVED"
        and not c.get("field")
        for c in contradictions
    ):
        conflict_fields.update({"callsign", "source_flight_id_displayed"})

    proposed = {}
    eligible = {
        "callsignRaw": "callsign",
        "sourceFlightIdRaw": "source_flight_id_displayed",
    }
    for mfl_key, observation_key in eligible.items():
        item = fields.get(observation_key)
        if not isinstance(item, Mapping) or observation_key in conflict_fields:
            continue
        value = item.get("value")
        if not isinstance(value, str) or not value.strip():
            continue
        proposed[mfl_key] = {
            "value_raw": value,
            "evidence_state": "INFERENCE",
            "certification": "CANDIDATE_NOT_IDENTITY",
            "source_ocr_ids": list(item.get("source_ocr_ids") or []),
            "requires": "authoritative source-id/temporal binding before corpus amendment",
        }

    withheld_reasons = {
        "sourceFlightIdRaw": "source flight ID not visibly extracted and independently bound",
        "callsignRaw": "no conflict-free displayed callsign",
        "pointCount": "native timestamped trajectory required",
        "startTimeUtc": "native or independently corroborated source time required",
        "endTimeUtc": "native or independently corroborated source time required",
        "start": "certified source endpoint geometry required",
        "end": "certified source endpoint geometry required",
        "sourceManifestations": "native CSV/KML manifestations must be inventoried, not inferred from pixels",
        "metrics.maxAltitudeFt": "complete native flight altitude series required",
        "metrics.maxSpeedKt": "complete native flight speed series required",
        "metrics.trackDistanceKm": "validated trajectory and CRS/geodesy required",
        "metrics.prAreaPointPct": "validated trajectory and authoritative region geometry required",
        "metrics.maxGapSeconds": "complete timestamped series required",
        "metrics.gapCounts": "complete timestamped series required",
        "kmlEnrichment.routeRaw": "native KML source or independently corroborated route evidence required",
    }
    withheld = {key: reason for key, reason in withheld_reasons.items() if key not in proposed}
    assert len(proposed) + len(withheld) == len(MFL_FIELDS)
    return {
        "schema_version": "skywatcher.screenshot.mfl_projection.v1",
        "target_format": "master-flight-log-backup",
        "target_version": 1,
        "scope": "PROVISIONAL_SCREENSHOT_EVIDENCE",
        "screenshot_sha256": screenshot_sha256,
        "proposed_fields": proposed,
        "withheld_fields": withheld,
        "proposed_count": len(proposed),
        "withheld_count": len(withheld),
        "candidate_count": len(candidates),
        "candidate_relation": "CANDIDATE_NOT_IDENTITY",
        "canonical_append_authorized": False,
        "certification": "NONCANONICAL",
        "unresolved_contradictions": list(contradictions),
    }
