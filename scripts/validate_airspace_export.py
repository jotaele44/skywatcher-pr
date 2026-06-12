#!/usr/bin/env python3
"""Validate a PRIIS airspace producer export package.

This validator is intentionally small and dependency-light. It checks the
required package files, core observation fields, source/lineage/confidence
references, and the test-vs-production synthetic-data boundary.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PRODUCER_ID = "skywatcher-pr"

ALLOWED_EVIDENCE_TIERS = {"T1", "T2", "T3", "T4"}
ALLOWED_GEOMETRY_STATUS = {"located", "approximate", "unlocated", "invalid"}
ALLOWED_TEMPORAL_STATUS = {"exact", "approximate", "missing", "invalid"}
REQUIRED_PACKAGE_FILES = {
    "manifest.json",
    "observations.geojson",
    "observations.csv",
    "sources.json",
    "lineage.json",
    "confidence.json",
}
REQUIRED_OBSERVATION_FIELDS = {
    "observation_id",
    "event_datetime",
    "lat",
    "lon",
    "signal_type",
    "source_id",
    "source_type",
    "evidence_tier",
    "confidence",
    "geometry_status",
    "temporal_status",
    "lineage_id",
    "synthetic",
}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    raise ValueError(f"invalid boolean value: {value!r}")


def parse_float(value: Any, field_name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be numeric") from exc


def validate_datetime(value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("event_datetime is required")
    normalized = value.replace("Z", "+00:00")
    datetime.fromisoformat(normalized)


def load_observations(package_dir: Path) -> list[dict[str, Any]]:
    geojson = load_json(package_dir / "observations.geojson")
    if geojson.get("type") != "FeatureCollection":
        raise ValueError("observations.geojson must be a FeatureCollection")

    observations: list[dict[str, Any]] = []
    for index, feature in enumerate(geojson.get("features", []), start=1):
        props = feature.get("properties") or {}
        if not isinstance(props, dict):
            raise ValueError(f"feature {index} is missing properties")
        observations.append(props)
    return observations


def load_csv_ids(package_dir: Path) -> set[str]:
    with (package_dir / "observations.csv").open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return {row.get("observation_id", "") for row in reader}


def validate_package(package_dir: Path, mode: str) -> list[str]:
    errors: list[str] = []

    if not package_dir.exists() or not package_dir.is_dir():
        return [f"package directory does not exist: {package_dir}"]

    missing_files = sorted(name for name in REQUIRED_PACKAGE_FILES if not (package_dir / name).exists())
    if missing_files:
        errors.append(f"missing required files: {', '.join(missing_files)}")
        return errors

    try:
        manifest = load_json(package_dir / "manifest.json")
    except Exception as exc:  # noqa: BLE001
        return [f"manifest.json is invalid JSON: {exc}"]

    if not manifest.get("schema_version"):
        errors.append("manifest schema_version is required")
    if manifest.get("producer") != PRODUCER_ID:
        errors.append(f"manifest producer must be {PRODUCER_ID}")
    if manifest.get("mode") not in {"test", "production"}:
        errors.append("manifest mode must be test or production")

    try:
        observations = load_observations(package_dir)
    except Exception as exc:  # noqa: BLE001
        return errors + [f"observations.geojson is invalid: {exc}"]

    try:
        csv_ids = load_csv_ids(package_dir)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"observations.csv is invalid: {exc}")
        csv_ids = set()

    try:
        sources = {item["source_id"] for item in load_json(package_dir / "sources.json")}
    except Exception as exc:  # noqa: BLE001
        errors.append(f"sources.json is invalid: {exc}")
        sources = set()

    try:
        lineage = {item["lineage_id"] for item in load_json(package_dir / "lineage.json")}
    except Exception as exc:  # noqa: BLE001
        errors.append(f"lineage.json is invalid: {exc}")
        lineage = set()

    try:
        confidence_rows = {item["observation_id"] for item in load_json(package_dir / "confidence.json")}
    except Exception as exc:  # noqa: BLE001
        errors.append(f"confidence.json is invalid: {exc}")
        confidence_rows = set()

    for index, obs in enumerate(observations, start=1):
        obs_id = obs.get("observation_id", f"feature-{index}")
        missing = sorted(field for field in REQUIRED_OBSERVATION_FIELDS if field not in obs or obs[field] in {"", None})
        if missing:
            errors.append(f"{obs_id}: missing required fields: {', '.join(missing)}")
            continue

        try:
            validate_datetime(obs["event_datetime"])
        except ValueError as exc:
            errors.append(f"{obs_id}: {exc}")

        lat = parse_float(obs.get("lat"), "lat")
        lon = parse_float(obs.get("lon"), "lon")
        if not -90 <= lat <= 90:
            errors.append(f"{obs_id}: lat outside valid range")
        if not -180 <= lon <= 180:
            errors.append(f"{obs_id}: lon outside valid range")

        confidence = parse_float(obs.get("confidence"), "confidence")
        if not 0 <= confidence <= 1:
            errors.append(f"{obs_id}: confidence outside 0.0-1.0")

        if obs.get("evidence_tier") not in ALLOWED_EVIDENCE_TIERS:
            errors.append(f"{obs_id}: unsupported evidence_tier")
        if obs.get("geometry_status") not in ALLOWED_GEOMETRY_STATUS:
            errors.append(f"{obs_id}: unsupported geometry_status")
        if obs.get("temporal_status") not in ALLOWED_TEMPORAL_STATUS:
            errors.append(f"{obs_id}: unsupported temporal_status")
        if obs.get("source_id") not in sources:
            errors.append(f"{obs_id}: source_id not found in sources.json")
        if obs.get("lineage_id") not in lineage:
            errors.append(f"{obs_id}: lineage_id not found in lineage.json")
        if obs_id not in confidence_rows:
            errors.append(f"{obs_id}: confidence row not found in confidence.json")
        if csv_ids and obs_id not in csv_ids:
            errors.append(f"{obs_id}: observation missing from observations.csv")

        try:
            is_synthetic = parse_bool(obs.get("synthetic"))
        except ValueError as exc:
            errors.append(f"{obs_id}: {exc}")
            is_synthetic = False
        if mode == "production" and is_synthetic:
            errors.append(f"{obs_id}: synthetic rows are not allowed in production mode")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a PRIIS airspace export package")
    parser.add_argument("package_dir", type=Path)
    parser.add_argument("--mode", choices=["test", "production"], default="test")
    args = parser.parse_args()

    try:
        errors = validate_package(args.package_dir, args.mode)
    except ValueError as exc:
        errors = [str(exc)]

    if errors:
        print("VALIDATION FAILED")
        for error in errors:
            print(f"- {error}")
        return 1

    print("VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
