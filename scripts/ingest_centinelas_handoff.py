#!/usr/bin/env python3
"""Durably ingest one fail-closed Centinelas handoff envelope.

The receiver validates the bounded Skywatcher intake contract and stores an
immutable receipt. Exact replay is idempotent. Reuse of one idempotency key with
different protected payload bytes is a collision/fork and fails closed with
preserved collision evidence. New receipts also verify Centinelas' deterministic
idempotency-key derivation before they are accepted.

This adapter has no identity authority: a routed signal is an aviation lead only.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

RECEIPT_SCHEMA = "centinelas_skywatcher_handoff_receipt/v2"
COLLISION_SCHEMA = "centinelas_skywatcher_handoff_collision/v1"
RECEIPT_DIR = Path("data/centinelas_handoffs")
_REQUIRED_SIGNAL_FIELDS = {
    "schema_version",
    "item_id",
    "source_url",
    "title",
    "labels",
    "captured_at",
}


def _canonical_payload(value: Any) -> str:
    # Must match centinelas-pr _idempotency_key serialization exactly.
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _payload_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_payload(value).encode()).hexdigest()


def _expected_idempotency_key(item_id: str, target: str, signal: dict[str, Any]) -> str:
    digest = hashlib.sha256(
        f"{item_id}\0{target}\0{_canonical_payload(signal)}".encode()
    ).hexdigest()
    return f"centinelas:{item_id}:{target}:{digest[:20]}"


def _valid_datetime(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.utcoffset() is not None


def _validate_signal(signal: Any) -> dict[str, Any]:
    if not isinstance(signal, dict):
        raise ValueError("signal must be an object")
    missing = sorted(_REQUIRED_SIGNAL_FIELDS - set(signal))
    if missing:
        raise ValueError(f"signal missing required fields: {missing}")
    if not isinstance(signal["schema_version"], str) or not signal["schema_version"]:
        raise ValueError("signal.schema_version must be a non-empty string")
    if not isinstance(signal["item_id"], str) or not signal["item_id"]:
        raise ValueError("signal.item_id must be a non-empty string")
    if not isinstance(signal["title"], str) or not signal["title"]:
        raise ValueError("signal.title must be a non-empty string")
    parsed_url = urlparse(str(signal["source_url"]))
    if not parsed_url.scheme:
        raise ValueError("signal.source_url must be an absolute URI")
    if not isinstance(signal["labels"], list) or not all(
        isinstance(value, str) for value in signal["labels"]
    ):
        raise ValueError("signal.labels must be an array of strings")
    for field in ("captured_at", "published_at", "routed_at"):
        if field in signal and signal[field] is not None and not _valid_datetime(signal[field]):
            raise ValueError(f"signal.{field} must be an ISO date-time with timezone")
    tier = signal.get("evidence_tier")
    if tier is not None and tier not in {"T1", "T2", "T3", "T4"}:
        raise ValueError("signal.evidence_tier must be T1|T2|T3|T4")
    confidence = signal.get("confidence")
    if confidence is not None and (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0 <= float(confidence) <= 1
    ):
        raise ValueError("signal.confidence must be between 0 and 1")
    return signal


def validate_envelope(payload: Any, expected_target: str) -> dict[str, Any]:
    """Validate envelope shape without consuming the idempotency key.

    Key verification for a new receipt happens only after the existing-receipt
    collision check so a fork attempt cannot disappear as a bare key-mismatch.
    """
    if not isinstance(payload, dict):
        raise ValueError("handoff payload must be an object")
    for field in ("item_id", "target", "idempotency_key", "signal"):
        if field not in payload:
            raise ValueError(f"handoff payload missing {field}")
    item_id = payload["item_id"]
    target = payload["target"]
    key = payload["idempotency_key"]
    if not isinstance(item_id, str) or not item_id:
        raise ValueError("item_id must be a non-empty string")
    if target != expected_target:
        raise ValueError("handoff target mismatch")
    if not isinstance(key, str) or not key:
        raise ValueError("idempotency_key must be a non-empty string")
    signal = _validate_signal(payload["signal"])
    if signal["item_id"] != item_id:
        raise ValueError("outer item_id does not match signal.item_id")
    return payload


def ingest(
    payload: dict[str, Any],
    expected_target: str,
    *,
    receipt_dir: Path = RECEIPT_DIR,
) -> dict[str, Any]:
    validate_envelope(payload, expected_target)
    key = payload["idempotency_key"]
    incoming_sha = _payload_sha256(payload)
    receipt_dir.mkdir(parents=True, exist_ok=True)
    out = receipt_dir / f"{hashlib.sha256(key.encode()).hexdigest()}.json"

    if out.exists():
        existing = json.loads(out.read_text(encoding="utf-8"))
        if existing.get("receipt_schema") == RECEIPT_SCHEMA:
            existing_sha = existing.get("payload_sha256")
        else:
            # Backward-compatible v1 receipts stored only the original envelope.
            existing_sha = _payload_sha256(existing)
        if existing_sha != incoming_sha:
            collision = out.with_suffix(".collision.json")
            collision.write_text(
                json.dumps(
                    {
                        "collision_schema": COLLISION_SCHEMA,
                        "identity_effect": "NONE",
                        "idempotency_key": key,
                        "existing_receipt": str(out),
                        "existing_payload_sha256": existing_sha,
                        "incoming_payload_sha256": incoming_sha,
                        "incoming_payload": payload,
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            raise ValueError("idempotency collision: protected payload differs")
        return {"duplicate": True, "receipt_path": str(out), "payload_sha256": incoming_sha}

    expected_key = _expected_idempotency_key(
        payload["item_id"], payload["target"], payload["signal"]
    )
    if key != expected_key:
        raise ValueError("idempotency_key does not match protected payload")

    receipt = {
        "receipt_schema": RECEIPT_SCHEMA,
        "target": expected_target,
        "item_id": payload["item_id"],
        "idempotency_key": key,
        "identity_effect": "NONE",
        "payload_sha256": incoming_sha,
        "payload": payload,
    }
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"duplicate": False, "receipt_path": str(out), "payload_sha256": incoming_sha}


def main() -> int:
    payload = json.loads(os.environ["CENTINELAS_CLIENT_PAYLOAD"])
    expected_target = os.environ["EXPECTED_TARGET"]
    try:
        result = ingest(payload, expected_target)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if github_output := os.environ.get("GITHUB_OUTPUT"):
        with open(github_output, "a", encoding="utf-8") as handle:
            handle.write(f"duplicate={str(result['duplicate']).lower()}\n")
            handle.write(f"receipt_path={result['receipt_path']}\n")
            handle.write(f"payload_sha256={result['payload_sha256']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
