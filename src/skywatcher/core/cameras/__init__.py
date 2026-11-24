"""Sky Cameras: a curated catalog of public Puerto Rico live cameras plus a moderated
community contribution queue. See docs/SKY_CAMERAS.md."""

from .catalog import (
    Camera,
    camera_from_dict,
    coverage_summary,
    filter_cameras,
    load_catalog,
    load_municipios,
    load_status,
)
from .submissions import (
    SubmissionInput,
    SubmissionStore,
    community_camera,
    submission_receipt,
)
from .validation import (
    CATEGORIES,
    LICENSES,
    SubmissionError,
    embed_url,
    parse_embed,
    sniff_video,
    validate_https_url,
)

__all__ = [
    "CATEGORIES",
    "LICENSES",
    "Camera",
    "SubmissionError",
    "SubmissionInput",
    "SubmissionStore",
    "camera_from_dict",
    "community_camera",
    "coverage_summary",
    "embed_url",
    "filter_cameras",
    "load_catalog",
    "load_municipios",
    "load_status",
    "parse_embed",
    "sniff_video",
    "submission_receipt",
    "validate_https_url",
]
