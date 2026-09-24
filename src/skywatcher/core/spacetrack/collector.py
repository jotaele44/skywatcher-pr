"""Restartable read-only Space-Track acquisition orchestration."""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .adapters import normalize_rows
from .contracts import get_source_contract
from .control_plane import (
    SpaceTrackControlPlane,
    archive_snapshot,
    schema_snapshot,
    source_arithmetic,
)
from .models import (
    ArchiveSnapshot,
    CapabilityObservation,
    CapabilityState,
    CertificationState,
    Manifestation,
    Watermark,
)
from .query import (
    SpaceTrackQuery,
    build_incremental_query,
    build_publicfile_download_url,
)
from .storage import SpaceTrackStore
from .transport import ReadOnlyTransport


@dataclass(frozen=True)
class CollectionResult:
    source_id: str
    state: CertificationState
    manifestation: Manifestation | None
    rows: tuple[dict[str, Any], ...]
    normalized_rows: tuple[dict[str, Any], ...]
    blocker: str | None = None


@dataclass(frozen=True)
class DownloadResult:
    source_id: str
    state: CertificationState
    manifestation: Manifestation | None
    archive: ArchiveSnapshot | None
    blocker: str | None = None


class SpaceTrackCollector:
    """Acquires raw bytes first, then conditionally promotes normalized rows."""

    def __init__(
        self,
        *,
        transport: ReadOnlyTransport,
        store: SpaceTrackStore,
        control_plane: SpaceTrackControlPlane | None = None,
    ) -> None:
        self.transport = transport
        self.store = store
        self.control_plane = control_plane or SpaceTrackControlPlane()

    @staticmethod
    def _iso_utc(now: datetime) -> str:
        if now.tzinfo is None:
            raise ValueError("collector timestamps must be timezone-aware")
        return now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _rows_from_json(body: bytes) -> list[dict[str, Any]]:
        payload = json.loads(body.decode("utf-8"))
        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict):
            rows = payload.get("data", payload.get("results", [payload]))
        else:
            raise ValueError("Space-Track JSON root must be an object or array")
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ValueError("Space-Track JSON rows must be objects")
        return [dict(row) for row in rows]

    @staticmethod
    def _watermark_from_rows(source_id: str, rows: list[dict[str, Any]]) -> Watermark | None:
        contract = get_source_contract(source_id)
        predicate = contract.incremental_predicate
        if predicate is None:
            return None
        values = [row.get(predicate) for row in rows if row.get(predicate) not in {None, ""}]
        if not values:
            return None
        if predicate == "FILE":
            try:
                value = str(max(int(str(item)) for item in values))
            except ValueError as exc:
                raise ValueError("SATCAT FILE watermark must be an integer") from exc
        else:
            value = max(str(item) for item in values)
        return Watermark(source_id=source_id, predicate=predicate, value=value)

    def _seed_accepted_schema(self, source_id: str) -> None:
        if source_id in self.control_plane.schemas:
            return
        accepted = self.store.load_schema(source_id)
        if accepted is not None:
            self.control_plane.schemas[source_id] = accepted
            self.control_plane.schema_promotion[source_id] = True

    def capture_modeldef(self, source_id: str, *, now: datetime) -> bool:
        contract = get_source_contract(source_id)
        if not contract.schema_required:
            raise ValueError(f"{source_id} does not require a modeldef schema")
        if contract.controller not in {"basicspacedata", "expandedspacedata"}:
            raise ValueError(f"modeldef is not defined for controller {contract.controller}")

        self._seed_accepted_schema(source_id)
        url = (
            "https://www.space-track.org/"
            f"{contract.controller}/modeldef/class/{contract.api_class}"
        )
        self.control_plane.rate_gate.record_global(now)
        response = self.transport.get(url)
        if response.status in {401, 403}:
            self.control_plane.record_capability(
                CapabilityObservation(
                    controller=contract.controller,
                    state=CapabilityState.UNAUTHORIZED,
                    observed_utc=self._iso_utc(now),
                    detail=f"HTTP {response.status}",
                )
            )
            return False
        if response.status != 200:
            raise RuntimeError(f"modeldef request failed with HTTP {response.status}")

        payload = json.loads(response.body.decode("utf-8"))
        snapshot = schema_snapshot(source_id, payload, self._iso_utc(now))
        unchanged = self.control_plane.register_schema(snapshot)
        self.store.save_schema(snapshot, accepted=unchanged)
        self.control_plane.record_capability(
            CapabilityObservation(
                controller=contract.controller,
                state=CapabilityState.AVAILABLE,
                observed_utc=self._iso_utc(now),
            )
        )
        return unchanged

    def collect_json(
        self,
        source_id: str,
        *,
        now: datetime,
        query: SpaceTrackQuery | None = None,
    ) -> CollectionResult:
        contract = get_source_contract(source_id)
        if contract.schema_required:
            self._seed_accepted_schema(source_id)

        watermark = (
            self.control_plane.get_watermark(source_id)
            or self.store.load_watermark(source_id)
        )
        active_query = query or build_incremental_query(source_id, watermark)
        url = active_query.to_url()

        if contract.query_once and self.store.query_seen(source_id, url):
            return CollectionResult(
                source_id=source_id,
                state=CertificationState.AUDIT_ONLY,
                manifestation=None,
                rows=(),
                normalized_rows=(),
                blocker="ALREADY_ACQUIRED",
            )

        self.control_plane.rate_gate.record(source_id, now)
        response = self.transport.get(url)
        observed_utc = self._iso_utc(now)

        if response.status in {401, 403}:
            self.control_plane.record_capability(
                CapabilityObservation(
                    controller=contract.controller,
                    state=CapabilityState.UNAUTHORIZED,
                    observed_utc=observed_utc,
                    detail=f"HTTP {response.status}",
                )
            )
            return CollectionResult(
                source_id=source_id,
                state=CertificationState.BLOCKED,
                manifestation=None,
                rows=(),
                normalized_rows=(),
                blocker="UNAUTHORIZED",
            )

        if response.status == 429:
            return CollectionResult(
                source_id=source_id,
                state=CertificationState.BLOCKED,
                manifestation=None,
                rows=(),
                normalized_rows=(),
                blocker="UPSTREAM_RATE_LIMIT",
            )

        if response.status != 200:
            return CollectionResult(
                source_id=source_id,
                state=CertificationState.OPEN,
                manifestation=None,
                rows=(),
                normalized_rows=(),
                blocker=f"HTTP_{response.status}",
            )

        try:
            rows = self._rows_from_json(response.body)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            manifestation = self.control_plane.freeze_manifestation(
                source_id=source_id,
                query=url,
                retrieved_utc=observed_utc,
                raw_bytes=response.body,
                row_count=None,
                schema_sha256=None,
                metadata={"http_status": response.status, "parse_status": "FAILED"},
            )
            self.store.freeze_raw(manifestation, response.body)
            if contract.query_once:
                self.store.record_query_receipt(manifestation)
            return CollectionResult(
                source_id=source_id,
                state=CertificationState.OPEN,
                manifestation=manifestation,
                rows=(),
                normalized_rows=(),
                blocker="JSON_PARSE_ERROR",
            )

        source_arithmetic(len(rows), len(rows), 0)
        schema = self.control_plane.schemas.get(source_id)
        manifestation = self.control_plane.freeze_manifestation(
            source_id=source_id,
            query=url,
            retrieved_utc=observed_utc,
            raw_bytes=response.body,
            row_count=len(rows),
            schema_sha256=schema.canonical_sha256 if schema else None,
            metadata={"http_status": response.status},
        )
        self.store.freeze_raw(manifestation, response.body)
        if contract.query_once:
            self.store.record_query_receipt(manifestation)

        self.control_plane.record_capability(
            CapabilityObservation(
                controller=contract.controller,
                state=CapabilityState.AVAILABLE if rows else CapabilityState.AUTHORIZED_EMPTY,
                observed_utc=observed_utc,
            )
        )

        if contract.schema_required and not self.control_plane.schema_promotion_allowed(source_id):
            self.store.save_status(self.control_plane.report())
            return CollectionResult(
                source_id=source_id,
                state=CertificationState.PROVISIONAL,
                manifestation=manifestation,
                rows=tuple(rows),
                normalized_rows=(),
                blocker="SCHEMA_UNVERIFIED_OR_DRIFTED",
            )

        normalized = normalize_rows(source_id, rows)
        if len(normalized) != len(rows):
            raise RuntimeError("normalization row conservation failed")

        next_watermark = self._watermark_from_rows(source_id, rows)
        if next_watermark is not None:
            self.control_plane.set_watermark(next_watermark)
            self.store.save_watermark(next_watermark)

        self.store.save_status(self.control_plane.report())
        return CollectionResult(
            source_id=source_id,
            state=CertificationState.PASS,
            manifestation=manifestation,
            rows=tuple(rows),
            normalized_rows=tuple(normalized),
        )

    def download_public_file(self, name: str, *, now: datetime) -> DownloadResult:
        source_id = "publicfile_download"
        contract = get_source_contract(source_id)
        url = build_publicfile_download_url(name)

        if self.store.query_seen(source_id, url):
            return DownloadResult(
                source_id=source_id,
                state=CertificationState.AUDIT_ONLY,
                manifestation=None,
                archive=None,
                blocker="ALREADY_ACQUIRED",
            )

        self.control_plane.rate_gate.record(source_id, now)
        response = self.transport.get(url)
        observed_utc = self._iso_utc(now)

        if response.status in {401, 403}:
            return DownloadResult(
                source_id=source_id,
                state=CertificationState.BLOCKED,
                manifestation=None,
                archive=None,
                blocker="UNAUTHORIZED",
            )
        if response.status == 429:
            return DownloadResult(
                source_id=source_id,
                state=CertificationState.BLOCKED,
                manifestation=None,
                archive=None,
                blocker="UPSTREAM_RATE_LIMIT",
            )
        if response.status != 200:
            return DownloadResult(
                source_id=source_id,
                state=CertificationState.OPEN,
                manifestation=None,
                archive=None,
                blocker=f"HTTP_{response.status}",
            )

        archive: ArchiveSnapshot | None = None
        try:
            archive = archive_snapshot(response.body)
        except (zipfile.BadZipFile, OSError):
            archive = None

        metadata: dict[str, Any] = {
            "http_status": response.status,
            "filename": name,
            "content_type": response.headers.get("content-type"),
        }
        if archive is not None:
            metadata["archive_member_count"] = len(archive.members)
            metadata["archive_outer_sha256"] = archive.outer_sha256

        manifestation = self.control_plane.freeze_manifestation(
            source_id=source_id,
            query=url,
            retrieved_utc=observed_utc,
            raw_bytes=response.body,
            row_count=None,
            schema_sha256=None,
            metadata=metadata,
        )
        self.store.freeze_raw(manifestation, response.body)
        if contract.query_once:
            self.store.record_query_receipt(manifestation)
        self.store.save_status(self.control_plane.report())

        return DownloadResult(
            source_id=source_id,
            state=CertificationState.PASS,
            manifestation=manifestation,
            archive=archive,
        )
