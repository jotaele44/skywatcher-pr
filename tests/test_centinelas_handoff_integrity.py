from __future__ import annotations

import copy
import hashlib
import json

import pytest

from scripts import ingest_centinelas_handoff as handoff


def signal(**overrides):
    row = {
        "schema_version": "1.0.0",
        "item_id": "CENT-SIG-001",
        "source_url": "https://example.test/aviation/1",
        "source_name": "fixture",
        "title": "Aircraft activity near Roosevelt Roads",
        "body_text": "review lead only",
        "published_at": "2026-09-11T12:00:00Z",
        "captured_at": "2026-09-11T12:05:00Z",
        "evidence_tier": "T3",
        "labels": ["MILITARY_AEROSPACE"],
        "confidence": 0.8,
        "routed_to": "skywatcher-pr",
        "routed_at": "2026-09-11T12:06:00Z",
    }
    row.update(overrides)
    return row


def envelope(sig=None, **overrides):
    sig = sig or signal()
    item_id = sig["item_id"]
    target = "skywatcher-pr"
    canonical = json.dumps(sig, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(f"{item_id}\0{target}\0{canonical}".encode()).hexdigest()
    row = {
        "item_id": item_id,
        "target": target,
        "idempotency_key": f"centinelas:{item_id}:{target}:{digest[:20]}",
        "signal": sig,
    }
    row.update(overrides)
    return row


def test_first_delivery_and_exact_replay_are_idempotent(tmp_path):
    payload = envelope()
    first = handoff.ingest(payload, "skywatcher-pr", receipt_dir=tmp_path)
    second = handoff.ingest(payload, "skywatcher-pr", receipt_dir=tmp_path)

    assert first["duplicate"] is False
    assert second["duplicate"] is True
    receipt = json.loads((tmp_path / (hashlib.sha256(payload["idempotency_key"].encode()).hexdigest() + ".json")).read_text())
    assert receipt["receipt_schema"] == handoff.RECEIPT_SCHEMA
    assert receipt["identity_effect"] == "NONE"
    assert receipt["payload"] == payload


def test_reused_key_with_changed_payload_preserves_collision_and_fails(tmp_path):
    original = envelope()
    handoff.ingest(original, "skywatcher-pr", receipt_dir=tmp_path)

    fork = copy.deepcopy(original)
    fork["signal"]["title"] = "Different protected payload"
    with pytest.raises(ValueError, match="idempotency collision"):
        handoff.ingest(fork, "skywatcher-pr", receipt_dir=tmp_path)

    base = tmp_path / (hashlib.sha256(original["idempotency_key"].encode()).hexdigest() + ".json")
    collision = base.with_suffix(".collision.json")
    evidence = json.loads(collision.read_text())
    assert evidence["collision_schema"] == handoff.COLLISION_SCHEMA
    assert evidence["identity_effect"] == "NONE"
    assert evidence["existing_payload_sha256"] != evidence["incoming_payload_sha256"]


def test_new_receipt_rejects_wrong_deterministic_key(tmp_path):
    payload = envelope(idempotency_key="centinelas:wrong")
    with pytest.raises(ValueError, match="does not match protected payload"):
        handoff.ingest(payload, "skywatcher-pr", receipt_dir=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_backward_compatible_v1_exact_replay_is_duplicate(tmp_path):
    payload = envelope()
    path = tmp_path / (hashlib.sha256(payload["idempotency_key"].encode()).hexdigest() + ".json")
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result = handoff.ingest(payload, "skywatcher-pr", receipt_dir=tmp_path)
    assert result["duplicate"] is True


def test_target_and_item_identity_mismatch_fail_closed(tmp_path):
    with pytest.raises(ValueError, match="target mismatch"):
        handoff.ingest(envelope(target="other-pr"), "skywatcher-pr", receipt_dir=tmp_path)

    payload = envelope()
    payload["item_id"] = "CENT-SIG-DIFFERENT"
    with pytest.raises(ValueError, match="outer item_id"):
        handoff.ingest(payload, "skywatcher-pr", receipt_dir=tmp_path)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"captured_at": "not-a-date"}, "captured_at"),
        ({"evidence_tier": "T9"}, "evidence_tier"),
        ({"confidence": 1.5}, "confidence"),
        ({"labels": "MILITARY_AEROSPACE"}, "labels"),
        ({"source_url": "relative/path"}, "absolute URI"),
    ],
)
def test_invalid_signal_contract_fails_closed(tmp_path, mutation, message):
    payload = envelope(signal=signal(**mutation))
    with pytest.raises(ValueError, match=message):
        handoff.ingest(payload, "skywatcher-pr", receipt_dir=tmp_path)
