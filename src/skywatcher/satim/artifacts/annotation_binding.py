from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

UNMARKED_POLICY = "UNKNOWN"

COLOR_CANDIDATES: dict[str, tuple[str, ...]] = {
    "RED": ("SATIM-A01",),
    "BLUE": ("SATIM-A03", "SATIM-A05"),
    "YELLOW": ("SATIM-A09", "SATIM-A02", "REAL_SHADOW", "UNRESOLVED"),
}

ALLOWED_MACHINE_STATES = {
    "SUPPORTED",
    "PARTIAL",
    "UNRESOLVED",
    "CONTRADICTED",
}


@dataclass(frozen=True)
class AnnotationPrimitive:
    roi_id: str
    image_id: str
    color: str
    geometry: Mapping[str, Any]
    annotation_pixels: int

    @property
    def candidate_classes(self) -> tuple[str, ...]:
        try:
            return COLOR_CANDIDATES[self.color]
        except KeyError as exc:
            raise ValueError(f"unsupported annotation color: {self.color}") from exc


@dataclass(frozen=True)
class AgreementSummary:
    denominator: int
    supported: int
    partial: int
    unresolved: int
    contradicted: int
    missing_results: int
    unmarked_policy: str = UNMARKED_POLICY

    @property
    def arithmetic_closed(self) -> bool:
        return self.denominator == (
            self.supported
            + self.partial
            + self.unresolved
            + self.contradicted
            + self.missing_results
        )

    @property
    def certification_ready(self) -> bool:
        return self.arithmetic_closed and self.unresolved == 0 and self.missing_results == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "denominator": self.denominator,
            "supported": self.supported,
            "partial": self.partial,
            "unresolved": self.unresolved,
            "contradicted": self.contradicted,
            "missing_results": self.missing_results,
            "unmarked_policy": self.unmarked_policy,
            "arithmetic_closed": self.arithmetic_closed,
            "certification_ready": self.certification_ready,
        }


def assert_pristine_measurement_source(
    *,
    pristine_sha256: str,
    measurement_sha256: str,
    annotation_sha256: str,
) -> None:
    """Fail closed if measurements came from annotated rather than pristine bytes."""
    if not pristine_sha256 or not measurement_sha256 or not annotation_sha256:
        raise ValueError("all SHA-256 bindings are required")
    if measurement_sha256 != pristine_sha256:
        raise ValueError("measurement bytes are not the bound pristine source")
    if measurement_sha256 == annotation_sha256:
        raise ValueError("annotation bytes must never be used as measurement bytes")


def validate_positive_only_annotations(
    primitives: Iterable[AnnotationPrimitive],
) -> tuple[AnnotationPrimitive, ...]:
    rows = tuple(primitives)
    ids = [row.roi_id for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate ROI ids are not allowed")
    for row in rows:
        if row.color not in COLOR_CANDIDATES:
            raise ValueError(f"unsupported annotation color: {row.color}")
        if row.annotation_pixels <= 0:
            raise ValueError(f"ROI {row.roi_id} has no annotation pixels")
    return rows


def summarize_positive_only_agreement(
    primitives: Iterable[AnnotationPrimitive],
    machine_states: Mapping[str, str],
) -> AgreementSummary:
    """Summarize explicit positive annotations while unmarked regions stay UNKNOWN.

    This function intentionally never emits true-negative or false-negative counts.
    Absence of markup is not a negative label under the positive-only contract.
    """
    rows = validate_positive_only_annotations(primitives)
    roi_ids = {row.roi_id for row in rows}
    extras = set(machine_states) - roi_ids
    if extras:
        raise ValueError(f"machine results contain unknown ROI ids: {sorted(extras)}")

    counts: Counter[str] = Counter()
    missing = 0
    for row in rows:
        state = machine_states.get(row.roi_id)
        if state is None:
            missing += 1
            continue
        if state not in ALLOWED_MACHINE_STATES:
            raise ValueError(f"unsupported machine state for {row.roi_id}: {state}")
        counts[state] += 1

    result = AgreementSummary(
        denominator=len(rows),
        supported=counts["SUPPORTED"],
        partial=counts["PARTIAL"],
        unresolved=counts["UNRESOLVED"],
        contradicted=counts["CONTRADICTED"],
        missing_results=missing,
    )
    if not result.arithmetic_closed:
        raise AssertionError("positive-only agreement arithmetic did not close")
    return result


def annotation_pixel_accounting(
    *,
    detected_color_pixels: int,
    accepted_annotation_pixels: int,
    rejected_source_color_pixels: int,
) -> dict[str, Any]:
    """Close color-segmentation arithmetic without treating source colors as labels."""
    values = (
        detected_color_pixels,
        accepted_annotation_pixels,
        rejected_source_color_pixels,
    )
    if any(value < 0 for value in values):
        raise ValueError("pixel counts must be non-negative")
    residue = detected_color_pixels - accepted_annotation_pixels - rejected_source_color_pixels
    return {
        "detected_color_pixels": detected_color_pixels,
        "accepted_annotation_pixels": accepted_annotation_pixels,
        "rejected_source_color_pixels": rejected_source_color_pixels,
        "unexplained_pixels": residue,
        "arithmetic_closed": residue == 0,
    }
