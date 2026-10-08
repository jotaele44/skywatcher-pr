#!/usr/bin/env python3
"""Verify and optionally install the user-supplied FR24 icon reference library.

The public repository stores only taxonomy/provenance metadata. Pixel assets remain
machine-local until redistribution rights are verified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path, PurePosixPath

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from skywatcher.registry.fr24_poi_icons import (  # noqa: E402
    DEFAULT_REGISTRY,
    load_registry,
    validate_registry,
    verify_source_archive,
)

DEFAULT_INSTALL_ROOT = REPO / "data" / "local_reference" / "fr24_icon_library"


def _safe_destination(root: Path, member_path: str) -> Path:
    parts = PurePosixPath(member_path)
    if parts.is_absolute() or ".." in parts.parts:
        raise ValueError(f"unsafe archive member path: {member_path!r}")
    destination = root.joinpath(*parts.parts)
    resolved_root = root.resolve()
    resolved_destination = destination.resolve()
    if resolved_destination != resolved_root and resolved_root not in resolved_destination.parents:
        raise ValueError(f"archive member escapes install root: {member_path!r}")
    return destination


def install_reference_library(
    zip_path: Path,
    *,
    registry_path: Path = DEFAULT_REGISTRY,
    install_root: Path = DEFAULT_INSTALL_ROOT,
    overwrite: bool = False,
) -> dict[str, object]:
    registry = load_registry(registry_path)
    registry_check = validate_registry(registry)
    if registry_check["status"] != "pass":
        raise ValueError(
            "registry validation failed: " + "; ".join(registry_check["failures"])
        )
    archive_check = verify_source_archive(zip_path, registry)
    if not archive_check["install_allowed"]:
        raise ValueError(
            "archive payload is not an installable V1 manifestation: "
            + str(archive_check["status"])
        )

    actual_sha = str(archive_check["archive_sha256"])
    destination = install_root / actual_sha[:16]
    if destination.exists():
        if not overwrite:
            raise FileExistsError(
                f"install destination already exists: {destination} "
                "(use --overwrite for an idempotent refresh)"
            )
        shutil.rmtree(destination)

    expected_manifestations = {
        row["raw_member_path"]: row for row in registry["source_manifestations"]
    }
    destination.mkdir(parents=True, exist_ok=False)
    installed: list[dict[str, object]] = []

    with zipfile.ZipFile(zip_path) as archive:
        by_name = {
            info.filename: info for info in archive.infolist() if not info.is_dir()
        }
        for member_path, expected in sorted(expected_manifestations.items()):
            info = by_name.get(member_path)
            if info is None:
                raise ValueError(f"required semantic member missing: {member_path}")
            payload = archive.read(member_path)
            digest = hashlib.sha256(payload).hexdigest()
            if digest != expected["sha256"] or len(payload) != expected["uncompressed_size"]:
                raise ValueError(f"semantic member failed hash/size check: {member_path}")
            out = _safe_destination(destination / "raw", member_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(payload)
            installed.append(
                {
                    "raw_member_path": member_path,
                    "uncompressed_size": len(payload),
                    "sha256": digest,
                    "local_path": str(out.relative_to(destination)),
                }
            )

    receipt = {
        "schema_version": "fr24_icon_reference_install_receipt/1.0",
        "registry_id": registry["registry_id"],
        "registry_path": str(registry_path),
        "archive": archive_check,
        "installed_semantic_members": installed,
        "installed_count": len(installed),
        "pixel_policy": registry["source_archive"]["repository_pixel_policy"],
        "note": (
            "This directory is machine-local and gitignored. Raw pixels are reference "
            "material only; icon class is not POI/operator identity."
        ),
    }
    (destination / "install_receipt.json").write_text(
        json.dumps(receipt, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "status": "installed",
        "destination": str(destination),
        "installed_count": len(installed),
        "archive_status": archive_check["status"],
        "receipt": str(destination / "install_receipt.json"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="Path to Icon Library.zip")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--install-root", type=Path, default=DEFAULT_INSTALL_ROOT)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)

    try:
        registry = load_registry(args.registry)
        registry_check = validate_registry(registry)
        if registry_check["status"] != "pass":
            print(json.dumps(registry_check, indent=2, ensure_ascii=False))
            return 2

        archive_check = verify_source_archive(args.archive, registry)
        result: dict[str, object] = {
            "registry": registry_check,
            "archive": archive_check,
        }
        if args.install:
            result["install"] = install_reference_library(
                args.archive,
                registry_path=args.registry,
                install_root=args.install_root,
                overwrite=args.overwrite,
            )
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
        return 0 if archive_check["install_allowed"] else 2
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(json.dumps({"status": "failed", "error": f"{type(exc).__name__}: {exc}"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
