from pathlib import Path

from tools.gatim.core.classifier import apply_classification
from tools.gatim.core.dedupe import assign_clusters
from tools.gatim.core.normalizer import normalize_many

FIXTURES = Path(__file__).parent / "fixtures" / "sanitized_seed"


def test_known_class_labels():
    rows = apply_classification(assign_clusters(normalize_many([FIXTURES / "access.csv", FIXTURES / "ilap.csv"])))
    by_file = {row.source_file: row for row in rows}
    assert by_file["access.csv"].class_primary == "ACCESS"
    assert by_file["ilap.csv"].class_primary == "ILAP"
