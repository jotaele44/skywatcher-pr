"""Shared deterministic helpers for ADR 0006 S06 evidence projection."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from pathlib import PurePosixPath
from typing import Any

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
_RUN_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_TRIAL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]+$")
_ARTIFACT_ID_RE = re.compile(r"^artifact-sha256-([0-9a-f]{64})$")
_SECRET_KEY_RE = re.compile(
    r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret|authorization|private[_-]?key)",
    re.IGNORECASE,
)
_SECRET_VALUE_RE = re.compile(
    r"(?:^|\b)(?:bearer\s+[A-Za-z0-9._~+/=-]{8,}|sk-[A-Za-z0-9_-]{12,}|"
    r"anthropic_api_key\s*=|openai_api_key\s*=|-----BEGIN [A-Z ]*PRIVATE KEY-----)",
    re.IGNORECASE,
)
_PATH_KEY_RE = re.compile(r"(?:^|_)(?:path|dir|file|filename|locator)(?:$|_)", re.IGNORECASE)


class DualRunProjectionError(ValueError):
    """Raised when supplied evidence cannot be projected without invention."""


def canonical_json(value: Any) -> str:
    """Return stable JSON used by TheHub H08 content identities."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def canonical_json_bytes(value: Any) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


def require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise DualRunProjectionError(f"{label} must be an object")
    return dict(value)


def require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise DualRunProjectionError(f"{label} must be an array")
    return value


def ensure_sha256(value: Any, label: str) -> str:
    text = str(value or "")
    if not _SHA256_RE.fullmatch(text):
        raise DualRunProjectionError(f"{label} must be lowercase SHA-256")
    return text


def ensure_revision(value: Any, label: str) -> str:
    text = str(value or "")
    if not _REVISION_RE.fullmatch(text):
        raise DualRunProjectionError(f"{label} must be lowercase 40-character SHA")
    return text


def ensure_run_id(value: Any) -> str:
    text = str(value or "")
    if not _RUN_ID_RE.fullmatch(text):
        raise DualRunProjectionError("execution receipt run_id must be 32 lowercase hex")
    return text


def ensure_trial_id(value: Any, label: str = "trial_id") -> str:
    """Require one H08-compatible, filesystem-safe path component."""
    text = str(value or "")
    if not _TRIAL_ID_RE.fullmatch(text):
        raise DualRunProjectionError(
            f"{label} must match ^[a-z0-9][a-z0-9._-]+$"
        )
    cleaned = clean_relative_path(text, label)
    if len(PurePosixPath(cleaned).parts) != 1:
        raise DualRunProjectionError(f"{label} must be one path component")
    return cleaned


def artifact_sha256(artifact_id: Any) -> str:
    text = str(artifact_id or "")
    match = _ARTIFACT_ID_RE.fullmatch(text)
    if not match:
        raise DualRunProjectionError("artifact_id must be artifact-sha256-<sha256>")
    return match.group(1)


def unique_index(
    records: Iterable[Mapping[str, Any]], key: str, label: str
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for raw in records:
        record = require_mapping(raw, label)
        identity = str(record.get(key) or "")
        if not identity:
            raise DualRunProjectionError(f"{label} missing {key}")
        if identity in result:
            raise DualRunProjectionError(f"duplicate {label} {key}: {identity}")
        result[identity] = record
    return result


def clean_relative_path(value: Any, label: str) -> str:
    text = str(value or "")
    if not text or "\\" in text or text.startswith(("/", "~")):
        raise DualRunProjectionError(f"{label} must be a non-empty relative POSIX path")
    if re.match(r"^[A-Za-z]:", text):
        raise DualRunProjectionError(f"{label} must not be an absolute Windows path")
    path = PurePosixPath(text)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise DualRunProjectionError(f"{label} escapes the package root")
    return path.as_posix()


def reject_secret_or_unsafe_paths(value: Any, *, path: str = "record") -> None:
    """Fail closed on secret-shaped content and serialized workstation paths."""
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key)
            if _SECRET_KEY_RE.search(key):
                raise DualRunProjectionError(f"secret-shaped key denied at {path}.{key}")
            if _PATH_KEY_RE.search(key) and isinstance(item, str):
                clean_relative_path(item, f"{path}.{key}")
            reject_secret_or_unsafe_paths(item, path=f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            reject_secret_or_unsafe_paths(item, path=f"{path}[{index}]")
        return
    if isinstance(value, str) and _SECRET_VALUE_RE.search(value):
        raise DualRunProjectionError(f"secret-shaped value denied at {path}")


def compute_source_set_sha256(campaign: Mapping[str, Any]) -> str:
    records = require_list(campaign.get("source_artifacts"), "campaign source_artifacts")
    indexed = unique_index(records, "artifact_id", "campaign source artifact")
    normalized: list[tuple[str, str, str]] = []
    for artifact_id in sorted(indexed):
        record = indexed[artifact_id]
        digest = ensure_sha256(record.get("sha256"), "source artifact sha256")
        if artifact_sha256(artifact_id) != digest:
            raise DualRunProjectionError("source artifact ID and SHA-256 disagree")
        normalized.append((artifact_id, digest, str(record.get("classification") or "")))
    return sha256_json(normalized)


def compute_pins_sha256(campaign: Mapping[str, Any]) -> str:
    return sha256_json(require_mapping(campaign.get("pins"), "campaign pins"))


def canonical_campaign_identity_payload(campaign: Mapping[str, Any]) -> dict[str, Any]:
    """Canonicalize H08 arrays that are semantic sets before identity hashing."""
    payload = dict(campaign)
    payload.pop("campaign_id", None)

    sources = unique_index(
        require_list(payload.get("source_artifacts"), "campaign source_artifacts"),
        "artifact_id",
        "campaign source artifact",
    )
    payload["source_artifacts"] = [sources[key] for key in sorted(sources)]

    trials = unique_index(
        require_list(payload.get("trials"), "campaign trials"),
        "trial_id",
        "trial",
    )
    for identity in trials:
        ensure_trial_id(identity, "campaign trial_id")
    payload["trials"] = [trials[key] for key in sorted(trials)]

    for key, label in (
        ("required_deterministic_outputs", "campaign required deterministic outputs"),
        ("required_model_fields", "campaign required model fields"),
    ):
        values = [str(value) for value in require_list(payload.get(key), label)]
        if len(values) != len(set(values)):
            raise DualRunProjectionError(f"{label} must not contain duplicates")
        payload[key] = sorted(values)
    return payload


def compute_campaign_id(campaign: Mapping[str, Any]) -> str:
    return "dual-run-campaign-sha256-" + sha256_json(
        canonical_campaign_identity_payload(campaign)
    )


def validate_campaign(campaign: Mapping[str, Any], trial_id: str) -> dict[str, Any]:
    record = require_mapping(campaign, "campaign")
    selected_trial_id = ensure_trial_id(trial_id)
    ensure_revision(record.get("thehub_revision"), "campaign thehub_revision")
    ensure_revision(record.get("skywatcher_revision"), "campaign skywatcher_revision")
    if record.get("campaign_id") != compute_campaign_id(record):
        raise DualRunProjectionError("campaign_id does not match canonical content")
    source_set = compute_source_set_sha256(record)
    if record.get("source_set_sha256") != source_set:
        raise DualRunProjectionError("campaign source_set_sha256 mismatch")
    pins_sha = compute_pins_sha256(record)
    if record.get("pins_sha256") != pins_sha:
        raise DualRunProjectionError("campaign pins_sha256 mismatch")
    trials = unique_index(
        require_list(record.get("trials"), "campaign trials"), "trial_id", "trial"
    )
    if len(trials) < 2:
        raise DualRunProjectionError("campaign requires at least two distinct trials")
    for identity, trial in trials.items():
        ensure_trial_id(identity, "campaign trial_id")
        if set(trial) != {"trial_id"}:
            raise DualRunProjectionError("campaign trial fields are not exact")
    if selected_trial_id not in trials:
        raise DualRunProjectionError("trial_id is not declared by campaign")
    reject_secret_or_unsafe_paths(record, path="campaign")
    canonical = dict(record)
    identity_payload = canonical_campaign_identity_payload(record)
    for key in (
        "source_artifacts",
        "trials",
        "required_deterministic_outputs",
        "required_model_fields",
    ):
        canonical[key] = identity_payload[key]
    return canonical


def validate_execution_receipt_ref(reference: Mapping[str, Any]) -> dict[str, Any]:
    record = require_mapping(reference, "execution receipt reference")
    allowed = {"run_id", "receipt_sha256", "signature_verified"}
    if set(record) != allowed:
        raise DualRunProjectionError("execution receipt reference fields are not exact")
    ensure_run_id(record.get("run_id"))
    ensure_sha256(record.get("receipt_sha256"), "execution receipt sha256")
    if record.get("signature_verified") is not True:
        raise DualRunProjectionError("execution receipt must be verified upstream")
    return record


def validate_provenance(
    provenance: Mapping[str, Any],
    *,
    campaign: Mapping[str, Any],
    source_index: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    record = require_mapping(provenance, "model field provenance")
    required = {
        "source_artifact_id",
        "source_sha256",
        "provider_id",
        "model_id",
        "model_revision",
        "prompt_template_hash",
        "policy_version",
        "access_context_hash",
        "extraction_schema_version",
    }
    if set(record) != required:
        missing = sorted(required - set(record))
        extra = sorted(set(record) - required)
        raise DualRunProjectionError(
            f"model field provenance must be exact; missing={missing}, extra={extra}"
        )
    source_id = str(record["source_artifact_id"])
    if source_id not in source_index:
        raise DualRunProjectionError("model provenance references source outside campaign")
    source_sha = ensure_sha256(record["source_sha256"], "model provenance source_sha256")
    if source_sha != source_index[source_id]["sha256"]:
        raise DualRunProjectionError("model provenance source SHA-256 drift")
    pins = require_mapping(campaign.get("pins"), "campaign pins")
    exact_pairs = {
        "provider_id": "provider_id",
        "model_id": "model_id",
        "model_revision": "model_revision",
        "prompt_template_hash": "prompt_template_hash",
        "policy_version": "policy_version",
    }
    for provenance_key, pin_key in exact_pairs.items():
        if record[provenance_key] != pins[pin_key]:
            raise DualRunProjectionError(f"model provenance {provenance_key} drift")
    ensure_sha256(record["prompt_template_hash"], "prompt template hash")
    ensure_sha256(record["access_context_hash"], "access context hash")
    if not str(record["extraction_schema_version"]):
        raise DualRunProjectionError("extraction_schema_version is required")
    return record
