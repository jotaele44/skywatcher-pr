import json
from pathlib import Path

from tools.gatim.runner import build

FIXTURES = Path(__file__).parent / "fixtures" / "sanitized_seed"
FILES = ["context.csv", "access.csv", "ilap.csv", "poi.csv", "recon.csv", "anomaly.csv"]


def test_runner_writes_all_outputs(tmp_path):
    metrics = build(FIXTURES, tmp_path, files=FILES)
    assert metrics == {"rows": 6, "direct": 5, "needs_geocode": 1, "missing": 0}
    expected = [
        "GATIM_CALIBRATION_LEDGER_v1.csv",
        "GATIM_REVIEW_QUEUE_v1.csv",
        "GATIM_GEOCODE_QUEUE_v1.csv",
        "GATIM_CANDIDATES_v1.geojson",
        "GATIM_REVIEW_QUEUE_v1.geojson",
    ]
    assert all((tmp_path / name).exists() for name in expected)
    payload = json.loads((tmp_path / "GATIM_CANDIDATES_v1.geojson").read_text())
    assert payload["type"] == "FeatureCollection"
    assert len(payload["features"]) == 5
