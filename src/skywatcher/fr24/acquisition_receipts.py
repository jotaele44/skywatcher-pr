"""Durable acquisition receipts for coverage-ledger targets.

Discovery and playback are deliberately separate:
- discovery: authenticated FR24 history lookup produces dated FR24 flight IDs
- playback: scripts/fr24_harvest.py spends quota one flight at a time

This module never performs network access and never stores credentials.
"""

from __future__ import annotations

import csv
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
DISCOVERY_OPEN = {"BLOCKED_EXTERNAL_AUTH", "PENDING_DISCOVERY", "ERROR"}
DISCOVERY_TERMINAL = {"DISCOVERED", "NO_MATCHES", "BEYOND_LOOKBACK"}
PLAYBACK_STATES = {"NOT_ATTEMPTED", "READY", "IN_PROGRESS", "COMPLETE", "PARTIAL", "BLOCKED"}


class AcquisitionReceiptError(ValueError):
    """Raised when an acquisition receipt violates the manifest contract."""


def load_manifest(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    validate_manifest(value)
    return value


def validate_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise AcquisitionReceiptError("unsupported acquisition manifest schema")
    targets = manifest.get("targets")
    if not isinstance(targets, list):
        raise AcquisitionReceiptError("targets must be a list")
    seen: set[str] = set()
    for target in targets:
        if not isinstance(target, dict):
            raise AcquisitionReceiptError("target must be an object")
        acquisition_id = target.get("acquisition_id")
        if not isinstance(acquisition_id, str) or not acquisition_id:
            raise AcquisitionReceiptError("target acquisition_id is required")
        if acquisition_id in seen:
            raise AcquisitionReceiptError(f"duplicate acquisition_id: {acquisition_id}")
        seen.add(acquisition_id)
        if target.get("priority_tier") != "P1":
            raise AcquisitionReceiptError(f"{acquisition_id}: non-P1 target in P1 manifest")
        if not isinstance(target.get("identity"), str) or not target["identity"]:
            raise AcquisitionReceiptError(f"{acquisition_id}: identity is required")
        if target.get("playback_status") not in PLAYBACK_STATES:
            raise AcquisitionReceiptError(f"{acquisition_id}: invalid playback_status")
        flights = target.get("discovered_flights", [])
        if not isinstance(flights, list):
            raise AcquisitionReceiptError(f"{acquisition_id}: discovered_flights must be a list")
        for flight in flights:
            _validate_discovered_flight(target, flight)


def _validate_discovered_flight(target: dict[str, Any], flight: Any) -> None:
    if not isinstance(flight, dict):
        raise AcquisitionReceiptError("discovered flight must be an object")
    flight_id = flight.get("flight_id")
    if not isinstance(flight_id, str) or not (6 <= len(flight_id) <= 8):
        raise AcquisitionReceiptError("discovered flight_id must be a 6-8 character FR24 id")
    try:
        int(flight_id, 16)
    except ValueError as exc:
        raise AcquisitionReceiptError("discovered flight_id must be hexadecimal") from exc
    if flight.get("identity") != target.get("identity"):
        raise AcquisitionReceiptError("discovered flight identity must match target identity")
    date = flight.get("date")
    if not isinstance(date, str):
        raise AcquisitionReceiptError("discovered flight date is required")
    try:
        observed = datetime.fromisoformat(date).date()
    except ValueError as exc:
        raise AcquisitionReceiptError("discovered flight date must be YYYY-MM-DD") from exc
    start = target.get("recoverable_from")
    end = target.get("recoverable_to")
    if start and observed < datetime.fromisoformat(start).date():
        raise AcquisitionReceiptError("discovered flight falls before recoverable window")
    if end and observed > datetime.fromisoformat(end).date():
        raise AcquisitionReceiptError("discovered flight falls after recoverable window")


def _atomic_write(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, sort_keys=False)
            handle.write("\n")
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def next_discovery_target(manifest: dict[str, Any]) -> dict[str, Any] | None:
    validate_manifest(manifest)
    candidates = [
        target for target in manifest["targets"]
        if target.get("discovery_status") in DISCOVERY_OPEN
    ]
    candidates.sort(
        key=lambda target: (
            target.get("days_left_at_freeze") if target.get("days_left_at_freeze") is not None else 10**9,
            -int(target.get("priority_score") or 0),
            target["acquisition_id"],
        )
    )
    return candidates[0] if candidates else None


def record_discovery(
    path: Path,
    acquisition_id: str,
    flights: list[dict[str, str]],
    *,
    source: str,
    observed_at: str | None = None,
) -> dict[str, Any]:
    manifest = load_manifest(path)
    target = next(
        (item for item in manifest["targets"] if item["acquisition_id"] == acquisition_id),
        None,
    )
    if target is None:
        raise AcquisitionReceiptError(f"unknown acquisition_id: {acquisition_id}")
    normalized = []
    for flight in flights:
        item = {
            "identity": target["identity"],
            "date": flight["date"],
            "flight_id": flight["flight_id"].lower(),
            "discovery_source": source,
        }
        _validate_discovered_flight(target, item)
        normalized.append(item)
    deduped = {
        (flight["date"], flight["flight_id"]): flight
        for flight in normalized
    }
    target["discovered_flights"] = [
        deduped[key] for key in sorted(deduped)
    ]
    target["discovered_flight_ids"] = [
        flight["flight_id"] for flight in target["discovered_flights"]
    ]
    target["discovery_status"] = "DISCOVERED" if target["discovered_flights"] else "NO_MATCHES"
    target["playback_status"] = "READY" if target["discovered_flights"] else "NOT_ATTEMPTED"
    target["last_attempt_at"] = observed_at or datetime.now(timezone.utc).isoformat()
    target["attempt_count"] = int(target.get("attempt_count") or 0) + 1
    target["last_error"] = None
    validate_manifest(manifest)
    _atomic_write(path, manifest)
    return target


def record_blocked_auth(
    path: Path,
    acquisition_id: str,
    *,
    reason: str,
    observed_at: str | None = None,
) -> dict[str, Any]:
    manifest = load_manifest(path)
    target = next(
        (item for item in manifest["targets"] if item["acquisition_id"] == acquisition_id),
        None,
    )
    if target is None:
        raise AcquisitionReceiptError(f"unknown acquisition_id: {acquisition_id}")
    target["discovery_status"] = "BLOCKED_EXTERNAL_AUTH"
    target["last_attempt_at"] = observed_at or datetime.now(timezone.utc).isoformat()
    target["attempt_count"] = int(target.get("attempt_count") or 0) + 1
    target["last_error"] = reason
    _atomic_write(path, manifest)
    return target


def export_harvest_carryover(manifest: dict[str, Any], output: Path) -> int:
    """Export discovered flights into fr24_harvest.py's carryover queue contract."""
    validate_manifest(manifest)
    rows: dict[str, dict[str, str]] = {}
    for target in manifest["targets"]:
        if target.get("discovery_status") != "DISCOVERED":
            continue
        for flight in target.get("discovered_flights") or []:
            rows[flight["flight_id"]] = {
                "date": flight["date"],
                "tail": flight["identity"],
                "flight_id": flight["flight_id"],
            }

    ordered = sorted(rows.values(), key=lambda row: (row["date"], row["tail"], row["flight_id"]))
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["date", "tail", "flight_id"])
        writer.writeheader()
        writer.writerows(ordered)
    return len(ordered)


def status_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    validate_manifest(manifest)
    targets = manifest["targets"]
    discovery: dict[str, int] = {}
    playback: dict[str, int] = {}
    for target in targets:
        ds = str(target.get("discovery_status"))
        ps = str(target.get("playback_status"))
        discovery[ds] = discovery.get(ds, 0) + 1
        playback[ps] = playback.get(ps, 0) + 1
    return {
        "target_count": len(targets),
        "discovery": discovery,
        "playback": playback,
        "discovered_flight_count": sum(len(target.get("discovered_flights") or []) for target in targets),
    }
