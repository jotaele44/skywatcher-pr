from pathlib import Path

from tools.gatim.cli import build
from tools.gatim.gatim_classifier import apply_classification
from tools.gatim.gatim_dedupe import assign_clusters, haversine_m
from tools.gatim.gatim_normalizer import extract_coords, normalize_many
from tools.gatim.satim_gatim_interface import link_to_fn_points

DATA = Path(__file__).parent / "fixtures" / "gatim"
FILES = [
    "UAP.csv",
    "access.csv",
    "ilap.csv",
    "poi.csv",
    "recon.csv",
    "anomaly.csv",
]


def test_decimal_coordinate_extraction():
    lat, lon, status, _ = extract_coords("https://www.google.com/maps/search/18.0244757,-66.6632832")
    assert status == "direct"
    assert lat == "18.0244757"
    assert lon == "-66.6632832"


def test_dms_coordinate_extraction():
    lat, lon, status, _ = extract_coords("29°40'00.0\"N 65°35'00.0\"W")
    assert status == "direct"
    assert abs(float(lat) - 29.6666667) < 0.00001
    assert abs(float(lon) + 65.5833333) < 0.00001


def test_six_sanitized_fixtures_ingest():
    rows = normalize_many(DATA / name for name in FILES)
    assert len(rows) == 6
    assert sum(row.coord_status == "direct" for row in rows) == 5
    assert sum(row.coord_status == "needs_geocode" for row in rows) == 1


def test_5m_dedupe_collapses_close_points():
    rows = assign_clusters(normalize_many(DATA / name for name in FILES), radius_m=5.0)
    direct_rows = [row for row in rows if row.coord_status == "direct"]
    clusters = {row.dedupe_cluster_id for row in direct_rows}
    assert len(direct_rows) == 5
    assert len(clusters) == 4
    duplicate_clusters = {
        row.dedupe_cluster_id
        for row in direct_rows
        if row.dedupe_cluster_size.isdigit() and int(row.dedupe_cluster_size) > 1
    }
    assert len(duplicate_clusters) == 1


def test_classifier_assigns_expected_classes_without_confirming_anomaly():
    rows = apply_classification(assign_clusters(normalize_many(DATA / name for name in FILES)))
    by_file = {row.source_file: row for row in rows}
    assert by_file["UAP.csv"].class_primary == "UAP_CASE_ANCHOR"
    assert by_file["access.csv"].class_primary == "ACCESS"
    assert by_file["ilap.csv"].class_primary == "ILAP"
    assert by_file["anomaly.csv"].class_primary == "TERRAIN_ANOMALY"
    assert all("CONFIRMED" not in row.review_priority for row in rows)


def test_satim_gatim_interface_nearby_fn_link_is_candidate_only():
    rows = apply_classification(assign_clusters(normalize_many([DATA / "access.csv"])))
    target = next(row for row in rows if row.coord_status == "direct")
    links = link_to_fn_points([target], [{"fn_id": "FN_TEST", "lat": target.lat, "lon": target.lon}], radius_m=250)
    assert len(links) == 1
    assert links[0].link_status == "confirmed_overlap"
    assert links[0].distance_m <= 1


def test_cli_build_writes_outputs(tmp_path):
    metrics = build(DATA, tmp_path, files=FILES)
    assert metrics == {"rows": 6, "direct": 5, "needs_geocode": 1, "missing": 0}
    assert (tmp_path / "GATIM_CALIBRATION_LEDGER_v1.csv").exists()
    assert (tmp_path / "GATIM_REVIEW_QUEUE_v1.csv").exists()


def test_haversine_sanity():
    assert haversine_m(18.0, -66.0, 18.0, -66.0) == 0
