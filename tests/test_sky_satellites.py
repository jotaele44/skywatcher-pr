"""SGP4 satellite targets checked against independent published values.

- Vallado et al., "Revisiting Spacetrack Report #3" (AIAA 2006-6753), verification
  object 00005, as shipped in sgp4's tcppver.out (WGS-72, opsmode 'i').
- Skyfield's earth-satellites documentation: ISS seen from 40.8939 N, 83.8917 W
  at 2014-01-23T11:18:07Z (altitude 16 deg 16' 32.6", azimuth 350 deg 15' 20.4",
  range 1168.7 km, astrometric RA 03h19m07.97s, Dec +63 deg 55' 47.2").
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sgp4.propagation import gstime

from skywatcher.core.sky.ephemeris import Observer, SkyFrame
from skywatcher.core.sky.satellites import (
    GPElementError,
    gmst_radians,
    satrec_from_gp_raw,
    topocentric,
    tracked_objects,
)

VANGUARD = {
    "EPOCH": "2000-06-27T18:50:19.733568",
    "MEAN_MOTION": "10.82419157",
    "ECCENTRICITY": "0.1859667",
    "INCLINATION": "34.2682",
    "RA_OF_ASC_NODE": "348.7242",
    "ARG_OF_PERICENTER": "331.7664",
    "MEAN_ANOMALY": "19.3264",
    "BSTAR": "2.8098e-05",
    "MEAN_MOTION_DOT": "2.3e-07",
    "MEAN_MOTION_DDOT": "0",
    "NORAD_CAT_ID": "5",
    "OBJECT_ID": "1958-002B",
    "CLASSIFICATION_TYPE": "U",
    "EPHEMERIS_TYPE": "0",
    "ELEMENT_SET_NO": "475",
    "REV_AT_EPOCH": "41366",
}
ISS_2014 = {
    "EPOCH": "2014-01-20T22:23:04.000416",
    "MEAN_MOTION": "15.49815350",
    "ECCENTRICITY": "0.0003572",
    "INCLINATION": "51.6498",
    "RA_OF_ASC_NODE": "109.4756",
    "ARG_OF_PERICENTER": "55.9686",
    "MEAN_ANOMALY": "274.8005",
    "BSTAR": "1.82e-4",
    "MEAN_MOTION_DOT": "9.878e-05",
    "MEAN_MOTION_DDOT": "0",
    "NORAD_CAT_ID": "25544",
    "OBJECT_ID": "1998-067A",
    "OBJECT_NAME": "ISS (ZARYA)",
    "EPHEMERIS_TYPE": "0",
    "ELEMENT_SET_NO": "508",
    "REV_AT_EPOCH": "86847",
}
ISS_FRAME = SkyFrame(
    Observer(40.8939, -83.8917, 0.0), datetime(2014, 1, 23, 11, 18, 7, tzinfo=timezone.utc)
)


@pytest.mark.parametrize(
    ("tsince", "expected"),
    [
        (0.0, (7022.46529266, -1400.08296755, 0.03995155)),
        (360.0, (-7154.03120202, -3783.17682504, -3536.19412294)),
    ],
)
def test_vallado_verification_object(tsince, expected):
    error, position, _ = satrec_from_gp_raw(VANGUARD).sgp4_tsince(tsince)
    assert error == 0
    assert all(abs(a - b) < 1e-3 for a, b in zip(position, expected, strict=True))


def test_iss_pass_matches_skyfield_reference():
    position = topocentric(satrec_from_gp_raw(ISS_2014), ISS_FRAME)
    assert abs(position.airless_alt_deg - 16.275722) <= 0.02
    assert abs(position.az_deg - 350.255667) <= 0.05
    assert abs(position.range_km - 1168.7) <= 0.5
    assert abs(position.ra_j2000_deg - 49.78321) <= 0.02
    assert abs(position.dec_j2000_deg - 63.92978) <= 0.02
    assert abs(position.element_age_days - 2.538) < 0.01
    assert position.alt_deg > position.airless_alt_deg


def test_gmst_matches_sgp4_reference_implementation():
    for jd, fraction in ((2451545.0, 0.25), (2456680.5, 0.4709), (2461333.5, 0.0208)):
        assert gmst_radians(jd, fraction) == pytest.approx(gstime(jd + fraction), abs=1e-9)


@pytest.mark.parametrize(
    "epoch",
    ["2014-01-20T22:23:04.000416Z", "2014-01-20 22:23:04.000416", "2014-01-20T22:23:04.000416+00:00"],
)
def test_epoch_formats_normalize(epoch):
    reference = satrec_from_gp_raw(ISS_2014)
    variant = satrec_from_gp_raw({**ISS_2014, "EPOCH": epoch})
    assert variant.jdsatepoch + variant.jdsatepochF == pytest.approx(
        reference.jdsatepoch + reference.jdsatepochF, abs=1e-9
    )
    whole = satrec_from_gp_raw({**ISS_2014, "EPOCH": "2014-01-20T22:23:04"})
    assert whole.jdsatepochF == pytest.approx(reference.jdsatepochF, abs=1e-8)


def test_missing_optional_omm_fields_are_padded():
    trimmed = {k: v for k, v in ISS_2014.items()
               if k not in ("OBJECT_ID", "CLASSIFICATION_TYPE", "ELEMENT_SET_NO", "REV_AT_EPOCH")}
    assert satrec_from_gp_raw(trimmed).error == 0


def test_incomplete_or_invalid_rows_are_rejected():
    with pytest.raises(GPElementError, match="MEAN_MOTION"):
        satrec_from_gp_raw({k: v for k, v in ISS_2014.items() if k != "MEAN_MOTION"})
    with pytest.raises(GPElementError):
        topocentric(satrec_from_gp_raw({**ISS_2014, "ECCENTRICITY": "1.5"}), ISS_FRAME)


def test_tracked_objects_reports_every_skip_reason():
    materialization = {
        "objects": [
            {"norad_cat_id": "25544", "identity_state": "PASS", "aliases": ["ISS (ZARYA)"],
             "gp_row": {"object_name": "ISS (ZARYA)", "raw": ISS_2014}},
            {"norad_cat_id": "1", "gp_row": None},
            {"norad_cat_id": "2", "gp_row": {"raw": {**ISS_2014, "EPHEMERIS_TYPE": "2"}}},
            {"norad_cat_id": "3", "gp_row": {"raw": {"NORAD_CAT_ID": "3"}}},
        ]
    }
    tracked, skipped = tracked_objects(materialization)
    assert [item.norad_cat_id for item in tracked] == ["25544"]
    assert tracked[0].name == "ISS (ZARYA)" and tracked[0].identity_state == "PASS"
    reasons = {item["norad_cat_id"]: item["reason"] for item in skipped}
    assert reasons["1"] == "no current GP elements"
    assert reasons["2"] == "unsupported EPHEMERIS_TYPE 2"
    assert reasons["3"].startswith("GP row missing")
