"""Tests for strategies #5 and #6 — cluster-first review worklist +
wave-backed harvest-quota targeting."""
from __future__ import annotations

import csv
import datetime
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from rlsm_review_worklist import build_worklist, score_cluster  # noqa: E402
from suggest_harvest_targets import load_wave_index, rank_queue  # noqa: E402


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))


# ──────────────────────────────────────────────────────────────────────────
# strategy #5 — review worklist
# ──────────────────────────────────────────────────────────────────────────

CLUSTERS = [
    {   # aircraft co-occurrence dominates: should rank FIRST despite fewer shots
        "cluster_key": "1170x2532_pad_500_800", "image_dims": "1170x2532",
        "candidate_type": "pad", "grid_x_px": "500", "grid_y_px": "800",
        "n_hits": "40", "n_distinct_screenshots": "10", "n_unique_aircraft": "12",
        "months_active": "2026-03,2026-04", "first_seen": "2026-03-01",
        "last_seen": "2026-04-30", "avg_confidence": "0.7",
        "top_aircraft": "N407PR(6),N999ZY(4)",
    },
    {   # many screenshots, zero aircraft: breadth alone ranks lower
        "cluster_key": "1170x2532_antenna_100_900", "image_dims": "1170x2532",
        "candidate_type": "antenna", "grid_x_px": "100", "grid_y_px": "900",
        "n_hits": "80", "n_distinct_screenshots": "30", "n_unique_aircraft": "0",
        "months_active": "2026-03", "first_seen": "2026-03-01",
        "last_seen": "2026-03-31", "avg_confidence": "0.5", "top_aircraft": "",
    },
    {   # small everything: last
        "cluster_key": "1170x2532_tank_50_700", "image_dims": "1170x2532",
        "candidate_type": "tank", "grid_x_px": "50", "grid_y_px": "700",
        "n_hits": "6", "n_distinct_screenshots": "5", "n_unique_aircraft": "1",
        "months_active": "2026-04", "first_seen": "2026-04-01",
        "last_seen": "2026-04-15", "avg_confidence": "0.4", "top_aircraft": "N1(1)",
    },
]


def test_worklist_ranking_is_aircraft_first_and_deterministic():
    # 3*12 + 10 + 2*2 = 50 > 3*0 + 30 + 2*1 = 32 > 3*1 + 5 + 2*1 = 10
    assert score_cluster(CLUSTERS[0]) == 50.0
    assert score_cluster(CLUSTERS[1]) == 32.0
    assert score_cluster(CLUSTERS[2]) == 10.0
    worklist = build_worklist(list(reversed(CLUSTERS)), top_n=10)
    assert [w["cluster_key"] for w in worklist] == [
        "1170x2532_pad_500_800", "1170x2532_antenna_100_900", "1170x2532_tank_50_700",
    ]
    assert [w["rank"] for w in worklist] == [1, 2, 3]
    assert "12 distinct aircraft co-occur" in worklist[0]["rationale"]
    assert build_worklist(CLUSTERS, top_n=2)[1]["cluster_key"] == (
        "1170x2532_antenna_100_900"
    )


def test_worklist_script_end_to_end(tmp_path):
    clusters_csv = tmp_path / "clusters.csv"
    with clusters_csv.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(CLUSTERS[0]))
        writer.writeheader()
        for row in CLUSTERS:
            writer.writerow(row)
    out_csv = tmp_path / "worklist.csv"
    proc = _run([sys.executable, str(SCRIPTS / "rlsm_review_worklist.py"),
                 "--clusters", str(clusters_csv), "--out", str(out_csv), "--top-n", "2"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "satim_harvest_review_labels.py" in proc.stdout  # SATIM follow-through
    rows = list(csv.DictReader(out_csv.open()))
    assert len(rows) == 2
    assert rows[0]["cluster_key"] == "1170x2532_pad_500_800"
    assert rows[0]["review_score"] == "50.0"


def test_worklist_script_fails_closed_without_input(tmp_path):
    proc = _run([sys.executable, str(SCRIPTS / "rlsm_review_worklist.py"),
                 "--clusters", str(tmp_path / "nope.csv"),
                 "--out", str(tmp_path / "out.csv")])
    assert proc.returncode == 1
    assert "not found" in proc.stdout


# ──────────────────────────────────────────────────────────────────────────
# strategy #6 — harvest-target suggester
# ──────────────────────────────────────────────────────────────────────────

def _waves_csv(path: Path, rows: list[dict]) -> Path:
    fields = ["wave_id", "wave_aircraft_identity", "wave_obs_count",
              "wave_earliest_iso", "wave_latest_iso"]
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


WAVES = [
    {"wave_id": "wave_000001", "wave_aircraft_identity": "N123AB",
     "wave_obs_count": "5", "wave_earliest_iso": "2026-03-24T09:40:00",
     "wave_latest_iso": "2026-03-24T10:10:00"},
    {"wave_id": "wave_000002", "wave_aircraft_identity": "N55XY",
     "wave_obs_count": "2", "wave_earliest_iso": "2026-04-01T09:00:00",
     "wave_latest_iso": "2026-04-01T09:20:00"},
    # single-frame wave: not enough backing
    {"wave_id": "wave_000003", "wave_aircraft_identity": "N77QQ",
     "wave_obs_count": "1", "wave_earliest_iso": "", "wave_latest_iso": ""},
    # identity is an image name, not a registration: ignored
    {"wave_id": "wave_000004", "wave_aircraft_identity": "2026-03-24 09-40-01.HEIC",
     "wave_obs_count": "9", "wave_earliest_iso": "", "wave_latest_iso": ""},
]


def test_load_wave_index_filters_to_registration_backed_waves(tmp_path):
    index = load_wave_index(_waves_csv(tmp_path / "waves.csv", WAVES))
    assert set(index) == {"N123AB", "N55XY"}
    assert index["N123AB"]["obs_count"] == 5


def test_rank_queue_bands_and_expiring_priority_tail(tmp_path):
    index = load_wave_index(_waves_csv(tmp_path / "waves.csv", WAVES))
    # N407PR is a PRIORITY_TAIL; date chosen so it expires from the Gold
    # window tomorrow (365-day window, bump band 0..2 days).
    expiring = (datetime.date.today() - datetime.timedelta(days=364)).isoformat()
    queue = [
        {"date": "2025-11-01", "tail": "N77QQ", "flight_id": "aaaa111"},   # no wave
        {"date": "2025-12-01", "tail": "N55XY", "flight_id": "bbbb222"},   # wave x2
        {"date": "2025-12-15", "tail": "N123AB", "flight_id": "cccc333"},  # wave x5
        {"date": expiring, "tail": "N407PR", "flight_id": "dddd444"},      # expiring
    ]
    ranked = rank_queue(queue, index)
    assert [e["flight_id"] for e in ranked] == [
        "dddd444",  # band 0: expiring priority tail first
        "cccc333",  # band 1: strongest wave backing
        "bbbb222",
        "aaaa111",  # band 2: wave-less keeps oldest-first
    ]
    assert "expiring from Gold window" in ranked[0]["suggest_reason"]
    assert "5 obs" in ranked[1]["suggest_reason"]
    assert ranked[3]["wave_obs_count"] == 0


def test_priority_tail_outside_expiry_window_is_not_bumped(tmp_path):
    index = load_wave_index(_waves_csv(tmp_path / "waves.csv", WAVES))
    recent = (datetime.date.today() - datetime.timedelta(days=100)).isoformat()
    queue = [
        {"date": "2025-12-15", "tail": "N123AB", "flight_id": "cccc333"},
        {"date": recent, "tail": "N407PR", "flight_id": "dddd444"},
    ]
    ranked = rank_queue(queue, index)
    assert ranked[0]["flight_id"] == "cccc333"  # wave-backed beats non-expiring priority


def test_suggester_script_emits_carryover_compatible_csv(tmp_path):
    waves = _waves_csv(tmp_path / "waves.csv", WAVES)
    carryover = tmp_path / "_harvest_carryover_20260701.csv"
    with carryover.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["date", "tail", "flight_id"])
        writer.writeheader()
        writer.writerow({"date": "2025-12-15", "tail": "N123AB", "flight_id": "cccc333"})
        writer.writerow({"date": "2025-11-01", "tail": "N77QQ", "flight_id": "aaaa111"})
    out = tmp_path / "suggestions.csv"
    proc = _run([sys.executable, str(SCRIPTS / "suggest_harvest_targets.py"),
                 "--waves", str(waves), "--carryover", str(carryover),
                 "--out", str(out)])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    summary = json.loads(proc.stdout.split("\nToday's quota")[0])
    assert summary["queue_entries"] == 2 and summary["wave_backed"] == 1

    rows = list(csv.DictReader(out.open()))
    # carryover shape preserved: load_queue() reads exactly these keys
    for row in rows:
        assert {"date", "tail", "flight_id"} <= set(row)
    assert rows[0]["flight_id"] == "cccc333"  # wave-backed first
    assert "Today's quota" in proc.stdout
