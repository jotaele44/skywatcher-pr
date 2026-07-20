"""Normalization helpers shared by all artifact repositories."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from ..source_taxonomy import DATA_RIGHTS, OPERATIONAL_MODES, SOURCE_FAMILIES, SOURCE_METHODS
from ..time import UTCValidationError, normalize_utc
from .io import artifact_ref


def first(row: dict[str, Any], keys: Iterable[str], default: Any = None) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return default


def text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return text(value).lower() in {"1", "true", "yes", "y", "on"}


def as_float(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def as_int(value: Any) -> int | None:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def parse_json(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def normalize_time(value: Any, *, field_name: str, qa_flags: list[str]) -> str | None:
    if value in (None, ""):
        qa_flags.append(f"missing_{field_name}")
        return None
    try:
        return normalize_utc(value, field_name=field_name)
    except UTCValidationError:
        qa_flags.append(f"invalid_or_naive_{field_name}")
        return None


def stable_id(*parts: Any, prefix: str = "") -> str:
    material = "|".join(text(part) for part in parts)
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}{digest}" if prefix else digest


def mph_to_kt(value: Any) -> float | None:
    speed = as_float(value)
    return round(speed * 0.868976, 4) if speed is not None else None


def provenance(
    *,
    path: Path,
    adapter: str,
    source_record_id: str,
    source_family: str,
    source_provider: str,
    source_method: str,
    data_rights: str,
    operational_mode: str,
    artifact_kind: str,
    retrieved_at_utc: str | None = None,
    attribution: str | None = None,
) -> dict[str, Any]:
    artifact = artifact_ref(path, kind=artifact_kind)
    lineage_id = stable_id(str(path.resolve(strict=False)), source_record_id, adapter, prefix="lin-")
    return {
        "source_family": source_family,
        "source_provider": source_provider,
        "source_method": source_method,
        "data_rights": data_rights,
        "operational_mode": operational_mode,
        "source_record_id": source_record_id,
        "lineage_id": lineage_id,
        "retrieved_at_utc": retrieved_at_utc,
        "license_or_terms_ref": None,
        "attribution": attribution,
        "artifact_path": str(path),
        "artifact_sha256": artifact.sha256,
        "ingest_adapter": adapter,
    }


def _canonical(value: str, allowed: tuple[str, ...], field: str, qa_flags: list[str]) -> str:
    if value in allowed:
        return value
    qa_flags.append(f"invalid_{field}_normalized_to_unknown")
    return "unknown"


def attach_provenance(
    row: dict[str, Any],
    *,
    path: Path,
    adapter: str,
    source_record_id: str,
    source_family: str,
    source_provider: str,
    source_method: str,
    data_rights: str,
    operational_mode: str,
    artifact_kind: str,
    synthetic: bool,
    qa_flags: list[str] | None = None,
) -> dict[str, Any]:
    output = dict(row)
    output["synthetic"] = bool(synthetic)
    combined_flags = list(output.get("qa_flags") or []) + list(qa_flags or [])
    canonical_family = _canonical("synthetic_test" if synthetic else source_family, SOURCE_FAMILIES, "source_family", combined_flags)
    canonical_method = _canonical(source_method, SOURCE_METHODS, "source_method", combined_flags)
    canonical_rights = _canonical("synthetic" if synthetic else data_rights, DATA_RIGHTS, "data_rights", combined_flags)
    canonical_mode = _canonical("batch" if synthetic else operational_mode, OPERATIONAL_MODES, "operational_mode", combined_flags)
    output["qa_flags"] = sorted(set(combined_flags))
    output["provenance"] = provenance(
        path=path,
        adapter=adapter,
        source_record_id=source_record_id,
        source_family=canonical_family,
        source_provider=source_provider or "unknown",
        source_method=canonical_method,
        data_rights=canonical_rights,
        operational_mode=canonical_mode,
        artifact_kind=artifact_kind,
    )
    return output
