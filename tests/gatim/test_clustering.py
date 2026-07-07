from pathlib import Path

from tools.gatim.core.dedupe import assign_clusters, haversine_m
from tools.gatim.core.normalizer import normalize_many

FIXTURES = Path(__file__).parent / "fixtures" / "sanitized_seed"
FILES = ["context.csv", "access.csv", "ilap.csv", "poi.csv", "recon.csv", "anomaly.csv"]


def test_5m_clusters_close_points():
    rows = assign_clusters(normalize_many(FIXTURES / name for name in FILES), radius_m=5.0)
    direct_rows = [row for row in rows if row.coord_status == "direct"]
    assert len({row.dedupe_cluster_id for row in direct_rows}) == 4


def test_haversine_zero_distance():
    assert haversine_m(18.0, -66.0, 18.0, -66.0) == 0
