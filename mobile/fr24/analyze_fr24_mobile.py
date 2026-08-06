#!/usr/bin/env python3
"""Bounded, dependency-free FR24 screenshot intake for a-Shell on iOS.

This module deliberately performs custody validation and image-header inspection
only. It does not claim OCR, aircraft identification, map geolocation, or parity
with the desktop RLSM pipeline. Those fields remain unresolved and provisional.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "skywatcher.fr24.mobile.v1"
MAX_BYTES = 40 * 1024 * 1024
MIN_DIMENSION = 320
MAX_DIMENSION = 16384


class MobileAnalysisError(ValueError):
    """A deterministic, user-correctable mobile intake failure."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        raise MobileAnalysisError("invalid_png_header")
    width, height = struct.unpack(">II", header[16:24])
    return width, height


def jpeg_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        if handle.read(2) != b"\xff\xd8":
            raise MobileAnalysisError("invalid_jpeg_header")
        while True:
            prefix = handle.read(1)
            if not prefix:
                break
            if prefix != b"\xff":
                continue
            marker = handle.read(1)
            while marker == b"\xff":
                marker = handle.read(1)
            if not marker or marker in {b"\xd8", b"\xd9"}:
                continue
            length_raw = handle.read(2)
            if len(length_raw) != 2:
                break
            length = struct.unpack(">H", length_raw)[0]
            if length < 2:
                raise MobileAnalysisError("invalid_jpeg_segment")
            marker_value = marker[0]
            if marker_value in {
                0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
            }:
                payload = handle.read(5)
                if len(payload) != 5:
                    break
                height, width = struct.unpack(">HH", payload[1:5])
                return width, height
            handle.seek(length - 2, os.SEEK_CUR)
    raise MobileAnalysisError("jpeg_dimensions_not_found")


def inspect_image(path: Path) -> tuple[str, int, int]:
    with path.open("rb") as handle:
        signature = handle.read(12)
    if signature.startswith(b"\x89PNG\r\n\x1a\n"):
        width, height = png_dimensions(path)
        return "image/png", width, height
    if signature.startswith(b"\xff\xd8"):
        width, height = jpeg_dimensions(path)
        return "image/jpeg", width, height
    raise MobileAnalysisError("unsupported_image_format")


def validate_dimensions(width: int, height: int) -> None:
    if min(width, height) < MIN_DIMENSION:
        raise MobileAnalysisError("image_too_small")
    if max(width, height) > MAX_DIMENSION:
        raise MobileAnalysisError("image_dimensions_exceed_limit")


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MobileAnalysisError("invalid_input_manifest") from exc
    if not isinstance(value, dict):
        raise MobileAnalysisError("invalid_input_manifest")
    required = {"schema_version", "run_id", "received_at"}
    if not required.issubset(value):
        raise MobileAnalysisError("input_manifest_missing_fields")
    if value["schema_version"] != SCHEMA_VERSION:
        raise MobileAnalysisError("unsupported_schema_version")
    return value


def result_for(source: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    size = source.stat().st_size
    if size <= 0:
        raise MobileAnalysisError("empty_input")
    if size > MAX_BYTES:
        raise MobileAnalysisError("input_exceeds_40_mib")
    media_type, width, height = inspect_image(source)
    validate_dimensions(width, height)
    orientation = "square" if width == height else ("landscape" if width > height else "portrait")
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": manifest["run_id"],
        "received_at": manifest["received_at"],
        "processed_at": now,
        "source": {
            "safe_filename": source.name,
            "byte_size": size,
            "sha256": sha256_file(source),
            "media_type": media_type,
        },
        "image": {"width": width, "height": height, "orientation": orientation},
        "classification": {
            "status": "provisional",
            "is_fr24": "unresolved",
            "confidence": 0.0,
            "reason": "mobile_v1_performs_custody_and_header_validation_only",
        },
        "observations": [],
        "unresolved_fields": [
            "fr24_layout_profile",
            "ocr_text",
            "aircraft_identity",
            "aircraft_marker_position",
            "map_scale",
            "map_geolocation",
            "desktop_rlsm_parity",
        ],
        "processing": {
            "execution_environment": "a-shell-ios",
            "analyzer": "mobile/fr24/analyze_fr24_mobile.py",
            "bounded_mode": True,
            "network_used": False,
            "external_processes_used": False,
        },
    }


def error_result(manifest: dict[str, Any] | None, code: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": manifest.get("run_id") if manifest else None,
        "status": "error",
        "error": {"code": code, "retryable": code in {"invalid_input_manifest"}},
        "observations": [],
        "unresolved_fields": ["all_analysis_fields"],
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    manifest: dict[str, Any] | None = None
    try:
        manifest = load_manifest(args.manifest)
        result = result_for(args.input, manifest)
        exit_code = 0
    except (OSError, MobileAnalysisError) as exc:
        code = str(exc) or exc.__class__.__name__
        result = error_result(manifest, code)
        exit_code = 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
