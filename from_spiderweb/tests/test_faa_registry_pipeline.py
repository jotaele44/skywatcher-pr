import csv
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "faa_registry_pipeline.py"
FIX = ROOT / "tests" / "fixtures"


def test_pipeline_sample(tmp_path):
    out = tmp_path / "out"
    cmd = [
        sys.executable,
        str(SCRIPT),
        "--registrations",
        str(FIX / "regs.txt"),
        "--faa-dir",
        str(FIX / "faa_registry_sample"),
        "--output-dir",
        str(out),
        "--no-extract",
    ]
    result = subprocess.run(cmd, check=True, text=True, capture_output=True)
    summary = json.loads(result.stdout)
    assert summary["target_count"] == 3
    assert summary["matched_master_count"] == 2
    assert summary["matched_deregistered_count"] == 1
    rows = list(csv.DictReader((out / "faa_registry_consolidated.csv").open()))
    by_reg = {r["registration"]: r for r in rows}
    assert by_reg["N196DM"]["aircraft_manufacturer"] == "BELL"
    assert by_reg["N407PR"]["type_aircraft_label"] == "Rotorcraft"
    assert by_reg["N999ZZ"]["match_status"] == "deregistered"
