import csv
import json
from pathlib import Path

from scripts.build_satim_l3_predictions import build_records, read_csv


def write_csv(path: Path, rows, fieldnames):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_build_l3_predictions_adds_registry_and_timestamp_metadata(tmp_path):
    baseline = tmp_path / "data" / "FR24_baseline" / "2026-03"
    baseline.mkdir(parents=True)
    image = baseline / "2026-03-16T09-10-01_03f5e15e.png"
    image.write_bytes(b"not-an-image-but-exists")

    ocr_events = [{
        "tail": "N5854Z",
        "alt_ft": "150",
        "speed_mph": "76",
        "best_confidence": "0.94",
        "sample_image": image.name,
    }]

    registry_rows = [{
        "tail": "N5854Z",
        "make_model": "Airbus Helicopters H125",
        "aircraft_type": "Rotor",
        "owner_or_status": "Example Owner",
    }]

    records = build_records(
        ocr_events=ocr_events,
        registry_rows=registry_rows,
        baseline_root=tmp_path / "data" / "FR24_baseline",
    )

    assert len(records) == 1
    rec = records[0]
    assert rec["image_path"].endswith(image.name)
    assert rec["registration"] == "N5854Z"
    assert rec["callsign"] == "N5854Z"
    assert rec["altitude_ft"] == "150"
    assert rec["aircraft_type"] == "Airbus Helicopters H125"
    assert rec["aircraft_type_source"] == "registry_make_model"
    assert rec["timeline_present"] is False
    assert rec["timestamp_source"] == "file_creation_time"
    assert rec["event_timestamp"]


def test_read_csv_roundtrip(tmp_path):
    path = tmp_path / "rows.csv"
    write_csv(path, [{"tail": "N2JJ"}], ["tail"])
    assert read_csv(path) == [{"tail": "N2JJ"}]
