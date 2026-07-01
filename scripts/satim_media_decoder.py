#!/usr/bin/env python3
"""Runtime media decoder for Skywatcher/SATIM inputs.

This module converts analyst-provided runtime media into a sanitized frame
manifest. Source media are not copied into the repository and source filenames
are not written to committed outputs.

Supported extensions:
- PDF: page enumeration plus optional page rendering when PyMuPDF is installed.
- JPG/JPEG/PNG/WEBP/TIF/TIFF: image load verification with Pillow.
- HEIC/HEIF: requires Pillow plus pillow-heif or a local converter workflow.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".heic",
    ".heif",
    ".webp",
    ".tif",
    ".tiff",
}

IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".tif",
    ".tiff",
}

HEIC_EXTENSIONS = {".heic", ".heif"}


@dataclass
class FrameRecord:
    run_id: str
    frame_id: str
    frame_index: int
    media_kind: str
    input_extension: str
    source_reference: str
    width: int | None = None
    height: int | None = None
    page_number: int | None = None
    decode_status: str = "decoded"
    decoder: str = "unknown"
    notes: str | None = None


def load_manifest(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("manifest must be a JSON object")
    if "input_path" not in data:
        raise ValueError("manifest requires input_path")
    return data


def safe_run_id(manifest: dict[str, Any], input_path: Path) -> str:
    # Do not fall back to input_path.stem; that can leak source filenames.
    return str(manifest.get("run_id") or "runtime_media_run")


def validate_extension(input_path: Path) -> str:
    ext = input_path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        allowed = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(f"unsupported input extension {ext!r}; allowed: {allowed}")
    return ext


def decode_image(input_path: Path, run_id: str, ext: str) -> list[FrameRecord]:
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow is required for image decoding") from exc

    with Image.open(input_path) as image:
        width, height = image.size

    return [
        FrameRecord(
            run_id=run_id,
            frame_id=f"{run_id}_frame_0001",
            frame_index=1,
            media_kind="image",
            input_extension=ext,
            source_reference="runtime_input_not_committed",
            width=width,
            height=height,
            decoder="Pillow",
        )
    ]


def decode_heic(input_path: Path, run_id: str, ext: str) -> list[FrameRecord]:
    try:
        import pillow_heif  # type: ignore

        pillow_heif.register_heif_opener()
    except ImportError as exc:
        raise RuntimeError(
            "HEIC/HEIF decoding requires pillow-heif. Install with: pip install pillow-heif"
        ) from exc

    return decode_image(input_path, run_id, ext)


def decode_pdf(input_path: Path, run_id: str, ext: str) -> list[FrameRecord]:
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise RuntimeError("PDF decoding requires PyMuPDF. Install with: pip install pymupdf") from exc

    frames: list[FrameRecord] = []
    with fitz.open(input_path) as doc:
        for idx, page in enumerate(doc, start=1):
            rect = page.rect
            frames.append(
                FrameRecord(
                    run_id=run_id,
                    frame_id=f"{run_id}_page_{idx:04d}",
                    frame_index=idx,
                    media_kind="pdf_page",
                    input_extension=ext,
                    source_reference="runtime_input_not_committed",
                    width=int(rect.width),
                    height=int(rect.height),
                    page_number=idx,
                    decoder="PyMuPDF",
                )
            )
    return frames


def decode_media(manifest: dict[str, Any]) -> dict[str, Any]:
    input_path = Path(str(manifest["input_path"]))
    ext = validate_extension(input_path)
    run_id = safe_run_id(manifest, input_path)

    if not input_path.exists():
        raise FileNotFoundError(f"runtime input does not exist: {input_path}")

    if ext == ".pdf":
        frames = decode_pdf(input_path, run_id, ext)
    elif ext in IMAGE_EXTENSIONS:
        frames = decode_image(input_path, run_id, ext)
    elif ext in HEIC_EXTENSIONS:
        frames = decode_heic(input_path, run_id, ext)
    else:
        raise ValueError(f"unsupported input extension {ext}")

    return {
        "run_id": run_id,
        "source_reference": "runtime_input_not_committed",
        "input_extension": ext,
        "mime_guess": mimetypes.guess_type(f"input{ext}")[0],
        "frame_count": len(frames),
        "frames": [asdict(frame) for frame in frames],
        "qa_flags": sorted(set([
            "runtime_media_input",
            "source_media_not_committed",
            "source_filename_not_recorded",
            "frame_manifest_generated",
            *manifest.get("qa_flags", []),
        ])),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", help="Runtime-local JSON manifest with input_path and optional run_id")
    parser.add_argument("--out", default="frame_manifest.json")
    args = parser.parse_args()

    manifest = load_manifest(Path(args.manifest))
    frame_manifest = decode_media(manifest)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(frame_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
