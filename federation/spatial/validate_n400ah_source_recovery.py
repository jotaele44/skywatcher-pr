#!/usr/bin/env python3
"""Validate recovered N400AH provider payloads without promoting archive identity.

The original N400AH.zip byte stream is not required to prove that an in-scope
provider payload is byte-identical. Archive/container identity and member
payload identity are intentionally reported separately.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

CONTRACT = "skywatcher-n400ah-source-recovery/1.0"
DATASET_ID = "N400AH_STRUCTURED_TRACKS_2026Q2_Q3_v1"
ORIGINAL_ARCHIVE_SHA256 = (
    "fa64d13aa3fc32b36b70e84e591b1a3ededb89bb3335e35dda711bb0182b264e"
)
EXPECTED_SCHEMA = (
    "Timestamp",
    "UTC",
    "Callsign",
    "Position",
    "Altitude",
    "Speed",
    "Direction",
)
POSITION_RE = re.compile(
    r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$"
)


class RecoveryError(ValueError):
    """Recovered manifestation fails the frozen source contract."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_source_hashes(path: Path) -> list[dict[str, Any]]:
    raw = path.read_bytes()
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    required = {"path", "role", "size_bytes", "sha256"}
    if not rows or set(rows[0]) != required:
        raise RecoveryError("source hash ledger schema mismatch")
    seen = set()
    for row in rows:
        name = row["path"]
        if not name or name in seen:
            raise RecoveryError("source hash ledger has missing or duplicate path")
        seen.add(name)
        if row["role"] not in {"provider_csv", "provider_kml"}:
            raise RecoveryError("unsupported source role")
        try:
            size = int(row["size_bytes"])
        except ValueError as exc:
            raise RecoveryError("invalid source size") from exc
        if size < 0:
            raise RecoveryError("invalid source size")
        digest = row["sha256"]
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise RecoveryError("invalid source SHA256")
    return rows


def _point_audit(csv_payloads: list[tuple[str, bytes]]) -> dict[str, Any]:
    point_count = 0
    valid_position_count = 0
    stable_ids: set[str] = set()
    timestamp_values: set[str] = set()
    utc_values: set[str] = set()
    callsigns: Counter[str] = Counter()
    track_rows: dict[str, int] = {}

    for name, raw in sorted(csv_payloads):
        track_id = Path(name).stem
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        if tuple(reader.fieldnames or ()) != EXPECTED_SCHEMA:
            raise RecoveryError(f"{name}: provider CSV schema mismatch")
        row_count = 0
        for source_row, row in enumerate(reader, start=1):
            row_count += 1
            point_count += 1
            record_id = f"N400AH:{track_id}:R{source_row:05d}"
            if record_id in stable_ids:
                raise RecoveryError("duplicate stable source-row Record_ID")
            stable_ids.add(record_id)

            match = POSITION_RE.fullmatch(row["Position"] or "")
            if not match:
                raise RecoveryError(f"{name}:{source_row}: malformed Position")
            lat, lon = float(match.group(1)), float(match.group(2))
            if (
                not math.isfinite(lat)
                or not math.isfinite(lon)
                or not -90 <= lat <= 90
                or not -180 <= lon <= 180
            ):
                raise RecoveryError(f"{name}:{source_row}: out-of-range Position")
            valid_position_count += 1

            timestamp = row["Timestamp"]
            utc = row["UTC"]
            if not timestamp or timestamp in timestamp_values:
                raise RecoveryError("missing or duplicate provider Timestamp")
            if not utc or utc in utc_values:
                raise RecoveryError("missing or duplicate provider UTC")
            timestamp_values.add(timestamp)
            utc_values.add(utc)
            callsigns[row["Callsign"]] += 1
        track_rows[track_id] = row_count

    if callsigns != Counter({"N400AH": point_count}):
        raise RecoveryError("callsign denominator mismatch")
    return {
        "Point_Count": point_count,
        "Valid_Position_Count": valid_position_count,
        "Stable_Record_ID_Count": len(stable_ids),
        "Duplicate_Record_ID_Count": point_count - len(stable_ids),
        "Unique_Timestamp_Count": len(timestamp_values),
        "Unique_UTC_Count": len(utc_values),
        "Callsign_Counts": dict(sorted(callsigns.items())),
        "Track_Row_Counts": dict(sorted(track_rows.items())),
    }


def validate_recovery(
    *,
    archive_path: Path,
    source_hashes_path: Path,
    prefix: str,
) -> dict[str, Any]:
    ledger = load_source_hashes(source_hashes_path)
    expected = {row["path"]: row for row in ledger}
    matched = 0
    missing: list[str] = []
    divergent: list[str] = []
    csv_payloads: list[tuple[str, bytes]] = []

    normalized_prefix = prefix.strip("/")
    prefix_with_slash = normalized_prefix + "/" if normalized_prefix else ""
    with zipfile.ZipFile(archive_path) as archive:
        all_payload_names = {
            name
            for name in archive.namelist()
            if not name.endswith("/") and not name.startswith("__MACOSX/")
        }
        scoped_names = {
            name
            for name in all_payload_names
            if name.startswith(prefix_with_slash)
        }
        for name, row in sorted(expected.items()):
            member = prefix_with_slash + name
            if member not in archive.namelist():
                missing.append(name)
                continue
            data = archive.read(member)
            actual_size = len(data)
            actual_sha = sha256_bytes(data)
            if actual_size != int(row["size_bytes"]) or actual_sha != row["sha256"]:
                divergent.append(name)
                continue
            matched += 1
            if row["role"] == "provider_csv":
                csv_payloads.append((name, data))

        expected_members = {prefix_with_slash + name for name in expected}
        extra_scoped = sorted(scoped_names - expected_members)

    if missing or divergent:
        raise RecoveryError(
            f"source payload closure failed: missing={len(missing)} divergent={len(divergent)}"
        )

    role_counts = Counter(row["role"] for row in ledger)
    point_audit = _point_audit(csv_payloads)
    archive_bytes = archive_path.read_bytes()
    actual_archive_sha = sha256_bytes(archive_bytes)

    if actual_archive_sha == ORIGINAL_ARCHIVE_SHA256:
        container_state = "BYTE_IDENTICAL"
    elif extra_scoped:
        container_state = "DISTINCT_PAYLOADS"
    else:
        container_state = "UNRESOLVED"

    return {
        "Contract": CONTRACT,
        "Dataset_ID": DATASET_ID,
        "Original_Source_Archive_SHA256": ORIGINAL_ARCHIVE_SHA256,
        "Recovery_Container_SHA256": actual_archive_sha,
        "Recovery_Container_Bytes": len(archive_bytes),
        "Container_Comparison_State": container_state,
        "Original_Archive_Byte_Identity": (
            "VERIFIED" if container_state == "BYTE_IDENTICAL" else "UNRESOLVED"
        ),
        "In_Scope_Source_Payload_State": "BYTE_IDENTICAL",
        "Expected_Source_File_Count": len(ledger),
        "Matched_Source_File_Count": matched,
        "Missing_Source_File_Count": len(missing),
        "Divergent_Source_File_Count": len(divergent),
        "Extra_Scoped_Container_File_Count": len(extra_scoped),
        "Role_Counts": dict(sorted(role_counts.items())),
        "Source_Hash_Ledger_SHA256": sha256_bytes(source_hashes_path.read_bytes()),
        **point_audit,
        "Coordinate_Evidence_State": "VERIFIED_SOURCE_COORDINATE",
        "Migration_Provenance_Class": "RECOMPUTED_FROM_SOURCE_COORDINATE",
        "Migration_Execution_State": "BLOCKED_SOURCE_NOT_CI_ADDRESSABLE",
        "Promotion_State": "CANDIDATE_NOT_CANONICAL",
        "State": "PASS_SOURCE_RECOVERY",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--source-hashes", type=Path, required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--receipt-out", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = validate_recovery(
            archive_path=args.archive,
            source_hashes_path=args.source_hashes,
            prefix=args.prefix,
        )
    except (OSError, zipfile.BadZipFile, RecoveryError) as exc:
        parser.exit(2, f"FAIL_CLOSED: {exc}\n")
    args.receipt_out.parent.mkdir(parents=True, exist_ok=True)
    args.receipt_out.write_text(
        json.dumps(receipt, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
