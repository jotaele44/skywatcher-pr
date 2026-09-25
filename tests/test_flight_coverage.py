from __future__ import annotations

from datetime import date

from skywatcher.fr24.flight_coverage import (
    UNRESOLVED_IDENTITY,
    build_coverage_ledger,
)


def _record(
    callsign: str | None,
    day: str,
    *,
    uid: str,
    kml: bool = True,
    folder: str | None = None,
    points: int = 10,
) -> dict:
    return {
        "corpusUid": uid,
        "sourceFlightIdRaw": uid[-8:],
        "callsignRaw": callsign,
        "pointCount": points,
        "startTimeUtc": f"{day}T12:00:00.000Z",
        "endTimeUtc": f"{day}T13:00:00.000Z",
        "sourceManifestations": [
            {
                "folderRaw": folder or callsign or "",
                "filenameRaw": f"{uid}.csv",
                "kmlPresent": kml,
            }
        ],
        "raw": {"fid": uid[-8:], "cs": callsign or ""},
    }


def test_gap_requires_minimum_and_cadence_multiplier():
    records = [
        _record("N1", "2026-01-01", uid="mfl:00000001"),
        _record("N1", "2026-01-06", uid="mfl:00000002"),
        _record("N1", "2026-02-15", uid="mfl:00000003"),
    ]
    ledger = build_coverage_ledger(records, as_of=date(2026, 2, 20))
    assert ledger["identities"][0]["median_cadence_days"] == 22.5
    assert ledger["gaps"] == []


def test_internal_gap_is_classified_against_365_day_lookback():
    records = [
        _record("N1", "2025-01-01", uid="mfl:00000001"),
        _record("N1", "2025-01-02", uid="mfl:00000002"),
        _record("N1", "2025-05-01", uid="mfl:00000003"),
        _record("N1", "2026-09-01", uid="mfl:00000004"),
    ]
    ledger = build_coverage_ledger(records, as_of=date(2026, 9, 25))
    states = {(item["from"], item["to"]): item["state"] for item in ledger["gaps"]}
    assert states[("2025-01-03", "2025-04-30")] == "BEYOND_LOOKBACK"
    assert states[("2025-05-02", "2026-08-31")] == "PARTLY_RECOVERABLE"


def test_recent_internal_gap_is_recoverable():
    records = [
        _record("N1", "2026-07-01", uid="mfl:00000001"),
        _record("N1", "2026-07-02", uid="mfl:00000002"),
        _record("N1", "2026-08-20", uid="mfl:00000003"),
    ]
    ledger = build_coverage_ledger(records, as_of=date(2026, 9, 25))
    assert ledger["gaps"][0]["state"] == "RECOVERABLE"
    assert ledger["gaps"][0]["recoverable_days"] == ledger["gaps"][0]["days"]


def test_blank_callsign_single_folder_is_provisional_not_registration():
    records = [_record(None, "2026-09-01", uid="mfl:00000001", folder="N123AB")]
    ledger = build_coverage_ledger(records, as_of=date(2026, 9, 25))
    ident = ledger["identities"][0]
    assert ident["identity"] == "N123AB"
    assert ident["identity_state"] == "PROVISIONAL_FOLDER_IDENTITY"
    assert any(item["type"] == "VERIFY" for item in ledger["acquisition_queue"])


def test_blank_callsign_generic_folder_stays_unresolved():
    records = [_record(None, "2026-09-01", uid="mfl:00000001", folder="csv")]
    ledger = build_coverage_ledger(records, as_of=date(2026, 9, 25))
    assert ledger["identities"][0]["identity"] == UNRESOLVED_IDENTITY
    assert ledger["identities"][0]["identity_state"] == "UNRESOLVED"


def test_missing_kml_is_acquisition_state_not_missing_flight():
    records = [_record("N1", "2026-09-20", uid="mfl:00000001", kml=False)]
    ledger = build_coverage_ledger(records, as_of=date(2026, 9, 25))
    queue = ledger["acquisition_queue"]
    assert any(item["type"] == "KML" for item in queue)
    item = next(item for item in queue if item["type"] == "KML")
    assert "not missing-flight evidence" in item["evidence_note"]


def test_stale_and_dormant_are_separate_activity_states():
    recent = build_coverage_ledger(
        [
            _record("N1", "2026-09-01", uid="mfl:00000001"),
            _record("N1", "2026-09-02", uid="mfl:00000002"),
            _record("N1", "2026-09-03", uid="mfl:00000003"),
        ],
        as_of=date(2026, 9, 25),
    )
    stale = next(item for item in recent["acquisition_queue"] if item["type"] == "STALE")
    assert stale["activity_state"] == "ACTIVE_RECENTLY"

    old = build_coverage_ledger(
        [
            _record("N1", "2026-01-01", uid="mfl:00000001"),
            _record("N1", "2026-01-02", uid="mfl:00000002"),
            _record("N1", "2026-01-03", uid="mfl:00000003"),
        ],
        as_of=date(2026, 9, 25),
    )
    dormant = next(item for item in old["acquisition_queue"] if item["type"] == "STALE")
    assert dormant["activity_state"] == "DORMANT"


def test_overlap_nonstandard_copy_is_superseded():
    a = _record("N1", "2026-09-01", uid="mfl:a")
    b = _record("N1", "2026-09-01", uid="mfl:b")
    a["sourceFlightIdRaw"] = None
    a["startTimeUtc"] = "2026-09-01T12:00:00.000Z"
    a["endTimeUtc"] = "2026-09-01T13:00:00.000Z"
    b["startTimeUtc"] = "2026-09-01T12:10:00.000Z"
    b["endTimeUtc"] = "2026-09-01T12:50:00.000Z"

    ledger = build_coverage_ledger([a, b], as_of=date(2026, 9, 25))
    ident = ledger["identities"][0]
    assert ident["record_count"] == 2
    assert ident["counted_flight_count"] == 1
    assert ident["superseded_count"] == 1
