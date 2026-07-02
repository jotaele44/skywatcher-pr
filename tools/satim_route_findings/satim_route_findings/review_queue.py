"""Manual review queue generation for route findings."""

from __future__ import annotations

from collections import Counter

from .util import safe_float, stable_id


def _blank(value: object) -> bool:
    return value is None or str(value).strip() == ""


def build_review_queue(
    track_rows: tuple[dict[str, str], ...],
    error_rows: tuple[dict[str, str], ...],
    low_confidence_threshold: float = 50.0,
    sparse_source_threshold: int = 3,
) -> list[dict[str, object]]:
    """Build a deterministic review queue from track and error ledgers."""

    review_rows: list[dict[str, object]] = []
    source_counts = Counter(row.get("source", "") for row in track_rows)

    for index, row in enumerate(track_rows):
        source = row.get("source", "")
        missing = [name for name in ("latitude", "longitude", "source") if _blank(row.get(name))]
        if missing:
            review_rows.append(
                {
                    "review_id": stable_id("review", "missing", index, source, ",".join(missing)),
                    "source": source,
                    "reason": "missing_required_field",
                    "detail": ",".join(missing),
                    "severity": "high",
                }
            )
        score = safe_float(row.get("verification_score"), default=100.0)
        if score < low_confidence_threshold:
            review_rows.append(
                {
                    "review_id": stable_id("review", "low_confidence", index, source, score),
                    "source": source,
                    "reason": "low_verification_score",
                    "detail": str(score),
                    "severity": "medium",
                }
            )

    for source, count in sorted(source_counts.items()):
        if source and count < sparse_source_threshold:
            review_rows.append(
                {
                    "review_id": stable_id("review", "sparse", source, count),
                    "source": source,
                    "reason": "sparse_source_geometry",
                    "detail": str(count),
                    "severity": "low",
                }
            )

    for index, row in enumerate(error_rows):
        if any(not _blank(value) for value in row.values()):
            review_rows.append(
                {
                    "review_id": stable_id("review", "error", index, row.get("source"), row.get("stage"), row.get("error_type")),
                    "source": row.get("source", ""),
                    "reason": "processing_error",
                    "detail": f"{row.get('stage', '')}:{row.get('error_type', '')}:{row.get('message', '')}",
                    "severity": "high",
                }
            )

    return sorted(review_rows, key=lambda row: (str(row["severity"]), str(row["reason"]), str(row["source"]), str(row["review_id"])))
