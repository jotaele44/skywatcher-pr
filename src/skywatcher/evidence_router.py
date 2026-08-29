"""Container-aware evidence ingestion and deterministic Skywatcher skill routing.

This module deliberately separates source/container manifestation identity from
analytical capability routing. A JPEG, a PDF page containing a screenshot,
and a ZIP member containing a screenshot may route to the same visual analysis
skills without becoming byte/logical-identical evidence.

The router is stdlib-first. It inventories/fingerprints what it can prove and
fails closed for unsupported or unreadable material. It does not perform OCR,
mission inference, georeferencing, or landing adjudication itself; those remain
owned by downstream Skywatcher skills.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import re
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".bmp", ".tif", ".tiff"}
STRUCTURED_EXTENSIONS = {".csv", ".json", ".geojson", ".kml", ".kmz", ".gpx", ".txt", ".log"}
ARCHIVE_EXTENSIONS = {".zip"}
PDF_EXTENSIONS = {".pdf"}

CERTIFICATION_STATES = {
    "PASS",
    "FAIL",
    "OPEN",
    "BLOCKED",
    "PROVISIONAL",
    "AUDIT_ONLY",
    "NONCANONICAL",
    "CANDIDATE_NOT_IDENTITY",
    "UNRESOLVED",
    "SUPERSEDED",
}


@dataclass(frozen=True)
class SkillSpec:
    skill_id: str
    capabilities: tuple[str, ...]
    module_hint: str
    prerequisites: tuple[str, ...] = ()
    advisory: bool = False


SKILL_REGISTRY: tuple[SkillSpec, ...] = (
    SkillSpec("RLSM", ("visual_evidence", "label_extraction", "map_context"), "run-rlsm.sh"),
    SkillSpec("FR24_SCREENSHOT_INVENTORY", ("visual_evidence", "provenance"), "fr24/screenshot_inventory.py"),
    SkillSpec("AIRCRAFT_IDENTITY", ("aircraft_identity",), "aircraft_intelligence.py"),
    SkillSpec("AIRCRAFT_MARKER_DETECTION", ("visual_evidence", "aircraft_marker"), "fr24/ui_segmenter.py"),
    SkillSpec("ROUTE_EXTRACTION", ("visual_evidence", "trajectory"), "fr24/route_extractor.py"),
    SkillSpec("FPIM", ("visual_evidence", "spatial_truth", "site_association"), "src/skywatcher/fpim"),
    SkillSpec("CORRIM", ("spatial_truth", "infrastructure_alignment", "site_association"), "src/skywatcher/corrim"),
    SkillSpec("SATIM", ("visual_evidence", "spatial_truth", "calibration"), "src/skywatcher/satim"),
    SkillSpec("TIMELINE", ("temporal_reconstruction",), "pipeline/timeline", advisory=True),
    SkillSpec("PATTERN", ("trajectory", "behavior", "mission_classification"), "pipeline/pattern", advisory=True),
    SkillSpec("ALTITUDE_VALIDITY", ("altitude_validity",), "fr24/event_export.py"),
    SkillSpec("STOP_HOVER_LANDING", ("trajectory", "landing_takeoff"), "fr24/event_export.py"),
    SkillSpec("SOURCE_IDENTITY_BINDING", ("provenance", "source_identity"), "scripts/reconcile_fr24_media_identity.py"),
)


@dataclass
class EvidenceItem:
    manifestation_id: str
    container_path: str
    member_path: str | None
    page_number: int | None
    media_kind: str
    extension: str
    size_bytes: int
    sha256: str | None
    mime_type: str | None
    status: str = "PASS"
    notes: list[str] = field(default_factory=list)


@dataclass
class EvidenceManifest:
    source_path: str
    source_sha256: str | None
    source_size_bytes: int | None
    container_kind: str
    items: list[EvidenceItem]
    contradictions: list[dict[str, str]] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)


@dataclass
class RoutePlan:
    manifest: EvidenceManifest
    capabilities: list[str]
    skills: list[dict[str, object]]
    gates: dict[str, str]
    safeguards: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "manifest": asdict(self.manifest),
            "capabilities": self.capabilities,
            "skills": self.skills,
            "gates": self.gates,
            "safeguards": self.safeguards,
        }


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _media_kind(path_name: str) -> str:
    ext = Path(path_name).suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return "native_image"
    if ext in PDF_EXTENSIONS:
        return "pdf"
    if ext in ARCHIVE_EXTENSIONS:
        return "archive"
    if ext in STRUCTURED_EXTENSIONS:
        return "structured_event_data"
    return "unknown"


def _item_id(*parts: object) -> str:
    canonical = "|".join("" if part is None else str(part) for part in parts)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def _pdf_page_count(data: bytes) -> int:
    """Return a conservative page count without pretending to parse PDF semantics.

    The regex excludes /Pages tree objects. Zero means the page denominator is
    unavailable and the caller must fail closed rather than inventing pages.
    """
    return len(re.findall(rb"/Type\s*/Page(?!s)\b", data))


def _native_item(path: Path) -> EvidenceItem:
    size = path.stat().st_size
    digest = _sha256_file(path)
    return EvidenceItem(
        manifestation_id=_item_id("native", path.name, digest),
        container_path=str(path),
        member_path=None,
        page_number=None,
        media_kind="native_image",
        extension=path.suffix.lower(),
        size_bytes=size,
        sha256=digest,
        mime_type=mimetypes.guess_type(path.name)[0],
    )


def _structured_item(path: Path) -> EvidenceItem:
    size = path.stat().st_size
    digest = _sha256_file(path)
    return EvidenceItem(
        manifestation_id=_item_id("structured", path.name, digest),
        container_path=str(path),
        member_path=None,
        page_number=None,
        media_kind="structured_event_data",
        extension=path.suffix.lower(),
        size_bytes=size,
        sha256=digest,
        mime_type=mimetypes.guess_type(path.name)[0],
    )


def _pdf_items(path: Path, data: bytes) -> tuple[list[EvidenceItem], list[str]]:
    page_count = _pdf_page_count(data)
    if page_count == 0:
        return [], ["PDF page denominator could not be established by stdlib inventory"]
    items = []
    for page in range(1, page_count + 1):
        items.append(
            EvidenceItem(
                manifestation_id=_item_id("pdf_page", path.name, page, _sha256_bytes(data)),
                container_path=str(path),
                member_path=None,
                page_number=page,
                media_kind="pdf_page_visual",
                extension=".pdf",
                size_bytes=len(data),
                sha256=None,
                mime_type="application/pdf",
                status="PROVISIONAL",
                notes=["page manifestation is distinct from PDF byte identity; render/image extraction is downstream"],
            )
        )
    return items, []


def _zip_items(path: Path) -> tuple[list[EvidenceItem], list[str], list[dict[str, str]]]:
    items: list[EvidenceItem] = []
    unresolved: list[str] = []
    contradictions: list[dict[str, str]] = []
    seen_payloads: dict[tuple[int, str], str] = {}
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            try:
                payload = archive.read(info.filename)
            except (RuntimeError, OSError, zipfile.BadZipFile) as exc:
                unresolved.append(f"unreadable ZIP member {info.filename}: {exc}")
                continue
            digest = _sha256_bytes(payload)
            kind = _media_kind(info.filename)
            key = (len(payload), digest)
            if key in seen_payloads:
                contradictions.append(
                    {
                        "class": "BYTE",
                        "state": "PASS",
                        "observation": "duplicate payload at different archive path",
                        "a": seen_payloads[key],
                        "b": info.filename,
                    }
                )
            else:
                seen_payloads[key] = info.filename
            items.append(
                EvidenceItem(
                    manifestation_id=_item_id("zip_member", path.name, info.filename, digest),
                    container_path=str(path),
                    member_path=info.filename,
                    page_number=None,
                    media_kind=("archive_image_member" if kind == "native_image" else kind),
                    extension=Path(info.filename).suffix.lower(),
                    size_bytes=len(payload),
                    sha256=digest,
                    mime_type=mimetypes.guess_type(info.filename)[0],
                )
            )
    return items, unresolved, contradictions


def inspect_path(path: str | Path) -> EvidenceManifest:
    source = Path(path)
    if not source.exists() or not source.is_file():
        return EvidenceManifest(
            source_path=str(source),
            source_sha256=None,
            source_size_bytes=None,
            container_kind="missing",
            items=[],
            unresolved=["source file is missing or not a regular file"],
        )

    source_sha = _sha256_file(source)
    source_size = source.stat().st_size
    kind = _media_kind(source.name)
    items: list[EvidenceItem] = []
    unresolved: list[str] = []
    contradictions: list[dict[str, str]] = []

    try:
        if kind == "native_image":
            items = [_native_item(source)]
        elif kind == "structured_event_data":
            items = [_structured_item(source)]
        elif kind == "pdf":
            items, unresolved = _pdf_items(source, source.read_bytes())
        elif kind == "archive":
            items, unresolved, contradictions = _zip_items(source)
        else:
            unresolved.append(f"unsupported outer container type: {source.suffix.lower() or '<none>'}")
    except (OSError, zipfile.BadZipFile) as exc:
        unresolved.append(f"container inspection failed: {exc}")

    return EvidenceManifest(
        source_path=str(source),
        source_sha256=source_sha,
        source_size_bytes=source_size,
        container_kind=kind,
        items=items,
        contradictions=contradictions,
        unresolved=unresolved,
    )


def merge_manifests(manifests: Sequence[EvidenceManifest]) -> EvidenceManifest:
    items = [item for manifest in manifests for item in manifest.items]
    contradictions = [c for manifest in manifests for c in manifest.contradictions]
    unresolved = [u for manifest in manifests for u in manifest.unresolved]
    source_fingerprint = _sha256_bytes(
        "\n".join(sorted(filter(None, (m.source_sha256 for m in manifests)))).encode("utf-8")
    )
    return EvidenceManifest(
        source_path="<mixed-batch>",
        source_sha256=source_fingerprint,
        source_size_bytes=sum(m.source_size_bytes or 0 for m in manifests),
        container_kind="mixed_batch",
        items=items,
        contradictions=contradictions,
        unresolved=unresolved,
    )


def _capabilities_for(manifest: EvidenceManifest) -> set[str]:
    caps = {"provenance", "source_identity"}
    kinds = {item.media_kind for item in manifest.items}
    if kinds & {"native_image", "archive_image_member", "pdf_page_visual"}:
        caps.update(
            {
                "visual_evidence",
                "label_extraction",
                "map_context",
                "aircraft_identity",
                "aircraft_marker",
                "trajectory",
                "spatial_truth",
                "site_association",
                "infrastructure_alignment",
                "temporal_reconstruction",
                "altitude_validity",
                "landing_takeoff",
                "behavior",
                "mission_classification",
                "calibration",
            }
        )
    if "structured_event_data" in kinds:
        caps.update({"aircraft_identity", "trajectory", "temporal_reconstruction", "altitude_validity", "behavior"})
    return caps


def build_route_plan(manifest: EvidenceManifest) -> RoutePlan:
    capabilities = _capabilities_for(manifest)
    selected: list[dict[str, object]] = []
    for spec in SKILL_REGISTRY:
        matched = sorted(capabilities.intersection(spec.capabilities))
        if not matched:
            continue
        selected.append(
            {
                "skill_id": spec.skill_id,
                "module_hint": spec.module_hint,
                "matched_capabilities": matched,
                "prerequisites": list(spec.prerequisites),
                "advisory": spec.advisory,
                "state": "PROVISIONAL" if spec.advisory else "PASS",
            }
        )

    visual_items = [
        item for item in manifest.items if item.media_kind in {"native_image", "archive_image_member", "pdf_page_visual"}
    ]
    gates = {
        "SOURCE_FREEZE": "PASS" if manifest.source_sha256 else "BLOCKED",
        "DENOMINATOR": "PASS" if manifest.items and not manifest.unresolved else ("OPEN" if manifest.items else "BLOCKED"),
        "VISUAL_ROUTING": "PASS" if visual_items else "OPEN",
        "CONTAINER_EQUIVALENCE": "PASS" if visual_items else "OPEN",
        "ANALYTICAL_CERTIFICATION": "OPEN",
    }
    safeguards = [
        "BAROMETRIC_ZERO_TRAP: 0 ft must not imply ON_GROUND",
        "STOP_NOT_LANDING: 0 mph/track termination must not certify landing",
        "POI_PROXIMITY_FALSE_TARGET: nearest/prominent label is discovery only",
        "RENDERED_TRAIL_NOT_RAW_TRAJECTORY",
        "OWNER_OPERATOR_MISSION_SEPARATION",
        "CORRIDOR_ALIGNMENT_NOT_MISSION_IDENTITY",
        "PRESERVE_RAW_NORMALIZED_CANONICAL_SEPARATELY",
        "FAIL_CLOSED_ON_NULL_TIE_DUPLICATE_OR_UNREADABLE_EVIDENCE",
    ]
    return RoutePlan(manifest, sorted(capabilities), selected, gates, safeguards)


def route_paths(paths: Iterable[str | Path]) -> RoutePlan:
    manifests = [inspect_path(path) for path in paths]
    manifest = manifests[0] if len(manifests) == 1 else merge_manifests(manifests)
    return build_route_plan(manifest)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inventory evidence containers and emit a Skywatcher skill route plan")
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    plan = route_paths(args.inputs)
    payload = json.dumps(plan.to_dict(), indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0 if plan.gates["DENOMINATOR"] != "BLOCKED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
