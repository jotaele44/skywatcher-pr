import base64

import pytest

from server.backend.console.pagination import CursorError, decode_cursor, encode_cursor


def test_cursor_round_trip():
    filters = {"bbox": "-67,17,-65,19", "source_method": ["adsb", "radar"]}
    cursor = encode_cursor(sort_value="2026-07-20T16:00:00Z", stable_id="state-1", filters=filters)
    payload = decode_cursor(cursor, filters=filters)
    assert payload["s"] == "2026-07-20T16:00:00Z"
    assert payload["id"] == "state-1"


def test_cursor_rejects_filter_mismatch():
    cursor = encode_cursor(sort_value="2026-07-20T16:00:00Z", stable_id="state-1", filters={"synthetic": False})
    with pytest.raises(CursorError, match="active filters"):
        decode_cursor(cursor, filters={"synthetic": True})


def test_cursor_rejects_tampering():
    cursor = encode_cursor(sort_value="2026-07-20T16:00:00Z", stable_id="state-1", filters={})
    raw = bytearray(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    raw[-2] = raw[-2] ^ 1
    tampered = base64.urlsafe_b64encode(bytes(raw)).decode().rstrip("=")
    with pytest.raises(CursorError):
        decode_cursor(tampered, filters={})
