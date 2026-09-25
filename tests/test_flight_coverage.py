from __future__ import annotations

from datetime import date

from skywatcher.fr24.flight_coverage import (
    UNRESOLVED_IDENTITY,
    build_coverage_ledger,
)


def _ledger(records, *, as_of=date(2026, 9, 25), watchlist=()):
    return build_coverage_ledger(records, as_of=as_of, watchlist=watchlist)


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
    ledger = _ledger(records, as_of=date(2026, 2, 20))
    assert ledger["identities"][0]["median_cadence_days"] == 22.5
    assert ledger["gaps"] == []


def test_internal_gap_is_classified_against_365_day_lookback():
    records = [
        _record("N1", "2025-01-01", uid="mfl:00000001"),
        _record("N1", "2025-01-02", uid="mfl:00000002"),
        _record("N1", "2025-01-03", uid="mfl:00000003"),
        _record("N1", "2025-05-01", uid="mfl:00000004"),
        _record("N1", "2025-05-02", uid="mfl:00000005"),
        _record("N1", "2026-09-01", uid="mfl:00000006"),
    ]
    ledger = _ledger(records, as_of=date(2026, 9, 25))
    states = {(item["from"], item["to"]): item["state"] for item in ledger["gaps"]}
    assert states[("2025-01-03", "2025-04-30")] == "BEYOND_LOOKBACK"
    assert states[("2025-05-02", "2026-08-31")] == "PARTLY_RECOVERABLE"


def test_recent_internal_gap_is_recoverable():
    records = [
        _record("N1", "2026-07-01", uid="mfl:00000001"),
        _record("N1", "2026-07-02", uid="mfl:00000002"),
        _record("N1", "2026-07-03", uid="mfl:00000003"),
        _record("N1", "2026-08-20", uid="mfl:00000004"),
    ]
    ledger = _ledger(records, as_of=date(2026, 9, 25))
    assert ledger["gaps"][0]["state"] == "RECOVERABLE"
    assert ledger["gaps"][0]["recoverable_days"] == ledger["gaps"][0]["days"]


def test_blank_callsign_single_folder_is_provisional_not_registration():
    records = [_record(None, "2026-09-01", uid="mfl:00000001", folder="N123AB")]
    ledger = _ledger(records, as_of=date(2026, 9, 25))
    ident = ledger["identities"][0]
    assert ident["identity"] == "N123AB"
    assert ident["identity_state"] == "PROVISIONAL_FOLDER_IDENTITY"
    assert any(item["type"] == "VERIFY" for item in ledger["acquisition_queue"])


def test_blank_callsign_generic_folder_stays_unresolved():
    records = [_record(None, "2026-09-01", uid="mfl:00000001", folder="csv")]
    ledger = _ledger(records, as_of=date(2026, 9, 25))
    assert ledger["identities"][0]["identity"] == UNRESOLVED_IDENTITY
    assert ledger["identities"][0]["identity_state"] == "UNRESOLVED"


def test_missing_kml_is_acquisition_state_not_missing_flight():
    records = [_record("N1", "2026-09-20", uid="mfl:00000001", kml=False)]
    ledger = _ledger(records, as_of=date(2026, 9, 25))
    queue = ledger["acquisition_queue"]
    assert any(item["type"] == "KML" for item in queue)
    item = next(item for item in queue if item["type"] == "KML")
    assert "not missing-flight evidence" in item["evidence_note"]


def test_stale_and_dormant_are_separate_activity_states():
    recent = _ledger(
        [
            _record("N1", "2026-09-01", uid="mfl:00000001"),
            _record("N1", "2026-09-02", uid="mfl:00000002"),
            _record("N1", "2026-09-03", uid="mfl:00000003"),
        ],
        as_of=date(2026, 9, 25),
    )
    stale = next(item for item in recent["acquisition_queue"] if item["type"] == "STALE")
    assert stale["activity_state"] == "ACTIVE_RECENTLY"

    old = _ledger(
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

    ledger = _ledger([a, b])
    ident = ledger["identities"][0]
    assert ident["record_count"] == 2
    assert ident["counted_flight_count"] == 1
    assert ident["superseded_count"] == 1


def test_watchlist_identity_with_no_records_gets_full_lookback_queue():
    ledger = _ledger([], watchlist=("C6062",))
    ident = next(item for item in ledger["identities"] if item["identity"] == "C6062")
    assert ident["identity_state"] == "WATCHLIST_ONLY"
    watch = next(item for item in ledger["acquisition_queue"] if item["type"] == "WATCH")
    assert watch["identity"] == "C6062"
    assert watch["from"] == "2025-09-25"
    assert watch["to"] == "2026-09-25"
    assert watch["state"] == "RECOVERABLE"
    assert watch["priority_tier"] in {"P1", "P2"}


def test_header_only_file_gets_flight_id_date_estimate_and_empty_queue():
    records = [
        _record("N1", "2026-01-01", uid="mfl:00000010"),
        _record("N1", "2026-01-11", uid="mfl:00000020"),
        _record("N1", "2026-01-01", uid="mfl:00000018", points=0),
    ]
    records[-1]["startTimeUtc"] = "1970-01-01T00:00:00.000Z"
    records[-1]["endTimeUtc"] = "1970-01-01T00:00:00.000Z"

    ledger = _ledger(records, as_of=date(2026, 2, 1))
    empty = next(item for item in ledger["acquisition_queue"] if item["type"] == "EMPTY")
    assert empty["source_flight_id_raw"] == "00000018"
    assert empty["estimated_day"] == "2026-01-06"
    assert empty["state"] == "RECOVERABLE"
    assert empty["estimate_edge"] is False


def test_priority_tier_is_explicit_for_gap_queue_item():
    records = [
        _record("N1", "2026-07-01", uid="mfl:00000001"),
        _record("N1", "2026-07-02", uid="mfl:00000002"),
        _record("N1", "2026-08-20", uid="mfl:00000003"),
    ]
    ledger = _ledger(records)
    gap = next(item for item in ledger["acquisition_queue"] if item["type"] == "GAP")
    assert isinstance(gap["priority_score"], int)
    assert gap["priority_tier"] in {"P1", "P2", "P3", "X"}
    assert gap["deadline"] is not None


def test_generic_csv_folder_does_not_create_misfiled_verification():
    record = _record("N407PR", "2026-09-01", uid="mfl:00000001", folder="csv")
    record["sourceManifestations"].append({
        "folderRaw": "N407PR",
        "filenameRaw": "00000001.csv",
        "kmlPresent": True,
    })
    ledger = _ledger([record])
    assert not any(
        item["type"] == "VERIFY" and item["state"] == "MISFILED"
        for item in ledger["acquisition_queue"]
    )


def test_non_generic_mismatched_folder_creates_misfiled_verification():
    record = _record("N684JB", "2026-08-30", uid="mfl:00000001", folder="N620GG")
    ledger = _ledger([record])
    verify = next(item for item in ledger["acquisition_queue"] if item["type"] == "VERIFY")
    assert verify["identity"] == "N684JB"
    assert verify["state"] == "MISFILED"
    assert verify["record_count"] == 1


def test_multi_folder_blank_callsign_stays_unresolved_and_idconf():
    record = _record(None, "2026-07-11", uid="mfl:00000001", folder="N409TD")
    record["sourceManifestations"].append({
        "folderRaw": "UNRESOLVED_CALLSIGN",
        "filenameRaw": "00000001.csv",
        "kmlPresent": False,
    })
    ledger = _ledger([record])
    ident = next(item for item in ledger["identities"] if item["identity"] == UNRESOLVED_IDENTITY)
    assert ident["identity_state"] == "UNRESOLVED"
    verify = next(item for item in ledger["acquisition_queue"] if item["type"] == "VERIFY")
    assert verify["state"] == "IDCONF"
