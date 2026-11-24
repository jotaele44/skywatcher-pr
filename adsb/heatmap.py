"""
adsb.lol / readsb replay ("heatmap") chunk decoder.

The adsb.lol web map replays history from half-hour chunk files at
``globe_history/YYYY/MM/DD/heatmap/NN.bin.ttf`` where ``NN = 2*hour +
minute // 30`` (UTC). A chunk is a flat little-endian array of 16-byte
records (four 32-bit words):

* **Slice header** — word 0 is the magic ``0x0E7F7C9D``. Words 1/2 hold the
  slice timestamp in milliseconds split as ``hi * 2**32 + lo``; the low 16 bits
  of word 3 are the slice interval in milliseconds.
* **Identity record** — word 1 (latitude) is ``>= 2**30``. Word 0 carries the
  24-bit ICAO address (bit 24 set = non-ICAO "~" address), the low 16 bits of
  word 1 the squawk as a decimal number, and bytes 8..15 an 8-byte callsign.
* **Position record** — word 0: ICAO address (bits 0-23), non-ICAO flag
  (bit 24) and position source type (bits 27-31); words 1/2: latitude and
  longitude in micro-degrees; word 3: altitude in 25 ft units (low 16 bits,
  signed; -123 = on ground, -124 = unknown) and ground speed in 0.1 kt (high
  16 bits, signed; -1 = unknown).

This mirrors the format readsb writes and tar1090's ``initReplay`` /
``replayStep`` read. The decoder is pure (bytes in, records out) so it can be
tested without network access.
"""

from __future__ import annotations

import sys
from array import array
from dataclasses import dataclass, field
from datetime import datetime, timezone

MAGIC = 0x0E7F7C9D
RECORD_BYTES = 16
_IDENTITY_LAT_THRESHOLD = 1 << 30

SOURCE_TYPES = (
    "adsb_icao",
    "adsb_icao_nt",
    "adsr_icao",
    "tisb_icao",
    "adsc",
    "mlat",
    "other",
    "mode_s",
    "adsb_other",
    "adsr_other",
    "tisb_trackfile",
    "tisb_other",
    "mode_ac",
)


class HeatmapFormatError(ValueError):
    """Raised when a chunk is not a readsb heatmap file."""


@dataclass
class HeatmapPosition:
    hex: str
    lat: float
    lon: float
    alt_baro: int | str | None
    gs: float | None
    source_type: str


@dataclass
class HeatmapSlice:
    timestamp: float
    interval_s: float
    positions: list[HeatmapPosition] = field(default_factory=list)


@dataclass
class HeatmapChunk:
    slices: list[HeatmapSlice]
    identities: dict[str, dict[str, str]]

    @property
    def start(self) -> float | None:
        return self.slices[0].timestamp if self.slices else None

    @property
    def end(self) -> float | None:
        if not self.slices:
            return None
        last = self.slices[-1]
        return last.timestamp + last.interval_s


def chunk_index(moment: datetime) -> int:
    """Half-hour chunk number (0..47) for a UTC moment."""

    moment = moment.astimezone(timezone.utc)
    return 2 * moment.hour + moment.minute // 30


def chunk_path(moment: datetime) -> str:
    """Site-relative path of the chunk that contains ``moment``."""

    moment = moment.astimezone(timezone.utc)
    return f"globe_history/{moment:%Y/%m/%d}/heatmap/{chunk_index(moment):02d}.bin.ttf"


def _hex(word: int) -> str:
    value = f"{word & 0xFFFFFF:06x}"
    return f"~{value}" if word & 0x1000000 else value


def _sign16(value: int) -> int:
    value &= 0xFFFF
    return value - 0x10000 if value & 0x8000 else value


def _in_bbox(lat: float, lon: float, bbox: tuple[float, float, float, float] | None) -> bool:
    if bbox is None:
        return True
    west, south, east, north = bbox
    if not south <= lat <= north:
        return False
    if west <= east:
        return west <= lon <= east
    return lon >= west or lon <= east  # bbox crosses the antimeridian


def decode_heatmap(
    data: bytes,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    start: float | None = None,
    end: float | None = None,
) -> HeatmapChunk:
    """Decode a heatmap chunk, optionally keeping only positions in ``bbox``
    (west, south, east, north) and slices with ``start <= t < end`` (epoch s).
    """

    if len(data) % RECORD_BYTES:
        raise HeatmapFormatError("heatmap length is not a multiple of 16 bytes")
    signed = array("i")
    signed.frombytes(data)
    if sys.byteorder != "little":  # pragma: no cover - big-endian hosts
        signed.byteswap()
    unsigned = array("I", signed.tobytes())

    slices: list[HeatmapSlice] = []
    identities: dict[str, dict[str, str]] = {}
    current: HeatmapSlice | None = None
    keep_current = False
    found_magic = False

    for i in range(0, len(signed), 4):
        word0 = unsigned[i]
        if word0 == MAGIC:
            found_magic = True
            timestamp = unsigned[i + 2] / 1000 + unsigned[i + 1] * 4294967.296
            interval = (unsigned[i + 3] & 0xFFFF) / 1000
            current = HeatmapSlice(timestamp=timestamp, interval_s=interval)
            keep_current = (start is None or timestamp >= start) and (end is None or timestamp < end)
            if keep_current:
                slices.append(current)
            continue
        if current is None:
            continue
        lat_raw = signed[i + 1]
        if lat_raw >= _IDENTITY_LAT_THRESHOLD:
            hex_id = _hex(word0)
            entry = identities.setdefault(hex_id, {})
            offset = 4 * (i + 2)
            raw_flight = data[offset : offset + 8]
            if raw_flight[:1] != b"\x00":
                flight = raw_flight.split(b"\x00", 1)[0].decode("ascii", "replace").strip()
                if flight:
                    entry["flight"] = flight
            entry["squawk"] = f"{lat_raw & 0xFFFF:04d}"
            continue
        if not keep_current:
            continue
        lat = lat_raw / 1e6
        lon = signed[i + 2] / 1e6
        if not _in_bbox(lat, lon, bbox):
            continue
        word3 = signed[i + 3]
        alt_units = _sign16(word3)
        if alt_units == -123:
            alt: int | str | None = "ground"
        elif alt_units == -124:
            alt = None
        else:
            alt = alt_units * 25
        gs_raw = word3 >> 16
        gs = None if gs_raw == -1 else gs_raw / 10
        type_index = (word0 >> 27) & 0x1F
        source_type = SOURCE_TYPES[type_index] if type_index < len(SOURCE_TYPES) else "unknown"
        current.positions.append(
            HeatmapPosition(
                hex=_hex(word0), lat=lat, lon=lon, alt_baro=alt, gs=gs, source_type=source_type
            )
        )

    if not found_magic:
        raise HeatmapFormatError("heatmap has no slice header (magic number missing)")
    return HeatmapChunk(slices=slices, identities=identities)


def encode_heatmap(slices: list[dict]) -> bytes:
    """Build a heatmap chunk from plain dicts. Used by tests and fixtures.

    Each slice: ``{"timestamp": s, "interval_s": s, "positions": [...],
    "identities": [...]}``; positions carry ``hex, lat, lon, alt_baro, gs,
    source_type``; identities carry ``hex, flight, squawk``.
    """

    words = array("I")

    def hex_word(value: str) -> int:
        tilde = value.startswith("~")
        word = int(value.lstrip("~"), 16) & 0xFFFFFF
        return word | (0x1000000 if tilde else 0)

    for item in slices:
        millis = round(item["timestamp"] * 1000)
        words.extend([MAGIC, millis >> 32, millis & 0xFFFFFFFF, round(item["interval_s"] * 1000) & 0xFFFF])
        for ident in item.get("identities", []):
            flight = ident.get("flight", "").encode("ascii")[:8].ljust(8, b"\x00")
            lat_word = _IDENTITY_LAT_THRESHOLD | int(ident.get("squawk", "0000"))
            words.extend([hex_word(ident["hex"]), lat_word])
            words.frombytes(flight)
        for pos in item.get("positions", []):
            alt = pos.get("alt_baro")
            alt_units = -123 if alt == "ground" else -124 if alt is None else int(alt) // 25
            gs = pos.get("gs")
            gs_units = -1 if gs is None else round(gs * 10)
            type_index = SOURCE_TYPES.index(pos.get("source_type", "adsb_icao"))
            word0 = hex_word(pos["hex"]) | (type_index << 27)
            word3 = ((gs_units & 0xFFFF) << 16) | (alt_units & 0xFFFF)
            words.extend(
                [
                    word0,
                    round(pos["lat"] * 1e6) & 0xFFFFFFFF,
                    round(pos["lon"] * 1e6) & 0xFFFFFFFF,
                    word3,
                ]
            )
    if sys.byteorder != "little":  # pragma: no cover - big-endian hosts
        words.byteswap()
    return words.tobytes()
