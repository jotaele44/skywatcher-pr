"""Unit tests for the bundled deterministic filename-hint VisualOcrBackend.

Pure stdlib — no pandas, no image IO. Covers (a) the parser in isolation and
(b) its merge through the ``extract_visual_metadata`` backend seam, including the
guarantee that the default (no-backend) path is byte-for-byte unchanged.
"""
from satim_engine.plugins.visual_ocr import extract_visual_metadata
from satim_engine.plugins.visual_ocr_filename_backend import (
    filename_hint_backend,
    parse_filename_hints,
)


# ── parser in isolation ─────────────────────────────────────────────────────

def test_parses_tail_callsign_and_iso_timestamp():
    hints = parse_filename_hints("FR24_N123AB_2026-01-01T18:42:05Z.jpg")
    assert hints["tail_hint"] == "N123AB"
    assert hints["timestamp_hint"] == "2026-01-01T18:42:05Z"
    # 'FR24' is a source tag on the stopword list, not a callsign.
    assert hints["callsign_hint"] is None


def test_parses_airline_callsign_and_date():
    hints = parse_filename_hints("AAL123_2026-01-01.png")
    assert hints["callsign_hint"] == "AAL123"
    assert hints["timestamp_hint"] == "2026-01-01"
    assert hints["tail_hint"] is None


def test_tail_not_misclassified_as_callsign():
    hints = parse_filename_hints("N5854Z.png")
    assert hints["tail_hint"] == "N5854Z"
    assert hints["callsign_hint"] is None


def test_hyphen_separated_tokens_and_compact_date():
    hints = parse_filename_hints("/tmp/x/N767PD-20260101-184205.jpg")
    assert hints["tail_hint"] == "N767PD"
    assert hints["timestamp_hint"] == "20260101"


def test_canada_tail_and_callsign():
    assert parse_filename_hints("C-GXYZ_2026-01-01.jpg")["tail_hint"] == "C-GXYZ"
    assert parse_filename_hints("screenshot_18:42Z_FURA1.png")["callsign_hint"] == "FURA1"


def test_clock_only_token_never_populates_timestamp_hint():
    """A date-less clock token must NOT become timestamp_hint (pairing reads that
    as an absolute time and would resolve it against a wrong/default date). It is
    surfaced under the non-authoritative clock_hint field instead."""
    hints = parse_filename_hints("screenshot_18:42Z_FURA1.png")
    assert hints["timestamp_hint"] is None
    assert hints["clock_hint"] == "18:42Z"


def test_date_present_wins_and_suppresses_clock_hint():
    hints = parse_filename_hints("frame_20260101_18:42Z.png")
    assert hints["timestamp_hint"] == "20260101"
    # A real date is authoritative; the clock token is not separately surfaced.
    assert hints["clock_hint"] is None


def test_no_tokens_returns_all_none():
    hints = parse_filename_hints("random_file_name.png")
    assert hints == {
        "callsign_hint": None,
        "tail_hint": None,
        "timestamp_hint": None,
        "clock_hint": None,
    }


# ── merge through the extract_visual_metadata backend seam ───────────────────

def test_backend_merges_hints_over_filename_defaults():
    meta = extract_visual_metadata(
        "/data/FR24_N123AB_2026-01-01T18:42:05Z.jpg", backend=filename_hint_backend
    )
    assert meta["ocr_status"] == "FILENAME_HINT"
    assert meta["plugin"] == "visual_ocr.filename_hint"
    assert meta["tail_hint"] == "N123AB"
    assert meta["timestamp_hint"] == "2026-01-01T18:42:05Z"
    # Not resolved by the parser -> canonical field stays None (from the defaults).
    assert meta["callsign_hint"] is None
    # Filename-derived provenance from the defaults is preserved.
    assert meta["visual_path"] == "/data/FR24_N123AB_2026-01-01T18:42:05Z.jpg"
    assert meta["text"] == "FR24_N123AB_2026-01-01T18:42:05Z"


def test_backend_only_fills_confident_fields():
    meta = extract_visual_metadata("/data/random_file_name.png", backend=filename_hint_backend)
    # No confident tokens -> all hints stay None but status still marks the backend.
    assert meta["ocr_status"] == "FILENAME_HINT"
    assert meta["callsign_hint"] is None
    assert meta["tail_hint"] is None
    assert meta["timestamp_hint"] is None


def test_default_path_is_byte_for_byte_unchanged():
    """The no-backend contract must be identical whether or not this module loaded."""
    path = "/data/FR24_N123AB_2026-01-01T18:42:05Z.jpg"
    assert extract_visual_metadata(path) == {
        "visual_path": path,
        "ocr_status": "FILENAME_ONLY",
        "text": "FR24_N123AB_2026-01-01T18:42:05Z",
        "callsign_hint": None,
        "timestamp_hint": None,
        "tail_hint": None,
        "plugin": "visual_ocr.default_filename_adapter",
    }
