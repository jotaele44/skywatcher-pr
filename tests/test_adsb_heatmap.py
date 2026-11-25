"""Tests for the adsb.lol / readsb replay chunk decoder (pure, no network)."""

from datetime import datetime, timezone

import pytest

from adsb.heatmap import HeatmapFormatError, chunk_index, chunk_path, decode_heatmap, encode_heatmap

T0 = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc).timestamp()


def _chunk():
    return encode_heatmap(
        [
            {
                "timestamp": T0,
                "interval_s": 10,
                "identities": [
                    {"hex": "a37f12", "flight": "AAL1512", "squawk": "3037"},
                    {"hex": "~abc123", "flight": "TISB1", "squawk": "7700"},
                ],
                "positions": [
                    {"hex": "a37f12", "lat": 18.498789, "lon": -67.111683, "alt_baro": 36000, "gs": 430.7, "source_type": "adsb_icao"},
                    {"hex": "~abc123", "lat": 18.25, "lon": -66.1, "alt_baro": "ground", "gs": None, "source_type": "tisb_other"},
                    {"hex": "c0ffee", "lat": 40.6, "lon": -73.8, "alt_baro": None, "gs": 150.0, "source_type": "mlat"},
                ],
            },
            {
                "timestamp": T0 + 10,
                "interval_s": 10,
                "positions": [
                    {"hex": "a37f12", "lat": 18.5, "lon": -67.15, "alt_baro": -50, "gs": 431.0, "source_type": "adsb_icao"},
                ],
            },
        ]
    )


def test_decode_roundtrip_preserves_fields_and_identities():
    chunk = decode_heatmap(_chunk())
    assert [round(s.timestamp, 3) for s in chunk.slices] == [T0, T0 + 10]
    assert chunk.slices[0].interval_s == 10
    first = {p.hex: p for p in chunk.slices[0].positions}
    assert first["a37f12"].alt_baro == 36000
    assert first["a37f12"].gs == 430.7
    assert first["a37f12"].source_type == "adsb_icao"
    assert first["~abc123"].alt_baro == "ground"
    assert first["~abc123"].gs is None
    assert first["~abc123"].source_type == "tisb_other"
    assert first["c0ffee"].alt_baro is None
    assert chunk.slices[1].positions[0].alt_baro == -50
    assert chunk.identities["a37f12"] == {"flight": "AAL1512", "squawk": "3037"}
    assert chunk.identities["~abc123"]["squawk"] == "7700"
    assert chunk.start == T0 and chunk.end == T0 + 20


def test_decode_filters_bbox_and_time_window():
    chunk = decode_heatmap(_chunk(), bbox=(-68.2, 17.8, -65.1, 18.7), start=T0 + 5)
    assert len(chunk.slices) == 1
    assert [p.hex for p in chunk.slices[0].positions] == ["a37f12"]
    # identities are collected from every slice so later frames can be labelled
    assert "a37f12" in chunk.identities


def test_decode_rejects_non_heatmap_payloads():
    with pytest.raises(HeatmapFormatError):
        decode_heatmap(b"\x00" * 15)
    with pytest.raises(HeatmapFormatError):
        decode_heatmap(b"\x00" * 32)


def test_chunk_naming_matches_adsblol_layout():
    moment = datetime(2026, 11, 3, 16, 1, tzinfo=timezone.utc)
    assert chunk_index(moment) == 32
    assert chunk_path(moment) == "globe_history/2026/11/03/heatmap/32.bin.ttf"
    assert chunk_index(datetime(2026, 11, 3, 0, 29, tzinfo=timezone.utc)) == 0
    assert chunk_index(datetime(2026, 11, 3, 23, 30, tzinfo=timezone.utc)) == 47
