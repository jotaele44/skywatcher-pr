"""Fail-closed provenance, cadence, schema, and archive controls."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from collections import Counter, deque
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from .contracts import SourceContract, get_source_contract
from .models import (
    ArchiveMember,
    ArchiveSnapshot,
    CapabilityObservation,
    CapabilityState,
    DistributionClass,
    Manifestation,
    SchemaSnapshot,
    SourceArithmetic,
    Watermark,
)


def logical_json_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def raw_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def classify_decay_stage(precedence: int | str | None) -> str:
    mapping = {
        4: "SIXTY_DAY_PREDICTION",
        3: "TIP_PREDICTION",
        2: "DECAY_ANNOUNCEMENT",
        1: "SATCAT_CURRENT_DECAY",
    }
    try:
        key = int(precedence) if precedence is not None else None
    except (TypeError, ValueError):
        return "UNRESOLVED"
    return mapping.get(key, "UNRESOLVED")


def source_arithmetic(
    source_count: int,
    retained_count: int,
    excluded_count: int,
) -> SourceArithmetic:
    arithmetic = SourceArithmetic(source_count, retained_count, excluded_count)
    if not arithmetic.closes:
        raise ValueError(
            "source arithmetic does not close: "
            f"{source_count} != {retained_count} + {excluded_count}"
        )
    return arithmetic


def archive_snapshot(payload: bytes) -> ArchiveSnapshot:
    outer = raw_sha256(payload)
    members: list[ArchiveMember] = []
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for info in sorted(archive.infolist(), key=lambda row: row.filename):
            if info.is_dir():
                continue
            member = archive.read(info.filename)
            members.append(
                ArchiveMember(
                    path=info.filename,
                    uncompressed_size=len(member),
                    sha256=raw_sha256(member),
                )
            )
    return ArchiveSnapshot(outer_sha256=outer, members=tuple(members))


def classify_archive_equivalence(left: ArchiveSnapshot, right: ArchiveSnapshot) -> str:
    if left.outer_sha256 == right.outer_sha256:
        return "BYTE_IDENTICAL"

    left_by_path = tuple((m.path, m.uncompressed_size, m.sha256) for m in left.members)
    right_by_path = tuple((m.path, m.uncompressed_size, m.sha256) for m in right.members)
    if left_by_path == right_by_path:
        return "PURE_RECOMPRESSION"

    left_payloads = Counter((m.uncompressed_size, m.sha256) for m in left.members)
    right_payloads = Counter((m.uncompressed_size, m.sha256) for m in right.members)
    if left_payloads == right_payloads:
        return "SAME_PAYLOADS_DIFFERENT_PATHS"

    return "DISTINCT_PAYLOADS"


def schema_snapshot(source_id: str, modeldef: Any, retrieved_utc: str) -> SchemaSnapshot:
    fields: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key.lower() in {"field", "name", "predicate", "column"} and isinstance(
                    child, str
                ):
                    fields.add(child)
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(modeldef)
    return SchemaSnapshot(
        source_id=source_id,
        retrieved_utc=retrieved_utc,
        canonical_sha256=logical_json_sha256(modeldef),
        fields=tuple(sorted(fields)),
    )


class RateGate:
    """Deterministic request admission; never sleeps or performs I/O."""

    GLOBAL_PER_MINUTE = 29
    GLOBAL_PER_HOUR = 299

    def __init__(self) -> None:
        self._global: deque[datetime] = deque()
        self._by_source: dict[str, deque[datetime]] = {}

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("request timestamps must be timezone-aware")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _trim(queue: deque[datetime], threshold: datetime) -> None:
        while queue and queue[0] <= threshold:
            queue.popleft()

    def can_global(self, now: datetime) -> tuple[bool, str | None]:
        current = self._utc(now)
        self._trim(self._global, current - timedelta(hours=1))
        recent_minute = sum(ts > current - timedelta(minutes=1) for ts in self._global)
        if recent_minute >= self.GLOBAL_PER_MINUTE:
            return False, "GLOBAL_PER_MINUTE"
        if len(self._global) >= self.GLOBAL_PER_HOUR:
            return False, "GLOBAL_PER_HOUR"
        return True, None

    def can_request(self, source_id: str, now: datetime) -> tuple[bool, str | None]:
        current = self._utc(now)
        allowed, reason = self.can_global(current)
        if not allowed:
            return False, reason

        contract = get_source_contract(source_id)
        history = self._by_source.setdefault(source_id, deque())
        if contract.one_time_only and history:
            return False, "ONE_TIME_ONLY"
        if contract.max_requests_per_hour is None:
            return True, None

        self._trim(history, current - timedelta(days=8))
        if history:
            minimum_interval = timedelta(hours=1 / contract.max_requests_per_hour)
            if current - history[-1] < minimum_interval:
                return False, "SOURCE_CADENCE"
        return True, None

    def record_global(self, now: datetime) -> None:
        allowed, reason = self.can_global(now)
        if not allowed:
            raise RuntimeError(f"Space-Track request blocked: {reason}")
        self._global.append(self._utc(now))

    def record(self, source_id: str, now: datetime) -> None:
        allowed, reason = self.can_request(source_id, now)
        if not allowed:
            raise RuntimeError(f"Space-Track request blocked: {reason}")
        current = self._utc(now)
        self._global.append(current)
        self._by_source.setdefault(source_id, deque()).append(current)


class SpaceTrackControlPlane:
    """In-memory state machine for acquisition/runtime adapters."""

    def __init__(self) -> None:
        self.rate_gate = RateGate()
        self.capabilities: dict[str, CapabilityObservation] = {}
        self.schemas: dict[str, SchemaSnapshot] = {}
        self.schema_promotion: dict[str, bool] = {}
        self.watermarks: dict[str, Watermark] = {}
        self.manifestations: list[Manifestation] = []

    def record_capability(self, observation: CapabilityObservation) -> None:
        self.capabilities[observation.controller] = observation

    def capability_state(self, controller: str) -> CapabilityState:
        observation = self.capabilities.get(controller)
        return observation.state if observation else CapabilityState.UNVERIFIED

    def register_schema(self, snapshot: SchemaSnapshot) -> bool:
        previous = self.schemas.get(snapshot.source_id)
        unchanged = previous is None or previous.canonical_sha256 == snapshot.canonical_sha256
        self.schemas[snapshot.source_id] = snapshot
        self.schema_promotion[snapshot.source_id] = unchanged
        return unchanged

    def schema_promotion_allowed(self, source_id: str) -> bool:
        return self.schema_promotion.get(source_id, False)

    def set_watermark(self, watermark: Watermark) -> None:
        self.watermarks[watermark.source_id] = watermark

    def get_watermark(self, source_id: str) -> Watermark | None:
        return self.watermarks.get(source_id)

    def freeze_manifestation(
        self,
        *,
        source_id: str,
        query: str,
        retrieved_utc: str,
        raw_bytes: bytes,
        row_count: int | None,
        schema_sha256: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> Manifestation:
        contract: SourceContract = get_source_contract(source_id)
        manifestation = Manifestation(
            source_id=source_id,
            controller=contract.controller,
            query=query,
            retrieved_utc=retrieved_utc,
            raw_sha256=raw_sha256(raw_bytes),
            byte_count=len(raw_bytes),
            row_count=row_count,
            schema_sha256=schema_sha256,
            distribution_class=contract.distribution_class,
            metadata=dict(metadata or {}),
        )
        self.manifestations.append(manifestation)
        return manifestation

    def assert_redistributable(self, manifestation: Manifestation) -> None:
        blocked = {
            DistributionClass.UNKNOWN,
            DistributionClass.ACCOUNT_ONLY,
            DistributionClass.ODR_CONTROLLED,
            DistributionClass.SSA_AGREEMENT_CONTROLLED,
        }
        if manifestation.distribution_class in blocked:
            raise PermissionError(
                "manifestation is not cleared for redistribution: "
                f"{manifestation.distribution_class.value}"
            )

    def report(self) -> dict[str, Any]:
        return {
            "capabilities": {
                key: asdict(value) for key, value in sorted(self.capabilities.items())
            },
            "schemas": {
                key: asdict(value) for key, value in sorted(self.schemas.items())
            },
            "schema_promotion": dict(sorted(self.schema_promotion.items())),
            "watermarks": {
                key: asdict(value) for key, value in sorted(self.watermarks.items())
            },
            "manifestation_count": len(self.manifestations),
        }


def distinct_ids(rows: Iterable[dict[str, Any]], field: str) -> set[str]:
    values: set[str] = set()
    for row in rows:
        value = row.get(field)
        if value is not None and str(value).strip():
            values.add(str(value))
    return values


def set_comparison(
    left_rows: Iterable[dict[str, Any]],
    right_rows: Iterable[dict[str, Any]],
    *,
    field: str = "NORAD_CAT_ID",
) -> dict[str, set[str]]:
    left = distinct_ids(left_rows, field)
    right = distinct_ids(right_rows, field)
    return {
        "intersection": left & right,
        "a_only": left - right,
        "b_only": right - left,
        "union": left | right,
        "symmetric_difference": left ^ right,
    }
