from pathlib import Path

from tools.gatim.core.classifier import apply_classification
from tools.gatim.core.dedupe import assign_clusters
from tools.gatim.core.normalizer import normalize_many
from tools.gatim.interfaces.satim_bridge import link_to_fn_points

FIXTURES = Path(__file__).parent / "fixtures" / "sanitized_seed"


def test_bridge_is_proximity_only():
    rows = apply_classification(assign_clusters(normalize_many([FIXTURES / "access.csv"])))
    row = rows[0]
    links = link_to_fn_points([row], [{"fn_id": "FN_TEST", "lat": row.lat, "lon": row.lon}], radius_m=250)
    assert links[0].link_status == "coordinate_overlap"
    assert links[0].link_note == "proximity_only"
