#!/usr/bin/env python3
"""Runtime-only media decoder for Skywatcher/SATIM inputs.

This module accepts analyst-provided local media at runtime and writes sanitized
frame manifests. It never commits or records source media filenames in output.

Supported runtime input extensions:
- PDF: requires PyMuPDF (`fitz`) for page rendering
- JPG/JPEG/PNG/WEBP/TIF/TIFF: requires Pillow
- HEIC/HEIF: requires Pillow plus pillow-heif, or a pre-converted runtime file
"""

from __future__ import annotations

import argparse
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

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

RASTER_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".tif",
    ".tiff",
    ".heic",
    ".heif",
}


@dataclass(frozen=True)
class FrameRecord:
    run_id: str
    frame_id: str
    frame_index: int
    source_packet: str
    media_type: str
    derived_frame_path: str
    width_px: int | None
    height_px: int | None
    extraction_status: str
    qa_flags: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "frame_id": self.frame_id,
            "frame_index": self.frame_index,
            "source_packet": self.source_packet,
            "media_type": self.media_type,
            "derived_frame_path": self.derived_frame_path,
            "width_px": self.width_px,
            "height_px": self.height_px,
            "extraction_status": self.extraction_status,
            "qa_flags": self.qa_flags,
        }


def load_manifest(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("manifest must be a JSON object")
    if "input_path" not in data:
        raise ValueError("manifest requires input_path")
    return data


def validate_input(input_path: str) -> Path:
    path = Path(input_path)
    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        allowed = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(f"unsupported input extension {ext!r}; allowed: {allowed}")
    if not path.exists():
        raise FileNotFoundError(f"runtime input not found: {path}")
    return path


def sanitized_run_id(manifest: dict[str, Any]) -> str:
    explicit = manifest.get("run_id")
    if explicit:
        return str(explicit)
    return f"runtime_{uuid.uuid4().hex[:12]}"


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def decode_pdf(input_path: Path, run_id: str, out_dir: Path, dpi: int) -> list[FrameRecord]:
    try:
        import fitz  # type: ignore
    except ImportError as exc:  # pragma: no cover - dependency availability varies
        raise RuntimeError("PDF decoding requires PyMuPDF: pip install pymupdf") from exc

    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    rows: list[FrameRecord] = []
    doc = fitz.open(input_path)
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)

    for page_index in range(len(doc)):
        page = doc.load_page(page_index)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        frame_name = f"frame_{page_index + 1:04d}.png"
        frame_path = frames_dir / frame_name
        pix.save(frame_path)
        rows.append(
            FrameRecord(
                run_id=run_id,
                frame_id=f"{run_id}_frame_{page_index + 1:04d}",
                frame_index=page_index + 1,
                source_packet="runtime_input_not_committed",
                media_type="pdf_page",
                derived_frame_path=str(frame_path),
                width_px=int(pix.width),
                height_px=int(pix.height),
                extraction_status="extracted",
                qa_flags=["runtime_media_input", "source_media_not_committed", "pdf_page_extraction"],
            )
        )
    return rows


def decode_raster(input_path: Path, run_id: str, out_dir: Path) -> list[FrameRecord]:
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - dependency availability varies
        raise RuntimeError("Raster decoding requires Pillow: pip install pillow") from exc

    ext = input_path.suffix.lower()
    if ext in {".heic", ".heif"}:
        try:
            import pillow_heif  # type: ignore

            pillow_heif.register_heif_opener()
        except ImportError as exc:  # pragma: no cover - dependency availability varies
            raise RuntimeError("HEIC/HEIF decoding requires pillow-heif: pip install pillow-heif") from exc

    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    frame_path = frames_dir / "frame_0001.png"

    with Image.open(input_path) as img:
        width, height = img.size
        img.convert("RGB").save(frame_path)

    return [
        FrameRecord(
            run_id=run_id,
            frame_id=f"{run_id}_frame_0001",
            frame_index=1,
            source_packet="runtime_input_not_committed",
            media_type=f"raster_{ext.lstrip('.')}",
            derived_frame_path=str(frame_path),
            width_px=int(width),
            height_px=int(height),
            extraction_status="extracted",
            qa_flags=["runtime_media_input", "source_media_not_committed", "raster_image_load"],
        )
    ]


def decode_media(manifest: dict[str, Any], out_dir: Path) -> list[FrameRecord]:
    input_path = validate_input(str(manifest["input_path"]))
    run_id = sanitized_run_id(manifest)
    ext = input_path.suffix.lower()
    if ext == ".pdf":
        return decode_pdf(input_path, run_id, out_dir, int(manifest.get("dpi", 144)))
    if ext in RASTER_EXTENSIONS:
        return decode_raster(input_path, run_id, out_dir)
    raise ValueError(f"unsupported extension after validation: {ext}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", help="Runtime-local manifest containing input_path")
    parser.add_argument("--out-dir", default="out/media_frames")
    parser.add_argument("--frame-manifest", default="frame_manifest.jsonl")
    args = parser.parse_args()

    manifest = load_manifest(Path(args.manifest))
    out_dir = Path(args.out_dir)
    rows = [row.as_dict() for row in decode_media(manifest, out_dir)]
    write_jsonl(out_dir / args.frame_manifest, rows)
    print(f"wrote {out_dir / args.frame_manifest}")


if __name__ == "__main__":
    main()
