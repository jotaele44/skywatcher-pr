"""Benchmark denominator, confusion metrics and production gate for landscape classification."""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

NEGATIVE_CONTROL_CLASSES = (
    "LANDSLIDE_OR_SCARP",
    "CONSTRUCTION_GRADING",
    "UTILITY_CORRIDOR",
    "ROAD_CUT",
    "QUARRY_OR_BORROW",
    "EXPOSED_RIVER_SEDIMENT",
    "HURRICANE_BLOWDOWN",
    "SOLAR_ARRAY",
    "LOGGING_CLEARING",
    "ABANDONED_BUILDING_PAD",
    "PASTURE_OR_LAWN",
    "NATURAL_SPARSE_VEGETATION",
)
EXPECTED_COMPETING_CLASSES = ("AGRICULTURAL_MOSAIC",) + NEGATIVE_CONTROL_CLASSES


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
    calibration_count: int = 0
    holdout_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            key: list(value) if isinstance(value, tuple) else value
            for key, value in self.__dict__.items()
        }


@dataclass(frozen=True)
class BenchmarkReport:
    status: str
    tp: int
    fp: int
    tn: int
    fn: int
    precision: float | None
    recall: float | None
    specificity: float | None
    f1: float | None
    balanced_accuracy: float | None
    unresolved_count: int
    tied_count: int
    null_competitor_count: int
    per_negative_class_confusion: dict[str, dict[str, int]]
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = self.__dict__.copy()
        payload["blockers"] = list(self.blockers)
        return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _requirements(raw: Any) -> tuple[dict[str, int], tuple[str, ...]]:
    output: dict[str, int] = {}
    duplicates: list[str] = []
    for item in raw or ():
        name = str(item["class"])
        minimum = int(item.get("minimum_verified_fixtures", 1))
        if name in output:
            duplicates.append(name)
        output[name] = minimum
    return output, tuple(sorted(set(duplicates)))


def _repo_root(manifest_path: Path) -> Path:
    return manifest_path.parent.parent.parent


def evaluate_benchmark_manifest(path: str | Path) -> BenchmarkState:
    manifest_path = Path(path).resolve()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    fixtures = list(data.get("fixtures") or ())
    repo_root = _repo_root(manifest_path)

    required_positive, duplicate_positive = _requirements(data.get("required_positive_classes"))
    required_negative, duplicate_negative = _requirements(data.get("required_negative_classes"))
    required = {**required_positive, **required_negative}
    blockers: list[str] = []

    if duplicate_positive or duplicate_negative:
        blockers.append("duplicate class entries exist in benchmark requirements")
    if set(required_positive) & set(required_negative):
        blockers.append("class appears in positive and negative requirements")

    roles = Counter(str(item.get("role") or "") for item in fixtures)
    positive_count = roles["POSITIVE_REGRESSION"]
    negative_count = roles["NEGATIVE_CONTROL"]
    if positive_count + negative_count != len(fixtures):
        blockers.append("fixture role arithmetic does not close")

    fixture_ids = [str(item.get("fixture_id") or "") for item in fixtures]
    hashes = [str(item.get("sha256") or "") for item in fixtures]
    if any(not value for value in fixture_ids):
        blockers.append("one or more fixtures lack fixture_id")
    if len(fixture_ids) != len(set(fixture_ids)):
        blockers.append("fixture_id uniqueness failed")
    if any(not value for value in hashes):
        blockers.append("one or more fixtures lack frozen raw-byte SHA256")
    nonempty_hashes = [value for value in hashes if value]
    if len(nonempty_hashes) != len(set(nonempty_hashes)):
        blockers.append("duplicate raw-byte SHA256 cannot count as independent fixtures")

    calibration_ids = {
        str(item.get("fixture_id"))
        for item in fixtures
        if item.get("split") == "CALIBRATION"
    }
    holdout_ids = {
        str(item.get("fixture_id"))
        for item in fixtures
        if item.get("split") == "HOLDOUT"
    }
    calibration_hashes = {
        str(item.get("sha256"))
        for item in fixtures
        if item.get("split") == "CALIBRATION"
    }
    holdout_hashes = {
        str(item.get("sha256"))
        for item in fixtures
        if item.get("split") == "HOLDOUT"
    }
    if calibration_ids & holdout_ids:
        blockers.append("calibration/holdout fixture_id leakage")
    if calibration_hashes & holdout_hashes:
        blockers.append("calibration/holdout raw-byte SHA256 leakage")

    verified = Counter()
    verified_ids: set[str] = set()
    for item in fixtures:
        fixture_id = str(item.get("fixture_id") or "")
        class_name = str(item.get("class") or "")
        raw_rel = str(item.get("raw_path") or "")
        annotation_rel = str(item.get("annotation_path") or "")
        expected_sha = str(item.get("sha256") or "")

        if item.get("split") not in {"CALIBRATION", "HOLDOUT"}:
            blockers.append(f"fixture {fixture_id} has invalid split")

        raw_path = repo_root / raw_rel if raw_rel else None
        annotation_path = repo_root / annotation_rel if annotation_rel else None
        if raw_path is None or not raw_path.is_file():
            blockers.append(f"fixture {fixture_id} raw_path is missing")
        elif expected_sha and _sha256(raw_path) != expected_sha:
            blockers.append(f"fixture {fixture_id} raw-byte SHA256 mismatch")

        annotation: dict[str, Any] | None = None
        if annotation_path is None or not annotation_path.is_file():
            blockers.append(f"fixture {fixture_id} annotation_path is missing")
        else:
            try:
                loaded = json.loads(annotation_path.read_text(encoding="utf-8"))
                annotation = loaded if isinstance(loaded, dict) else None
            except (OSError, json.JSONDecodeError):
                annotation = None
            if annotation is None:
                blockers.append(f"fixture {fixture_id} annotation invalid JSON")

        label_status = str(item.get("label_status") or "")
        if label_status not in {"PROVISIONAL_HUMAN_ANNOTATION", "VERIFIED_GROUND_TRUTH"}:
            blockers.append(f"fixture {fixture_id} invalid label_status")

        if annotation is not None:
            if str(annotation.get("fixture_id") or "") != fixture_id:
                blockers.append(f"fixture {fixture_id} annotation fixture_id mismatch")
            annotation_block = annotation.get("annotation") or {}
            raw_source = annotation.get("raw_source") or {}
            if str(annotation_block.get("label") or "") != class_name:
                blockers.append(f"fixture {fixture_id} annotation class mismatch")
            if str(annotation_block.get("label_status") or "") != label_status:
                blockers.append(f"fixture {fixture_id} label_status disagreement")
            if str(raw_source.get("sha256") or "") != expected_sha:
                blockers.append(f"fixture {fixture_id} annotation SHA256 mismatch")

        if (
            label_status == "VERIFIED_GROUND_TRUTH"
            and annotation is not None
            and str((annotation.get("annotation") or {}).get("label_status") or "")
            == label_status
        ):
            verified_ids.add(fixture_id)
            verified[class_name] += 1

    unresolved_required: list[str] = []
    for class_name, minimum in sorted(required.items()):
        if verified[class_name] < minimum:
            unresolved_required.append(f"{class_name}:{verified[class_name]}/{minimum}")
    if unresolved_required:
        blockers.append("required verified fixture coverage is incomplete")

    holdout_classes = {
        str(item.get("class"))
        for item in fixtures
        if item.get("split") == "HOLDOUT"
        and item.get("label_status") == "VERIFIED_GROUND_TRUTH"
    }
    if "AGRICULTURAL_MOSAIC" not in holdout_classes:
        blockers.append("verified agricultural HOLDOUT fixture is missing")
    for class_name in NEGATIVE_CONTROL_CLASSES:
        if class_name not in holdout_classes:
            blockers.append(f"verified HOLDOUT negative class is missing: {class_name}")

    blockers = list(dict.fromkeys(blockers))
    promotion = not blockers and not unresolved_required
    return BenchmarkState(
        status="PASS" if promotion else "BLOCKED",
        production_promotion_authorized=promotion,
        fixture_count=len(fixtures),
        positive_count=positive_count,
        negative_count=negative_count,
        verified_count=len(verified_ids),
        unresolved_required=tuple(unresolved_required),
        blockers=tuple(blockers),
        calibration_count=len(calibration_ids),
        holdout_count=len(holdout_ids),
    )


def evaluate_predictions(
    rows: Iterable[dict[str, Any]], *, calibration_status: str
) -> BenchmarkReport:
    tp = fp = tn = fn = 0
    unresolved_count = tied_count = null_competitor_count = 0
    blockers: list[str] = []
    per_class = defaultdict(
        lambda: {"agriculture_pred": 0, "correct_negative": 0, "unresolved": 0}
    )
    total = 0

    for row in rows:
        total += 1
        truth = str(row.get("truth_class") or "")
        assessment = row.get("assessment") or {}
        competitors = assessment.get("competing_classes") or []
        names = [item.get("class_name") for item in competitors]
        if len(names) != len(set(names)):
            blockers.append("duplicate competing class in prediction vector")
        missing = set(EXPECTED_COMPETING_CLASSES) - set(names)
        if missing:
            blockers.append("prediction missing competing classes: " + ", ".join(sorted(missing)))
        null_competitor_count += sum(item.get("score") is None for item in competitors)

        terminal = str(assessment.get("terminal_state") or "")
        if terminal == "REVIEW_UNRESOLVED":
            tied_count += 1
        if terminal in {"REVIEW_UNRESOLVED", "UNRESOLVED"}:
            unresolved_count += 1

        predicted_positive = (
            terminal == "CANDIDATE_NOT_IDENTITY"
            and assessment.get("top_class") == "AGRICULTURAL_MOSAIC"
        )
        actual_positive = truth == "AGRICULTURAL_MOSAIC"
        if actual_positive and predicted_positive:
            tp += 1
        elif actual_positive:
            fn += 1
        elif predicted_positive:
            fp += 1
            per_class[truth]["agriculture_pred"] += 1
        else:
            tn += 1
            if terminal in {"REVIEW_UNRESOLVED", "UNRESOLVED"}:
                per_class[truth]["unresolved"] += 1
            else:
                per_class[truth]["correct_negative"] += 1

    if tp + fp + tn + fn != total:
        blockers.append("prediction arithmetic does not close")

    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    specificity = tn / (tn + fp) if tn + fp else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None
        and recall is not None
        and precision + recall
        else None
    )
    balanced_accuracy = (
        (recall + specificity) / 2
        if recall is not None and specificity is not None
        else None
    )

    if calibration_status != "VALIDATED":
        blockers.append("calibration profile is not VALIDATED")
    if fp:
        blockers.append(f"holdout false positives must be zero: {fp}")
    if fn:
        blockers.append(f"holdout false negatives must be zero: {fn}")
    if unresolved_count:
        blockers.append(
            f"holdout unresolved/tied residue must be zero: {unresolved_count}"
        )

    blockers = list(dict.fromkeys(blockers))
    return BenchmarkReport(
        status="PASS" if not blockers else "BLOCKED",
        tp=tp,
        fp=fp,
        tn=tn,
        fn=fn,
        precision=precision,
        recall=recall,
        specificity=specificity,
        f1=f1,
        balanced_accuracy=balanced_accuracy,
        unresolved_count=unresolved_count,
        tied_count=tied_count,
        null_competitor_count=null_competitor_count,
        per_negative_class_confusion=dict(per_class),
        blockers=tuple(blockers),
    )
