"""Opaque deterministic cursor contract for future console list endpoints."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Mapping
from typing import Any

CURSOR_VERSION = 1


class CursorError(ValueError):
    """Raised when an opaque cursor is malformed, tampered, or filter-mismatched."""


def filter_fingerprint(filters: Mapping[str, Any] | None) -> str:
    canonical = json.dumps(filters or {}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    try:
        return base64.urlsafe_b64decode(text + padding)
    except Exception as exc:
        raise CursorError("cursor is not valid base64url") from exc


def encode_cursor(*, sort_value: str, stable_id: str, filters: Mapping[str, Any] | None = None) -> str:
    payload = {
        "v": CURSOR_VERSION,
        "s": str(sort_value),
        "id": str(stable_id),
        "f": filter_fingerprint(filters),
    }
    payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(payload_bytes).hexdigest()[:24]
    envelope = json.dumps({"p": payload, "d": digest}, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _b64encode(envelope)


def decode_cursor(cursor: str, *, filters: Mapping[str, Any] | None = None) -> dict[str, str | int]:
    try:
        envelope = json.loads(_b64decode(cursor))
        payload = envelope["p"]
        digest = envelope["d"]
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise CursorError("cursor envelope is malformed") from exc

    payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    expected = hashlib.sha256(payload_bytes).hexdigest()[:24]
    if not hmac.compare_digest(str(digest), expected):
        raise CursorError("cursor integrity check failed")
    if payload.get("v") != CURSOR_VERSION:
        raise CursorError("cursor version is unsupported")
    if payload.get("f") != filter_fingerprint(filters):
        raise CursorError("cursor does not match the active filters")
    if not payload.get("s") or not payload.get("id"):
        raise CursorError("cursor is missing ordering fields")
    return payload
