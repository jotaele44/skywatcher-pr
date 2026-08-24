"""Benchmark-denominator and production-promotion gate for landscape classification."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BenchmarkState:
    status: str
    production_promotion_authorized: bool
    fixture_count: int
    positive_count: int
    negative_count: int
    verified_count: int
    unresolved_required: tuple[str, ...]
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "production_promotion_authorized": self.production_promotion_authorized,
            "fixture_count": self.fixture_count,
            "positive_count": self.positive_count,
            "negative_count": self.negative_count,
            "verified_count": self.verified_count,
            "unresolved_required": list(self.unresolved_required),
            "blockers": list(self.blockers),
        }


def _requirements(raw: Any) -> tuple[dict[str, int], tuple[str, ...]]:
    out: dict[str, int] = {}
    duplicates: list[str] = []
    for item in raw or ():
        name = str(item["class"])
        minimum = int(item.get("minimum_verified_fixtures", 1))
        if name in out:
            duplicates.append(name)
        out[name] = minimum
    return out, tuple(sorted(set(duplicates)))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repo_root(manifest_path: Path) -> Path:
    """Resolve the repository root for the committed data/satim_landscape manifest."""
    return manifest_path.parent.parent.parent


def evaluate_benchmark_manifest(path: str | Path) -> BenchmarkState:
    manifest_path = Path(path).resolve()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    fixtures = list(data.get("fixtures") or ())
    repo_root = _repo_root(manifest_path)

    required_positive, duplicate_positive = _requirements(data.get("required_positive_classes"))
    required_negative, duplicate_negative = _requirements(data.get("required_negative_classes"))
    required = dict(required_positive)
    overlap = set(required) & set(required_negative)
    required.update(required_negative)

    blockers: list[str] = []
    if duplicate_positive or duplicate_negative:
        blockers.append("duplicate class entries exist in benchmark requirements")
    if overlap:
        blockers.append(
            "classes cannot be both required positive and required negative: "
            + ", ".join(sorted(overlap))
        )

    role_counts = Counter(str(item.get("role") or "") for item in fixtures)
    fixture_count = len(fixtures)
    positive_count = role_counts["POSITIVE_REGRESSION"]
    negative_count = role_counts["NEGATIVE_CONTROL"]
    if positive_count + negative_count != fixture_count:
        blockers.append(
            "fixture role arithmetic does not close: "
            f"positive={positive_count} + negative={negative_count} != total={fixture_count}"
        )

    fixture_ids = [str(item.get("fixture_id") or "") for item in fixtures]
    if any(not fixture_id for fixture_id in fixture_ids):
        blockers.append("one or more fixtures lack fixture_id")
    if len(fixture_ids) != len(set(fixture_ids)):
        blockers.append("fixture_id uniqueness failed")

    raw_hashes = [str(item.get("sha256") or "") for item in fixtures]
    if any(not value for value in raw_hashes):
        blockers.append("one or more fixtures lack frozen raw-byte SHA256")
    nonempty_hashes = [value for value in raw_hashes if value]
    if len(nonempty_hashes) != len(set(nonempty_hashes)):
        blockers.append("duplicate raw-byte SHA256 cannot count as independent benchmark fixtures")

    verified_fixture_ids: set[str] = set()
    class_verified: Counter[str] = Counter()
    for item in fixtures:
        fixture_id = str(item.get("fixture_id") or "")
        class_name = str(item.get("class") or "")
        raw_rel = str(item.get("raw_path") or "")
        annotation_rel = str(item.get("annotation_path") or "")
        expected_sha = str(item.get("sha256") or "")

        if not class_name:
            blockers.append(f"fixture {fixture_id or '<missing>'} lacks class")
        if not raw_rel:
            blockers.append(f"fixture {fixture_id or '<missing>'} lacks raw_path")
        if not annotation_rel:
            blockers.append(f"fixture {fixture_id or '<missing>'} lacks annotation_path")

        raw_path = repo_root / raw_rel if raw_rel else None
        annotation_path = repo_root / annotation_rel if annotation_rel else None
        if raw_path is not None:
            if not raw_path.is_file():
                blockers.append(f"fixture {fixture_id} raw_path is missing")
            elif expected_sha and _sha256(raw_path) != expected_sha:
                blockers.append(f"fixture {fixture_id} raw-byte SHA256 mismatch")

        annotation: dict[str, Any] | None = None
        if annotation_path is not None:
            if not annotation_path.is_file():
                blockers.append(f"fixture {fixture_id} annotation_path is missing")
            else:
                try:
                    loaded = json.loads(annotation_path.read_text(encoding="utf-8"))
                    annotation = loaded if isinstance(loaded, dict) else None
                except (OSError, json.JSONDecodeError):
                    annotation = None
                if annotation is None:
                    blockers.append(f"fixture {fixture_id} annotation is not valid JSON object")

        label_status = str(item.get("label_status") or "")
        if label_status not in {"PROVISIONAL_HUMAN_ANNOTATION", "VERIFIED_GROUND_TRUTH"}:
            blockers.append(f"fixture {fixture_id} has unknown label_status {label_status!r}")

        if annotation is not None:
            if str(annotation.get("fixture_id") or "") != fixture_id:
                blockers.append(f"fixture {fixture_id} annotation fixture_id mismatch")
            annotation_block = annotation.get("annotation") or {}
            if not isinstance(annotation_block, dict):
                blockers.append(f"fixture {fixture_id} annotation block is invalid")
                annotation_block = {}
            if class_name and str(annotation_block.get("label") or "") != class_name:
                blockers.append(f"fixture {fixture_id} annotation class mismatch")
            if label_status and str(annotation_block.get("label_status") or "") != label_status:
                blockers.append(f"fixture {fixture_id} label_status disagrees with annotation")
            raw_source = annotation.get("raw_source") or {}
            if isinstance(raw_source, dict):
                if expected_sha and str(raw_source.get("sha256") or "") != expected_sha:
                    blockers.append(f"fixture {fixture_id} annotation SHA256 mismatch")
                if raw_rel and str(raw_source.get("stored_path") or "") != raw_rel:
                    blockers.append(f"fixture {fixture_id} annotation raw path mismatch")
            else:
                blockers.append(f"fixture {fixture_id} annotation raw_source is invalid")

        if label_status == "VERIFIED_GROUND_TRUTH":
            if annotation is None:
                blockers.append(f"verified fixture {fixture_id} has no valid annotation")
            elif str((annotation.get("annotation") or {}).get("label_status") or "") == "VERIFIED_GROUND_TRUTH":
                verified_fixture_ids.add(fixture_id)
                class_verified[class_name] += 1

    unresolved: list[str] = []
    for class_name, minimum in sorted(required.items()):
        have = class_verified[class_name]
        if have < minimum:
            unresolved.append(f"{class_name}:{have}/{minimum}")
    if unresolved:
        blockers.append("required verified fixture coverage is incomplete")

    blockers = list(dict.fromkeys(blockers))
    promotion = not blockers and not unresolved
    return BenchmarkState(
        status="PASS" if promotion else "BLOCKED",
        production_promotion_authorized=promotion,
        fixture_count=fixture_count,
        positive_count=positive_count,
        negative_count=negative_count,
        verified_count=len(verified_fixture_ids),
        unresolved_required=tuple(unresolved),
        blockers=tuple(blockers),
    )
