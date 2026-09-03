"""REVIEW-STATUS HANDLING (mission responsibility 14)

Canonical review-status vocabulary and the Skywatcher<->Spiderweb crosswalk
(contradiction C4), plus re-exports of the existing review-state helpers
(``fr24.review_state``, ``fr24.review_queue_builder``) which are pure stdlib.

The crosswalk is the single source of truth used by the bridge serializer to
translate Skywatcher review dispositions into the Spiderweb review vocabulary.
"""

from __future__ import annotations

from fr24.review_queue_builder import (
    DISALLOWED_REVIEW_STATUSES,
    REVIEW_REQUIRED_STATUSES,
    build_review_queue,
)
from fr24.review_state import (
    build_local_state_payload,
    read_local_state_json,
    utc_now_iso,
    validate_local_state_payload,
    write_local_state_json,
)

__all__ = [
    "build_local_state_payload",
    "validate_local_state_payload",
    "read_local_state_json",
    "write_local_state_json",
    "utc_now_iso",
    "build_review_queue",
    "DISALLOWED_REVIEW_STATUSES",
    "REVIEW_REQUIRED_STATUSES",
    "SKYWATCHER_REVIEW_STATUSES",
    "SPIDERWEB_REVIEW_STATUSES",
    "REVIEW_STATUS_CROSSWALK",
    "to_spiderweb_review_status",
]

# Skywatcher canonical airspace/endpoint review vocabulary.
SKYWATCHER_REVIEW_STATUSES = (
    "draft",
    "needs_review",
    "reviewed",
    "promoted",
    "rejected",
)

# Spiderweb spatial review vocabulary.
SPIDERWEB_REVIEW_STATUSES = (
    "unreviewed",
    "reviewing",
    "approved",
    "rejected",
)

# Resolution of contradiction C4: an explicit, lossless-where-possible mapping
# from Skywatcher review dispositions to the Spiderweb vocabulary. "promoted"
# (Skywatcher's terminal accept) maps to "approved" (Spiderweb's terminal
# accept); "draft"/"needs_review" collapse to "unreviewed"/"reviewing".
REVIEW_STATUS_CROSSWALK = {
    "draft": "unreviewed",
    "needs_review": "reviewing",
    "reviewed": "reviewing",
    "promoted": "approved",
    "rejected": "rejected",
}


def to_spiderweb_review_status(skywatcher_status: str) -> str:
    """Translate a Skywatcher review status into the Spiderweb vocabulary.

    Unknown values fall back to ``"unreviewed"`` (fail-safe: never auto-approve).
    """
    return REVIEW_STATUS_CROSSWALK.get(str(skywatcher_status), "unreviewed")
