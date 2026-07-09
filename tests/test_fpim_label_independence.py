"""Regression guard: FPIM's flight-path/behavior detection must operate on
observed trajectory characteristics alone and must never branch on whether a
callsign matches a known operator/mission label — labeled and unlabeled
tracks go through identical processing. See docs/MODULE_SPEC_FPIM.md and
docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md."""

from fr24.flight_fusion import fuse_wave

BASE_ROW = {
    "image_name": "shot_1.png",
    "timestamp_iso": "2026-01-01T12:00:00",
    "lat": "18.40",
    "lon": "-66.10",
    "altitude_ft": "1200",
    "ground_speed_mph": "90",
    "confidence": "0.9",
    "aircraft_type": "H125",
}


def _wave_for(callsign: str) -> list:
    row1 = dict(BASE_ROW, callsign_or_label=callsign, image_name="shot_1.png",
                timestamp_iso="2026-01-01T12:00:00")
    row2 = dict(BASE_ROW, callsign_or_label=callsign, image_name="shot_2.png",
                timestamp_iso="2026-01-01T12:05:00", altitude_ft="1400")
    return [row1, row2]


def test_fusion_identical_for_known_vs_unknown_callsign():
    # "N5854Z" is a KNOWN_OPERATORS entry (PREPA); "N999ZZ" matches nothing.
    known_result = fuse_wave(_wave_for("N5854Z"))
    unknown_result = fuse_wave(_wave_for("N999ZZ"))

    assert known_result.keys() == unknown_result.keys()
    for key in known_result.keys() - {"aircraft_identity", "callsign"}:
        assert known_result[key] == unknown_result[key], f"field {key!r} diverged by label"

    # Both get analyzed identically — neither is skipped or short-circuited.
    assert known_result["num_screenshots"] == unknown_result["num_screenshots"] == 2
    assert known_result["confirmation_status"] == unknown_result["confirmation_status"] == "not_confirmed"
