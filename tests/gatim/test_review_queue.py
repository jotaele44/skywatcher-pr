from pathlib import Path

from tools.gatim.core.classifier import apply_classification
from tools.gatim.core.dedupe import assign_clusters
from tools.gatim.core.normalizer import normalize_many
from tools.gatim.core.review_queue import sort_for_review

FIXTURES = Path(__file__).parent / "fixtures" / "sanitized_seed"
FILES = ["context.csv", "access.csv", "ilap.csv", "poi.csv", "recon.csv", "anomaly.csv"]


def test_review_queue_places_geocode_later():
    rows = apply_classification(assign_clusters(normalize_many(FIXTURES / name for name in FILES)))
    sorted_rows = sort_for_review(rows)
    assert sorted_rows[-1].coord_status == "needs_geocode"
