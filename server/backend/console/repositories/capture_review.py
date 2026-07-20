"""FR24 capture-inventory and manual-review repository adapters."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import ArtifactRef, RepositorySnapshot, finalize_snapshot
from .io import (
    artifact_ref,
    bounded_paths,
    open_sqlite_readonly,
    read_structured_rows,
    sqlite_rows,
    sqlite_table_exists,
)
from .normalize import (
    as_bool,
    as_int,
    attach_provenance,
    first,
    normalize_time,
    parse_json,
    stable_id,
    text,
)

FLIGHT_DB_DEFAULTS = (
    "flight_database.db",
    "data/flight_database.db",
    "outputs/flight_database.db",
)

CAPTURE_DEFAULTS = (
    "data/_manifests/fr24_audit/screenshot_inventory.csv",
    "data/_manifests/fr24_audit/screenshot_inventory.json",
    "reports/fr24/screenshot_inventory.csv",
    "reports/fr24/screenshot_inventory.json",
    "screenshot_inventory.csv",
    "screenshot_inventory.json",
)

REVIEW_DEFAULTS = (
    "data/_manifests/fr24_audit/fr24_dashboard_review_queue.csv",
    "data/_manifests/fr24_audit/review_queue.csv",
    "data/_manifests/fr24_audit/review_queue.json",
    "fr24_dashboard_review_queue.json",
    "review/review_queue.db",
    "data/review/review_queue.db",
    "data/_manifests/fr24_audit/review_queue.db",
)


class FR24CaptureRepository:
    name = "fr24_captures"

    def __init__(self, root: Path):
        self.root = root

    def snapshot(self) -> RepositorySnapshot:
        rows: list[dict[str, Any]] = []
        artifacts: list[ArtifactRef] = []
        warnings: list[str] = []

        candidates = bounded_paths(
            self.root,
            env_var="SKYWATCHER_FR24_CAPTURE_INVENTORY",
            defaults=CAPTURE_DEFAULTS,
        )
        candidates += bounded_paths(
            self.root,
            env_var="SKYWATCHER_FLIGHT_DB",
            defaults=FLIGHT_DB_DEFAULTS,
        )
        seen_paths: set[str] = set()
        for path, configured_by in candidates:
            key = str(path.resolve(strict=False))
            if key in seen_paths:
                continue
            seen_paths.add(key)
            if not path.is_file():
                artifacts.append(artifact_ref(path, kind="capture_inventory", configured_by=configured_by))
                continue
            try:
                if path.suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
                    loaded = self._from_database(path)
                    kind = "sqlite_screenshots"
                else:
                    loaded = [self._normalize(row, path, "capture_inventory_file") for row in read_structured_rows(path)]
                    kind = "capture_inventory"
                rows.extend(row for row in loaded if row is not None)
                artifacts.append(
                    artifact_ref(
                        path,
                        kind=kind,
                        configured_by=configured_by,
                        record_count=len(loaded),
                        status="loaded",
                    )
                )
            except Exception as exc:
                artifacts.append(
                    artifact_ref(
                        path,
                        kind="capture_inventory",
                        configured_by=configured_by,
                        status="error",
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )

        deduped: dict[str, dict[str, Any]] = {}
        for row in rows:
            deduped.setdefault(str(row["id"]), row)
        return finalize_snapshot(
            self.name,
            list(deduped.values()),
            artifacts,
            absent_reason=(
                "No bounded screenshot inventory or FlightDatabase artifact is present. "
                "Configure SKYWATCHER_FR24_CAPTURE_INVENTORY or SKYWATCHER_FLIGHT_DB."
            ),
            empty_reason="Capture artifacts exist but contain no eligible metadata rows.",
            warnings=warnings,
        )

    def _from_database(self, path: Path) -> list[dict[str, Any]]:
        connection = open_sqlite_readonly(path)
        try:
            if not sqlite_table_exists(connection, "screenshots"):
                return []
            return [self._normalize(dict(row), path, "sqlite_screenshots") for row in sqlite_rows(connection, "screenshots")]
        finally:
            connection.close()

    def _normalize(self, source: dict[str, Any], path: Path, adapter: str) -> dict[str, Any]:
        qa_flags: list[str] = []
        source_record_id = text(
            first(source, ("screenshot_id", "capture_id", "sha256", "candidate_id", "image_path", "path"))
        ) or stable_id(path, source, prefix="capture-")
        scanned_at = normalize_time(
            first(source, ("scanned_at", "processed_at", "created_at", "timestamp")),
            field_name="capture_time",
            qa_flags=qa_flags,
        )
        image_path = text(first(source, ("image_path", "path", "image_name", "filename")))
        row = {
            "id": source_record_id,
            "capture_id": source_record_id,
            "screenshot_id": text(source.get("screenshot_id")) or source_record_id,
            "image_path": image_path,
            "filename": text(first(source, ("filename", "image_name"))) or Path(image_path).name,
            "sha256": text(source.get("sha256")) or None,
            "size_bytes": as_int(source.get("size_bytes")),
            "width": as_int(source.get("width")),
            "height": as_int(source.get("height")),
            "is_corrupt": as_bool(source.get("is_corrupt")),
            "is_duplicate": as_bool(source.get("is_duplicate")),
            "duplicate_of": text(source.get("duplicate_of")) or None,
            "scanned_at_utc": scanned_at,
            "review_status": text(source.get("review_status")) or "unreviewed",
            "coordinate_method": text(source.get("coordinate_method")) or None,
            "coordinate_confidence": source.get("coordinate_confidence"),
            "estimated_error_m": source.get("estimated_error_m"),
        }
        return attach_provenance(
            row,
            path=path,
            adapter=f"FR24CaptureRepository:{adapter}",
            source_record_id=source_record_id,
            source_family="screenshot_evidence",
            source_provider="skywatcher-fr24-ingest",
            source_method="screenshot_inventory",
            data_rights="user_supplied",
            operational_mode="evidence_only",
            artifact_kind="capture_inventory",
            synthetic=as_bool(source.get("synthetic") or source.get("synthetic_flag")),
            qa_flags=qa_flags,
        )


class ManualReviewRepository:
    name = "manual_review_items"

    def __init__(self, root: Path):
        self.root = root

    def snapshot(self) -> RepositorySnapshot:
        rows: list[dict[str, Any]] = []
        artifacts: list[ArtifactRef] = []
        candidates = bounded_paths(
            self.root,
            env_var="SKYWATCHER_REVIEW_QUEUE",
            defaults=REVIEW_DEFAULTS,
        )
        for path, configured_by in candidates:
            if not path.is_file():
                artifacts.append(artifact_ref(path, kind="manual_review_queue", configured_by=configured_by))
                continue
            try:
                if path.suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
                    loaded = self._from_database(path)
                    kind = "sqlite_review_queue"
                else:
                    loaded = [self._normalize(row, path, "review_export") for row in read_structured_rows(path)]
                    kind = "review_export"
                rows.extend(loaded)
                artifacts.append(
                    artifact_ref(
                        path,
                        kind=kind,
                        configured_by=configured_by,
                        record_count=len(loaded),
                        status="loaded",
                    )
                )
            except Exception as exc:
                artifacts.append(
                    artifact_ref(
                        path,
                        kind="manual_review_queue",
                        configured_by=configured_by,
                        status="error",
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )

        deduped: dict[str, dict[str, Any]] = {}
        for row in rows:
            deduped.setdefault(str(row["id"]), row)
        return finalize_snapshot(
            self.name,
            list(deduped.values()),
            artifacts,
            absent_reason=(
                "No bounded manual-review database or export is present. "
                "Configure SKYWATCHER_REVIEW_QUEUE or generate the documented review artifacts."
            ),
            empty_reason="Review artifacts exist but contain no candidate rows.",
        )

    def _from_database(self, path: Path) -> list[dict[str, Any]]:
        connection = open_sqlite_readonly(path)
        try:
            if not sqlite_table_exists(connection, "review_queue"):
                return []
            return [self._normalize(row, path, "sqlite_review_queue") for row in sqlite_rows(connection, "review_queue")]
        finally:
            connection.close()

    def _normalize(self, source: dict[str, Any], path: Path, adapter: str) -> dict[str, Any]:
        qa_flags: list[str] = []
        source_record_id = text(
            first(source, ("item_id", "candidate_id", "id", "image_path", "image_name"))
        ) or stable_id(path, source, prefix="review-")
        created_at = normalize_time(
            first(source, ("created_at", "generated_at", "timestamp")),
            field_name="created_at",
            qa_flags=qa_flags,
        )
        reviewed_at = None
        if first(source, ("reviewed_at", "resolved_at")) not in (None, ""):
            reviewed_at = normalize_time(
                first(source, ("reviewed_at", "resolved_at")),
                field_name="reviewed_at",
                qa_flags=qa_flags,
            )
        status = text(first(source, ("queue_status", "status", "review_status"))) or "pending"
        if status.lower() in {
            "confirmed",
            "confirmed_aircraft_event",
            "confirmed_anomaly",
            "confirmed_route",
            "verified_event",
            "validated_aircraft_event",
        }:
            status = "prohibited_label_held"
            qa_flags.append("prohibited_confirmation_label_removed")
        row = {
            "id": source_record_id,
            "item_id": source_record_id,
            "candidate_id": text(source.get("candidate_id")) or None,
            "queue_type": text(first(source, ("queue_type", "queue_source"))) or "unknown",
            "image_path": text(first(source, ("image_path", "image_name"))),
            "reason": text(first(source, ("reason", "review_reason", "notes"))) or "No reason supplied",
            "metadata": parse_json(source.get("metadata"), {}),
            "status": status,
            "resolution": text(source.get("resolution")) or None,
            "reviewer_notes": text(source.get("reviewer_notes")) or None,
            "created_at_utc": created_at,
            "reviewed_at_utc": reviewed_at,
            "confirmation_status": "not_confirmed",
            "priority_score": as_int(source.get("priority_score")),
            "priority_tier": as_int(source.get("priority_tier")),
        }
        return attach_provenance(
            row,
            path=path,
            adapter=f"ManualReviewRepository:{adapter}",
            source_record_id=source_record_id,
            source_family="screenshot_evidence",
            source_provider="skywatcher-fr24-review",
            source_method="review_queue",
            data_rights="derived",
            operational_mode="evidence_only",
            artifact_kind="manual_review_queue",
            synthetic=as_bool(source.get("synthetic") or source.get("synthetic_flag")),
            qa_flags=qa_flags,
        )
