"""Materialize visual evidence from native images, PDF pages, and ZIP members.

Derived visual files are conveniences for downstream engines. They never replace
or inherit the byte identity of their source container/page/member.
"""
from __future__ import annotations

import hashlib
import shutil
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

from skywatcher.evidence_router import EvidenceItem, EvidenceManifest


@dataclass
class MaterializedVisual:
    manifestation_id: str
    source_container: str
    source_member: str | None
    source_page: int | None
    output_path: str | None
    output_sha256: str | None
    output_size_bytes: int | None
    adapter: str
    state: str
    reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _target(output_dir: Path, item: EvidenceItem, suffix: str) -> Path:
    return output_dir / f"{item.manifestation_id}{suffix.lower()}"


def _materialize_native(item: EvidenceItem, output_dir: Path) -> MaterializedVisual:
    source = Path(item.container_path)
    target = _target(output_dir, item, item.extension or ".img")
    shutil.copyfile(source, target)
    digest = _sha256_file(target)
    state = "PASS" if digest == item.sha256 else "FAIL"
    return MaterializedVisual(
        manifestation_id=item.manifestation_id,
        source_container=item.container_path,
        source_member=None,
        source_page=None,
        output_path=str(target),
        output_sha256=digest,
        output_size_bytes=target.stat().st_size,
        adapter="native_image_passthrough",
        state=state,
        reason=None if state == "PASS" else "materialized bytes differ from frozen native-image hash",
    )


def _materialize_zip_member(item: EvidenceItem, output_dir: Path) -> MaterializedVisual:
    if not item.member_path:
        return _blocked(item, "zip_image_member", "archive image manifestation lacks member path")
    target = _target(output_dir, item, item.extension or ".img")
    try:
        with zipfile.ZipFile(item.container_path) as archive:
            payload = archive.read(item.member_path)
    except (KeyError, OSError, RuntimeError, zipfile.BadZipFile) as exc:
        return _blocked(item, "zip_image_member", f"archive member extraction failed: {exc}")
    target.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    state = "PASS" if digest == item.sha256 else "FAIL"
    return MaterializedVisual(
        manifestation_id=item.manifestation_id,
        source_container=item.container_path,
        source_member=item.member_path,
        source_page=None,
        output_path=str(target),
        output_sha256=digest,
        output_size_bytes=len(payload),
        adapter="zip_image_member",
        state=state,
        reason=None if state == "PASS" else "extracted member bytes differ from frozen member hash",
    )


def _materialize_pdf_page(item: EvidenceItem, output_dir: Path) -> MaterializedVisual:
    if item.page_number is None:
        return _blocked(item, "pymupdf_page_render", "PDF visual manifestation lacks page number")
    try:
        import fitz  # type: ignore[import-not-found]
    except ImportError:
        return _blocked(item, "pymupdf_page_render", "PyMuPDF is unavailable")

    target = _target(output_dir, item, ".png")
    try:
        with fitz.open(item.container_path) as document:
            if not (1 <= item.page_number <= document.page_count):
                return _blocked(item, "pymupdf_page_render", "page number is outside parsed PDF denominator")
            page = document.load_page(item.page_number - 1)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0), alpha=False)
            pixmap.save(str(target))
    except Exception as exc:  # PyMuPDF exposes multiple runtime exception classes.
        return _blocked(item, "pymupdf_page_render", f"PDF page rendering failed: {exc}")
    return MaterializedVisual(
        manifestation_id=item.manifestation_id,
        source_container=item.container_path,
        source_member=None,
        source_page=item.page_number,
        output_path=str(target),
        output_sha256=_sha256_file(target),
        output_size_bytes=target.stat().st_size,
        adapter="pymupdf_page_render",
        state="PASS",
        reason="derived render; output hash is not source/PDF/page byte identity",
    )


def _blocked(item: EvidenceItem, adapter: str, reason: str) -> MaterializedVisual:
    return MaterializedVisual(
        manifestation_id=item.manifestation_id,
        source_container=item.container_path,
        source_member=item.member_path,
        source_page=item.page_number,
        output_path=None,
        output_sha256=None,
        output_size_bytes=None,
        adapter=adapter,
        state="BLOCKED",
        reason=reason,
    )


def materialize_visuals(manifest: EvidenceManifest, output_dir: str | Path) -> list[MaterializedVisual]:
    """Materialize every visual manifestation while preserving one output per item."""
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    results: list[MaterializedVisual] = []
    for item in manifest.items:
        if item.media_kind == "native_image":
            results.append(_materialize_native(item, destination))
        elif item.media_kind == "archive_image_member":
            results.append(_materialize_zip_member(item, destination))
        elif item.media_kind == "pdf_page_visual":
            results.append(_materialize_pdf_page(item, destination))
    return results
