"""Deterministic Space-Track REST query construction.

This module constructs URLs only. It performs no authentication, network I/O,
or retries; runtime transports belong outside the canonical evidence model.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from urllib.parse import quote

from .contracts import get_source_contract
from .models import Watermark

_BASE_URL = "https://www.space-track.org"
_CURATED_FAVORITES = {"Navigation", "Special_Interest", "Visible", "Weather"}


def _segment(value: object) -> str:
    return quote(str(value), safe=",~-^")


@dataclass(frozen=True)
class SpaceTrackQuery:
    controller: str
    api_class: str
    filters: tuple[tuple[str, str], ...] = ()
    order_by: tuple[str, ...] = ()
    predicates: tuple[str, ...] = ()
    format: str = "json"
    metadata: bool = False
    emptyresult_show: bool = True
    limit: int | None = None
    path_override: str | None = None

    def with_filter(self, predicate: str, value: object) -> SpaceTrackQuery:
        return replace(self, filters=(*self.filters, (predicate, str(value))))

    def with_order(self, *terms: str) -> SpaceTrackQuery:
        return replace(self, order_by=tuple(terms))

    def with_predicates(self, *predicates: str) -> SpaceTrackQuery:
        return replace(self, predicates=tuple(predicates))

    def to_path(self) -> str:
        if self.path_override is not None:
            return self.path_override

        parts = [self.controller, "query", "class", self.api_class]
        for predicate, value in self.filters:
            parts.extend((_segment(predicate), _segment(value)))
        if self.order_by:
            parts.extend(("orderby", _segment(",".join(self.order_by))))
        if self.predicates:
            parts.extend(("predicates", _segment(",".join(self.predicates))))
        if self.metadata:
            parts.extend(("metadata", "true"))
        if self.limit is not None:
            if self.limit <= 0:
                raise ValueError("limit must be positive")
            parts.extend(("limit", str(self.limit)))
        if self.format:
            parts.extend(("format", _segment(self.format)))
        if self.emptyresult_show:
            parts.extend(("emptyresult", "show"))
        return "/" + "/".join(parts)

    def to_url(self) -> str:
        return _BASE_URL + self.to_path()


def build_incremental_query(
    source_id: str,
    watermark: Watermark | None = None,
    *,
    output_format: str = "json",
) -> SpaceTrackQuery:
    contract = get_source_contract(source_id)

    if source_id == "publicfiles":
        return SpaceTrackQuery(
            controller=contract.controller,
            api_class=contract.api_class,
            format="",
            emptyresult_show=False,
            path_override="/publicfiles/query/class/loadpublicdata",
        )

    if source_id == "publicfile_download":
        raise ValueError("use build_publicfile_download_url() for named public-file downloads")

    if source_id == "curated_favorites":
        raise ValueError("use build_curated_favorites_query() with an explicit collection")

    query = SpaceTrackQuery(
        controller=contract.controller,
        api_class=contract.api_class,
        format=output_format,
    )

    if source_id == "gp":
        query = query.with_filter("DECAY_DATE", "null-val")
        if watermark is None:
            return query.with_filter("EPOCH", ">now-10").with_order("GP_ID asc")
        return query.with_filter(
            "CREATION_DATE", f">{watermark.value}"
        ).with_order("GP_ID asc")

    if source_id == "satcat" and watermark is not None:
        return query.with_filter("FILE", f">{watermark.value}").with_order("FILE asc")

    if source_id == "satcat_debut":
        value = f">{watermark.value}" if watermark else ">now-1"
        return query.with_filter("DEBUT", value).with_order("DEBUT asc")

    if source_id == "decay":
        value = f">{watermark.value}" if watermark else ">now-1"
        return query.with_filter("MSG_EPOCH", value).with_order(
            "NORAD_CAT_ID asc", "PRECEDENCE asc", "MSG_EPOCH asc"
        )

    if source_id == "decay_60day":
        return (
            query.with_filter("SOURCE", "60day_msg")
            .with_filter("DECAY_EPOCH", "now--now+60")
            .with_order("NORAD_CAT_ID asc", "MSG_EPOCH asc")
        )

    if source_id == "tip":
        value = f">{watermark.value}" if watermark else ">now-0.042"
        return query.with_filter("INSERT_EPOCH", value).with_order("INSERT_EPOCH asc")

    if source_id == "cdm_public":
        value = f">{watermark.value}" if watermark else ">now-0.334"
        return query.with_filter("CREATED", value).with_order("CREATED asc")

    return query


def build_curated_favorites_query(
    collection: str,
    *,
    output_format: str = "json",
) -> SpaceTrackQuery:
    if collection not in _CURATED_FAVORITES:
        allowed = ", ".join(sorted(_CURATED_FAVORITES))
        raise ValueError(f"unknown curated favorites collection {collection!r}; expected {allowed}")
    return (
        SpaceTrackQuery(
            controller="basicspacedata",
            api_class="gp",
            format=output_format,
        )
        .with_filter("favorites", collection)
        .with_filter("EPOCH", ">now-10")
        .with_order("GP_ID asc")
    )


def build_publicfile_download_url(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("public-file name is required")
    return f"{_BASE_URL}/publicfiles/query/class/download?name={quote(cleaned, safe='')}"
