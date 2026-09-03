from skywatcher.geometry_format_policy import assess_track_twkb


def base(**overrides):
    values = dict(
        source_frozen=True,
        crs="EPSG:4326",
        dimension="XYZ",
        xy_precision=6,
        z_precision=2,
        roundtrip_ok=True,
        type_conserved=True,
        validity_conserved=True,
        vertex_count_conserved=True,
        application_tolerance=1e-6,
        observed_max_error=5e-7,
        canonical_track_retained=True,
    )
    values.update(overrides)
    return values


def test_admitted_track_is_noncanonical():
    assert assess_track_twkb(**base()).state == "NONCANONICAL"


def test_missing_crs_is_blocked():
    assert assess_track_twkb(**base(crs=None)).state == "BLOCKED"


def test_xyz_requires_z_precision():
    assert assess_track_twkb(**base(z_precision=None)).state == "BLOCKED"


def test_vertex_change_fails():
    assert assess_track_twkb(**base(vertex_count_conserved=False)).state == "FAIL"


def test_twkb_cannot_be_sole_track():
    assert assess_track_twkb(**base(canonical_track_retained=False)).state == "FAIL"
