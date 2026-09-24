from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timedelta, timezone

import pytest

from skywatcher.core.spacetrack.adapters import normalize_decay, normalize_gp
from skywatcher.core.spacetrack.collector import SpaceTrackCollector
from skywatcher.core.spacetrack.contracts import SOURCE_CONTRACTS, get_source_contract
from skywatcher.core.spacetrack.control_plane import (
    archive_snapshot,
    classify_archive_equivalence,
    classify_decay_stage,
    RateGate,
    schema_snapshot,
    set_comparison,
    source_arithmetic,
    SpaceTrackControlPlane,
)
from skywatcher.core.spacetrack.materialize import (
    materialize_space_objects,
    materialize_stored_space_objects,
)
from skywatcher.core.spacetrack.models import (
    CertificationState,
    DistributionClass,
    Manifestation,
    Watermark,
)
from skywatcher.core.spacetrack.query import build_incremental_query
from skywatcher.core.spacetrack.storage import SpaceTrackStore
from skywatcher.core.spacetrack.transport import TransportResponse


UTC = timezone.utc


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []

    def get(self, url: str) -> TransportResponse:
        self.urls.append(url)
        if not self.responses:
            raise AssertionError("unexpected transport call")
        return self.responses.pop(0)


def _json_response(payload, status=200):
    return TransportResponse(
        status=status,
        body=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


def _zip_bytes(path: str, content: bytes, *, compression: int) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=compression) as archive:
        archive.writestr(path, content)
    return out.getvalue()


def test_source_denominator_contains_required_v1_classes():
    ids = {row.source_id for row in SOURCE_CONTRACTS}
    assert {
        "satcat",
        "satcat_change",
        "satcat_debut",
        "gp",
        "gp_history",
        "decay",
        "decay_60day",
        "tip",
        "cdm_public",
        "publicfiles",
        "publicfile_download",
        "organization",
        "boxscore",
        "launch_site",
        "announcement",
        "curated_favorites",
    } <= ids


def test_space_track_manifestations_fail_closed_for_redistribution():
    assert get_source_contract("satcat").distribution_class is DistributionClass.ACCOUNT_ONLY
    assert get_source_contract("publicfiles").distribution_class is DistributionClass.ACCOUNT_ONLY

    control = SpaceTrackControlPlane()
    manifestation = Manifestation(
        source_id="satcat",
        controller="basicspacedata",
        query="q",
        retrieved_utc="2026-09-24T19:00:00Z",
        raw_sha256="a" * 64,
        byte_count=1,
        row_count=1,
        schema_sha256=None,
        distribution_class=DistributionClass.ACCOUNT_ONLY,
    )
    with pytest.raises(PermissionError):
        control.assert_redistributable(manifestation)


def test_gp_query_is_bulk_current_propagable_and_omm_capable():
    query = build_incremental_query("gp", output_format="xml")
    url = query.to_url()
    assert "/class/gp/" in url
    assert "/DECAY_DATE/null-val/" in url
    assert "/EPOCH/%3Enow-10/" in url
    assert "/orderby/GP_ID%20asc/" in url
    assert "/format/xml/" in url


def test_gp_query_advances_from_creation_date_watermark():
    query = build_incremental_query(
        "gp",
        Watermark("gp", "CREATION_DATE", "2026-09-24 18:59:00"),
    )
    assert "/CREATION_DATE/%3E2026-09-24%2018%3A59%3A00/" in query.to_url()


def test_publicfiles_and_sixty_day_queries_are_bounded():
    publicfiles = build_incremental_query("publicfiles")
    assert publicfiles.to_url() == (
        "https://www.space-track.org/publicfiles/query/class/loadpublicdata"
    )

    sixty_day = build_incremental_query("decay_60day").to_url()
    assert "/SOURCE/60day_msg/" in sixty_day
    assert "/DECAY_EPOCH/now--now%2B60/" in sixty_day


def test_incremental_queries_use_source_specific_watermarks():
    satcat = build_incremental_query("satcat", Watermark("satcat", "FILE", "9250"))
    assert "/FILE/%3E9250/" in satcat.to_url()

    debut = build_incremental_query(
        "satcat_debut",
        Watermark("satcat_debut", "DEBUT", "2026-09-23"),
    )
    assert "/DEBUT/%3E2026-09-23/" in debut.to_url()

    tip = build_incremental_query(
        "tip",
        Watermark("tip", "INSERT_EPOCH", "2026-09-24 18:00:00"),
    )
    assert "/INSERT_EPOCH/%3E2026-09-24%2018%3A00%3A00/" in tip.to_url()


def test_rate_gate_enforces_source_cadence_and_global_only_schema_calls():
    gate = RateGate()
    now = datetime(2026, 9, 24, 19, 0, tzinfo=UTC)

    gate.record_global(now)
    allowed, reason = gate.can_request("gp", now)
    assert allowed is True
    assert reason is None

    gate.record("gp", now)
    allowed, reason = gate.can_request("gp", now + timedelta(minutes=30))
    assert allowed is False
    assert reason == "SOURCE_CADENCE"
    allowed, reason = gate.can_request("gp", now + timedelta(hours=1))
    assert allowed is True
    assert reason is None


def test_gp_history_has_no_source_wide_lockout():
    gate = RateGate()
    now = datetime(2026, 9, 24, 19, 0, tzinfo=UTC)
    gate.record("gp_history", now)
    allowed, reason = gate.can_request("gp_history", now + timedelta(seconds=1))
    assert allowed is True
    assert reason is None


def test_publicfiles_cadence_is_eight_hours():
    gate = RateGate()
    now = datetime(2026, 9, 24, 19, 0, tzinfo=UTC)
    gate.record("publicfiles", now)
    assert gate.can_request("publicfiles", now + timedelta(hours=7, minutes=59))[0] is False
    assert gate.can_request("publicfiles", now + timedelta(hours=8))[0] is True


def test_publicfile_download_enforces_ten_per_fifteen_minute_window():
    gate = RateGate()
    now = datetime(2026, 9, 24, 19, 0, tzinfo=UTC)
    for index in range(10):
        gate.record("publicfile_download", now + timedelta(seconds=index))
    allowed, reason = gate.can_request(
        "publicfile_download",
        now + timedelta(minutes=14, seconds=59),
    )
    assert allowed is False
    assert reason == "SOURCE_WINDOW_LIMIT"
    assert gate.can_request("publicfile_download", now + timedelta(minutes=15))[0] is True


def test_schema_drift_blocks_normalized_promotion():
    control = SpaceTrackControlPlane()
    first = schema_snapshot(
        "satcat",
        [{"name": "NORAD_CAT_ID"}, {"name": "SATNAME"}],
        "2026-09-24T19:00:00Z",
    )
    same = schema_snapshot(
        "satcat",
        [{"name": "NORAD_CAT_ID"}, {"name": "SATNAME"}],
        "2026-09-24T20:00:00Z",
    )
    changed = schema_snapshot(
        "satcat",
        [{"name": "NORAD_CAT_ID"}, {"name": "SATNAME"}, {"name": "NEW_FIELD"}],
        "2026-09-24T21:00:00Z",
    )

    assert control.register_schema(first) is True
    assert control.schema_promotion_allowed("satcat") is True
    assert control.register_schema(same) is True
    assert control.schema_promotion_allowed("satcat") is True
    assert control.register_schema(changed) is False
    assert control.schema_promotion_allowed("satcat") is False


def test_schema_drift_remains_blocked_across_process_restart(tmp_path):
    store = SpaceTrackStore(tmp_path)
    now = datetime(2026, 9, 24, 19, 0, tzinfo=UTC)

    first = SpaceTrackCollector(
        transport=FakeTransport(
            [_json_response([{"name": "NORAD_CAT_ID"}, {"name": "SATNAME"}])]
        ),
        store=store,
    )
    assert first.capture_modeldef("satcat", now=now) is True

    changed_payload = [
        {"name": "NORAD_CAT_ID"},
        {"name": "SATNAME"},
        {"name": "NEW_FIELD"},
    ]
    second = SpaceTrackCollector(
        transport=FakeTransport([_json_response(changed_payload)]),
        store=store,
    )
    assert second.capture_modeldef("satcat", now=now + timedelta(days=1)) is False

    third = SpaceTrackCollector(
        transport=FakeTransport([_json_response(changed_payload)]),
        store=store,
    )
    assert third.capture_modeldef("satcat", now=now + timedelta(days=2)) is False


def test_archive_identity_classification_distinguishes_recompression_and_paths():
    stored = _zip_bytes("ephemeris.oem", b"same payload", compression=zipfile.ZIP_STORED)
    deflated = _zip_bytes("ephemeris.oem", b"same payload", compression=zipfile.ZIP_DEFLATED)
    renamed = _zip_bytes("renamed.oem", b"same payload", compression=zipfile.ZIP_DEFLATED)
    changed = _zip_bytes("ephemeris.oem", b"different", compression=zipfile.ZIP_DEFLATED)

    a = archive_snapshot(stored)
    b = archive_snapshot(deflated)
    c = archive_snapshot(renamed)
    d = archive_snapshot(changed)

    assert classify_archive_equivalence(a, a) == "BYTE_IDENTICAL"
    assert classify_archive_equivalence(a, b) == "PURE_RECOMPRESSION"
    assert classify_archive_equivalence(a, c) == "SAME_PAYLOADS_DIFFERENT_PATHS"
    assert classify_archive_equivalence(a, d) == "DISTINCT_PAYLOADS"


def test_source_arithmetic_fails_closed():
    assert source_arithmetic(10, 8, 2).closes is True
    with pytest.raises(ValueError):
        source_arithmetic(10, 8, 1)


def test_cross_source_set_comparison_preserves_full_difference_sets():
    result = set_comparison(
        [{"NORAD_CAT_ID": "1"}, {"NORAD_CAT_ID": "2"}],
        [{"NORAD_CAT_ID": "2"}, {"NORAD_CAT_ID": "3"}],
    )
    assert result == {
        "intersection": {"2"},
        "a_only": {"1"},
        "b_only": {"3"},
        "union": {"1", "2", "3"},
        "symmetric_difference": {"1", "3"},
    }


def test_nine_digit_norad_id_is_preserved_as_string():
    normalized = normalize_gp(
        {
            "GP_ID": "900000001",
            "NORAD_CAT_ID": "123456789",
            "OBJECT_ID": "2026-001A",
            "EPOCH": "2026-09-24T19:00:00.000000",
        }
    )
    assert normalized["norad_cat_id"] == "123456789"
    assert normalized["raw"]["NORAD_CAT_ID"] == "123456789"



def test_materializer_uses_stable_ids_and_preserves_aliases_without_name_merge():
    satcat = [
        {
            "norad_cat_id": "49277",
            "object_id": "1998-067SW",
            "object_name": "PRCUNAR2",
            "raw": {"FILE": "9250"},
        },
        {
            "norad_cat_id": "49277",
            "object_id": "1998-067SW",
            "object_name": "PR-CuNaR2",
            "raw": {"FILE": "9251"},
        },
    ]
    gp = [
        {
            "gp_id": "10",
            "norad_cat_id": "49277",
            "object_id": "1998-067SW",
            "object_name": "PRCUNAR2",
            "creation_date": "2022-08-29 12:00:00",
            "raw": {},
        }
    ]

    result = materialize_space_objects(satcat, gp)

    assert result.object_count == 1
    assert result.unmatched_satcat == ()
    assert result.unmatched_gp == ()
    obj = result.objects[0]
    assert obj.catalog_key == "space-track:norad:49277"
    assert obj.identity_state is CertificationState.PASS
    assert obj.satcat_row["raw"]["FILE"] == "9251"
    assert obj.gp_row["gp_id"] == "10"
    assert obj.aliases == ("PR-CuNaR2", "PRCUNAR2")


def test_materializer_fails_closed_on_identifier_cardinality_conflict():
    satcat = [
        {
            "norad_cat_id": "49277",
            "object_id": "1998-067SW",
            "object_name": "PRCUNAR2",
            "raw": {"FILE": "9250"},
        },
        {
            "norad_cat_id": "49277",
            "object_id": "DIFFERENT-ID",
            "object_name": "PRCUNAR2",
            "raw": {"FILE": "9251"},
        },
    ]

    result = materialize_space_objects(satcat, [])

    assert result.objects[0].identity_state is CertificationState.UNRESOLVED
    assert any(item.category == "IDENTITY" for item in result.contradictions)


def test_materializer_does_not_merge_name_only_rows():
    satcat = [
        {"norad_cat_id": None, "object_id": None, "object_name": "SAME NAME", "raw": {}},
        {"norad_cat_id": None, "object_id": None, "object_name": "SAME NAME", "raw": {}},
    ]
    result = materialize_space_objects(satcat, [])
    assert result.object_count == 0


def test_decay_precedence_mapping_is_explicit():
    assert classify_decay_stage(4) == "SIXTY_DAY_PREDICTION"
    assert classify_decay_stage("3") == "TIP_PREDICTION"
    assert classify_decay_stage(2) == "DECAY_ANNOUNCEMENT"
    assert classify_decay_stage("1") == "SATCAT_CURRENT_DECAY"
    assert classify_decay_stage(None) == "UNRESOLVED"


def test_prcunar2_decay_history_retains_all_assertions_without_latest_row_collapse():
    rows = [
        {
            "NORAD_CAT_ID": "49277",
            "SATNAME": "PRCUNAR2",
            "INTLDES": "1998-067SW",
            "COUNTRY": "PRI",
            "MSG_EPOCH": "2026-07-29 18:59:26",
            "DECAY_EPOCH": "2022-08-30 0:00:00",
            "SOURCE": "satcat",
            "PRECEDENCE": 1,
        },
        {
            "NORAD_CAT_ID": "49277",
            "SATNAME": "PRCUNAR2",
            "INTLDES": "1998-067SW",
            "COUNTRY": "PRI",
            "MSG_EPOCH": "2022-08-31 16:11:00",
            "DECAY_EPOCH": "2022-08-30 0:00:00",
            "SOURCE": "decay_msg",
            "PRECEDENCE": 2,
        },
        {
            "NORAD_CAT_ID": "49277",
            "MSG_EPOCH": "2022-07-13 22:01:24",
            "DECAY_EPOCH": "2022-09-01 0:00:00",
            "SOURCE": "60day_msg",
            "PRECEDENCE": 4,
        },
        {
            "NORAD_CAT_ID": "49277",
            "MSG_EPOCH": "2022-07-20 21:38:34",
            "DECAY_EPOCH": "2022-08-28 0:00:00",
            "SOURCE": "60day_msg",
            "PRECEDENCE": 4,
        },
        {
            "NORAD_CAT_ID": "49277",
            "MSG_EPOCH": "2022-07-28 02:27:23",
            "DECAY_EPOCH": "2022-09-04 0:00:00",
            "SOURCE": "60day_msg",
            "PRECEDENCE": 4,
        },
        {
            "NORAD_CAT_ID": "49277",
            "MSG_EPOCH": "2022-08-04 01:26:01",
            "DECAY_EPOCH": "2022-09-04 0:00:00",
            "SOURCE": "60day_msg",
            "PRECEDENCE": 4,
        },
        {
            "NORAD_CAT_ID": "49277",
            "MSG_EPOCH": "2022-08-11 01:06:43",
            "DECAY_EPOCH": "2022-08-31 0:00:00",
            "SOURCE": "60day_msg",
            "PRECEDENCE": 4,
        },
        {
            "NORAD_CAT_ID": "49277",
            "MSG_EPOCH": "2022-08-19 03:40:16",
            "DECAY_EPOCH": "2022-08-29 0:00:00",
            "SOURCE": "60day_msg",
            "PRECEDENCE": 4,
        },
        {
            "NORAD_CAT_ID": "49277",
            "MSG_EPOCH": "2022-08-25 06:04:02",
            "DECAY_EPOCH": "2022-08-30 0:00:00",
            "SOURCE": "60day_msg",
            "PRECEDENCE": 4,
        },
    ]

    normalized = [normalize_decay(row) for row in rows]
    assert len(normalized) == 9
    assert sum(row["assertion_role"] == "PREDICTION" for row in normalized) == 7
    assert sum(row["assertion_role"] == "HISTORICAL" for row in normalized) == 2
    assert {
        row["decay_epoch"]
        for row in normalized
        if row["assertion_role"] == "HISTORICAL"
    } == {"2022-08-30 0:00:00"}
    assert normalized[0]["raw"]["MSG_EPOCH"] == "2026-07-29 18:59:26"


def test_collector_freezes_raw_bytes_but_blocks_normalization_without_schema(tmp_path):
    transport = FakeTransport(
        [_json_response([{"NORAD_CAT_ID": "49277", "SATNAME": "PRCUNAR2"}])]
    )
    store = SpaceTrackStore(tmp_path)
    collector = SpaceTrackCollector(transport=transport, store=store)
    now = datetime(2026, 9, 24, 19, 0, tzinfo=UTC)

    result = collector.collect_json("satcat", now=now)
    assert result.state is CertificationState.PROVISIONAL
    assert result.blocker == "SCHEMA_UNVERIFIED_OR_DRIFTED"
    assert len(result.rows) == 1
    assert result.normalized_rows == ()
    assert result.manifestation is not None
    raw_path = (
        tmp_path
        / "raw"
        / "satcat"
        / result.manifestation.raw_sha256
        / "payload.bin"
    )
    assert raw_path.exists()


def test_collector_promotes_only_after_modeldef_baseline(tmp_path):
    transport = FakeTransport(
        [
            _json_response([{"name": "NORAD_CAT_ID"}, {"name": "SATNAME"}]),
            _json_response(
                [{"NORAD_CAT_ID": "49277", "SATNAME": "PRCUNAR2", "FILE": "9251"}]
            ),
        ]
    )
    store = SpaceTrackStore(tmp_path)
    collector = SpaceTrackCollector(transport=transport, store=store)
    now = datetime(2026, 9, 24, 19, 0, tzinfo=UTC)

    assert collector.capture_modeldef("satcat", now=now) is True
    result = collector.collect_json("satcat", now=now)
    assert result.state is CertificationState.PASS
    assert result.normalized_rows[0]["norad_cat_id"] == "49277"



def test_missing_incremental_watermark_blocks_persistence(tmp_path):
    transport = FakeTransport(
        [
            _json_response([{"name": "NORAD_CAT_ID"}, {"name": "CREATION_DATE"}]),
            _json_response([{"NORAD_CAT_ID": "49277", "EPOCH": "2022-08-29"}]),
        ]
    )
    store = SpaceTrackStore(tmp_path)
    collector = SpaceTrackCollector(transport=transport, store=store)
    now = datetime(2026, 9, 24, 19, 0, tzinfo=UTC)

    assert collector.capture_modeldef("gp", now=now) is True
    result = collector.collect_json("gp", now=now)

    assert result.state is CertificationState.PROVISIONAL
    assert result.blocker == "WATERMARK_MISSING"
    assert store.load_watermark("gp") is None
    assert store.load_normalized_batches("gp") == ()


def test_stored_batches_materialize_into_frozen_current_view(tmp_path):
    transport = FakeTransport(
        [
            _json_response([{"name": "NORAD_CAT_ID"}, {"name": "FILE"}]),
            _json_response([{"name": "NORAD_CAT_ID"}, {"name": "CREATION_DATE"}]),
            _json_response(
                [
                    {
                        "NORAD_CAT_ID": "49277",
                        "INTLDES": "1998-067SW",
                        "SATNAME": "PRCUNAR2",
                        "FILE": "9251",
                    }
                ]
            ),
            _json_response(
                [
                    {
                        "GP_ID": "100",
                        "NORAD_CAT_ID": "49277",
                        "OBJECT_ID": "1998-067SW",
                        "OBJECT_NAME": "PRCUNAR2",
                        "CREATION_DATE": "2026-09-24 18:59:00",
                        "EPOCH": "2026-09-24 18:00:00",
                    }
                ]
            ),
        ]
    )
    store = SpaceTrackStore(tmp_path)
    collector = SpaceTrackCollector(transport=transport, store=store)
    now = datetime(2026, 9, 24, 19, 0, tzinfo=UTC)

    assert collector.capture_modeldef("satcat", now=now) is True
    assert collector.capture_modeldef("gp", now=now) is True
    assert collector.collect_json("satcat", now=now).state is CertificationState.PASS
    assert collector.collect_json("gp", now=now).state is CertificationState.PASS

    result, digest = materialize_stored_space_objects(store)
    frozen = store.load_materialization("space_objects")

    assert len(digest) == 64
    assert result.object_count == 1
    assert result.objects[0].norad_cat_id == "49277"
    assert frozen["object_count"] == 1
    assert frozen["objects"][0]["norad_cat_id"] == "49277"


def test_gp_history_reuses_frozen_query_instead_of_redownloading(tmp_path):
    query = (
        build_incremental_query("gp_history")
        .with_filter("NORAD_CAT_ID", "49277")
        .with_filter("EPOCH", "2022-08-01--2022-08-31")
    )
    transport = FakeTransport([_json_response([{"NORAD_CAT_ID": "49277"}])])
    collector = SpaceTrackCollector(
        transport=transport,
        store=SpaceTrackStore(tmp_path),
    )
    now = datetime(2026, 9, 24, 19, 0, tzinfo=UTC)

    first = collector.collect_json("gp_history", now=now, query=query)
    second = collector.collect_json(
        "gp_history",
        now=now + timedelta(seconds=1),
        query=query,
    )

    assert first.state is CertificationState.PROVISIONAL
    assert second.state is CertificationState.AUDIT_ONLY
    assert second.blocker == "ALREADY_ACQUIRED"
    assert len(transport.urls) == 1


def test_publicfiles_inventory_does_not_require_basic_modeldef(tmp_path):
    transport = FakeTransport(
        [
            _json_response(
                [
                    {
                        "SOURCE": "NASA-JSC",
                        "TYPE": "Ephemeris",
                        "DATE": "2026-09-23 20:09:28",
                        "LINK": "temporary",
                        "SIZE": "408.03 KB",
                    }
                ]
            )
        ]
    )
    collector = SpaceTrackCollector(
        transport=transport,
        store=SpaceTrackStore(tmp_path),
    )
    result = collector.collect_json(
        "publicfiles",
        now=datetime(2026, 9, 24, 19, 0, tzinfo=UTC),
    )

    assert result.state is CertificationState.PASS
    assert result.normalized_rows[0]["source"] == "NASA-JSC"
    assert result.normalized_rows[0]["type"] == "Ephemeris"


def test_publicfile_download_is_frozen_once_per_filename_query(tmp_path):
    payload = _zip_bytes(
        "iss.oem",
        b"CCSDS_OEM_VERS = 2.0\n",
        compression=zipfile.ZIP_DEFLATED,
    )
    transport = FakeTransport(
        [TransportResponse(status=200, body=payload, headers={"content-type": "application/zip"})]
    )
    collector = SpaceTrackCollector(
        transport=transport,
        store=SpaceTrackStore(tmp_path),
    )
    now = datetime(2026, 9, 24, 19, 0, tzinfo=UTC)

    first = collector.download_public_file("NASAJSC_Ephemeris_example.zip", now=now)
    second = collector.download_public_file(
        "NASAJSC_Ephemeris_example.zip",
        now=now + timedelta(seconds=1),
    )

    assert first.state is CertificationState.PASS
    assert first.archive is not None
    assert first.archive.members[0].path == "iss.oem"
    assert second.state is CertificationState.AUDIT_ONLY
    assert second.blocker == "ALREADY_ACQUIRED"
    assert len(transport.urls) == 1


def test_collector_classifies_unauthorized_controller_without_guessing(tmp_path):
    transport = FakeTransport([_json_response({"detail": "forbidden"}, status=403)])
    collector = SpaceTrackCollector(
        transport=transport,
        store=SpaceTrackStore(tmp_path),
    )
    now = datetime(2026, 9, 24, 19, 0, tzinfo=UTC)

    result = collector.collect_json("organization", now=now)
    assert result.state is CertificationState.BLOCKED
    assert result.blocker == "UNAUTHORIZED"
