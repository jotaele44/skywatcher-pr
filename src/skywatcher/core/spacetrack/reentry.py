"""Reentry assertion and event materialization.

DECAY and TIP records are preserved as temporal assertions. A canonical decay
date is only derived from historical stages and never from a prediction.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from typing import Any, Iterable

from .contradictions import ContradictionRegister
from .control_plane import logical_json_sha256
from .models import ReentryEventView, TemporalAssertion
from .storage import SpaceTrackStore


def _text(value: Any) -> str | None:
    if value is None:
        return None
    rendered = str(value)
    return rendered if rendered else None


def _date_part(value: str | None) -> str | None:
    if value is None or len(value) < 10:
        return None
    return value[:10]


def build_reentry_assertions(
    decay_rows: Iterable[dict[str, Any]],
    tip_rows: Iterable[dict[str, Any]],
) -> tuple[TemporalAssertion, ...]:
    assertions: dict[str, TemporalAssertion] = {}

    for row in decay_rows:
        norad = _text(row.get("norad_cat_id"))
        if norad is None:
            continue
        logical = {
            "class": "decay",
            "norad_cat_id": norad,
            "row": row,
        }
        assertion_id = logical_json_sha256(logical)
        assertions.setdefault(
            assertion_id,
            TemporalAssertion(
                assertion_id=assertion_id,
                catalog_key=f"space-track:norad:{norad}",
                norad_cat_id=norad,
                source_id="decay",
                assertion_type=_text(row.get("decay_stage")) or "UNRESOLVED",
                role=_text(row.get("assertion_role")) or "UNRESOLVED",
                message_epoch=_text(row.get("message_epoch")),
                effective_epoch=_text(row.get("decay_epoch")),
                raw=dict(row),
            ),
        )

    for row in tip_rows:
        norad = _text(row.get("norad_cat_id"))
        if norad is None:
            continue
        logical = {
            "class": "tip",
            "norad_cat_id": norad,
            "row": row,
        }
        assertion_id = logical_json_sha256(logical)
        assertions.setdefault(
            assertion_id,
            TemporalAssertion(
                assertion_id=assertion_id,
                catalog_key=f"space-track:norad:{norad}",
                norad_cat_id=norad,
                source_id="tip",
                assertion_type="TIP_PREDICTION",
                role="PREDICTION",
                message_epoch=_text(row.get("message_epoch")),
                effective_epoch=_text(row.get("predicted_decay_epoch")),
                raw=dict(row),
            ),
        )

    return tuple(
        sorted(
            assertions.values(),
            key=lambda item: (
                item.norad_cat_id,
                item.message_epoch or "",
                item.assertion_id,
            ),
        )
    )


def materialize_reentry_events(
    decay_rows: Iterable[dict[str, Any]],
    tip_rows: Iterable[dict[str, Any]],
) -> tuple[tuple[ReentryEventView, ...], tuple]:
    assertions = build_reentry_assertions(decay_rows, tip_rows)
    by_norad: dict[str, list[TemporalAssertion]] = defaultdict(list)
    for assertion in assertions:
        by_norad[assertion.norad_cat_id].append(assertion)

    register = ContradictionRegister()
    events: list[ReentryEventView] = []

    for norad in sorted(by_norad, key=lambda value: (len(value), value)):
        rows = by_norad[norad]
        satcat = [
            row
            for row in rows
            if row.role == "HISTORICAL"
            and row.assertion_type == "SATCAT_CURRENT_DECAY"
        ]
        historical = satcat or [
            row
            for row in rows
            if row.role == "HISTORICAL"
            and row.assertion_type == "DECAY_ANNOUNCEMENT"
        ]

        dates = {
            value
            for row in historical
            if (value := _date_part(row.effective_epoch)) is not None
        }
        contradiction_ids: list[str] = []
        canonical: str | None = None
        precision: str | None = None

        if len(dates) == 1:
            canonical = next(iter(dates))
            precision = "DATE"
        elif len(dates) > 1:
            contradiction = register.add(
                "TIME",
                f"REENTRY_DATE:{norad}",
                dates,
            )
            contradiction_ids.append(contradiction.contradiction_id)

        events.append(
            ReentryEventView(
                catalog_key=f"space-track:norad:{norad}",
                norad_cat_id=norad,
                canonical_decay_date=canonical,
                temporal_precision=precision,
                assertions=tuple(rows),
                contradictions=tuple(contradiction_ids),
            )
        )

    return tuple(events), register.all()


def materialize_stored_reentry_events(
    store: SpaceTrackStore,
) -> tuple[tuple[ReentryEventView, ...], str]:
    decay_rows = [
        row
        for source_id in ("decay", "decay_60day")
        for batch in store.load_normalized_batches(source_id)
        for row in batch.rows
    ]
    tip_rows = [
        row
        for batch in store.load_normalized_batches("tip")
        for row in batch.rows
    ]
    events, contradictions = materialize_reentry_events(decay_rows, tip_rows)
    payload = {
        "events": [asdict(event) for event in events],
        "contradictions": [asdict(item) for item in contradictions],
    }
    _, digest = store.freeze_materialization("reentry_events", payload)
    return events, digest
