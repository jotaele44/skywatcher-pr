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


from scripts.extract_satim_l3_panel_fields import parse_panel_text


def test_parse_panel_text_extracts_route_location_aircraft_and_timeline():
    text = """
    N407PR
    Bell 407
    From SIG SAN JUAN
    To NRR CEIBA
    Near Lamboglia, Patillas
    Timeline 2025-10-23 09:55:25
    """

    rec = parse_panel_text(text, image_path="sample.png")

    assert rec["image_path"] == "sample.png"
    assert rec["aircraft_type"] == "Bell 407"
    assert rec["origin_code"] == "SIG"
    assert rec["destination_code"] == "NRR"
    assert rec["nearest_location"] == "Lamboglia, Patillas"
    assert rec["timeline_present"] == "true"
    assert rec["ocr_timeline_timestamp"] == "2025-10-23T09:55:25"


def test_build_l3_predictions_uses_panel_fields_over_registry(tmp_path):
    baseline = tmp_path / "data" / "FR24_baseline" / "2025-10"
    baseline.mkdir(parents=True)
    image = baseline / "2025-10-23T09-55-25_87fec1d1.png"
    image.write_bytes(b"placeholder")

    records = build_records(
        ocr_events=[{
            "tail": "N407PR",
            "alt_ft": "879",
            "speed_mph": "155",
            "best_confidence": "0.94",
            "sample_image": image.name,
        }],
        registry_rows=[],
        baseline_root=tmp_path / "data" / "FR24_baseline",
        panel_rows=[{
            "image_path": str(image),
            "aircraft_type": "Bell 407",
            "origin_code": "SIG",
            "destination_code": "NRR",
            "nearest_location": "Lamboglia, Patillas",
            "timeline_present": "true",
            "ocr_timeline_timestamp": "2025-10-23T09:55:25",
        }],
    )

    rec = records[0]
    assert rec["aircraft_type"] == "Bell 407"
    assert rec["aircraft_type_source"] == "panel_ocr"
    assert rec["origin_code"] == "SIG"
    assert rec["destination_code"] == "NRR"
    assert rec["nearest_location"] == "Lamboglia, Patillas"
    assert rec["timeline_present"] is True
    assert rec["timestamp_source"] == "fr24_timeline_ocr"
    assert rec["event_timestamp"] == "2025-10-23T09:55:25"


def test_parse_panel_text_strips_aircraft_registration_suffix():
    rec = parse_panel_text("Bell 429 GlobalRanger REG", image_path="sample.png")
    assert rec["aircraft_type"] == "Bell 429 GlobalRanger"


def test_parse_panel_text_extracts_fr24_baro_route_table():
    rec = parse_panel_text("""
    N413LP (AS50
    PSE > SIG BAROMETRIC ALT.
    PONCE SAN JUAN 1,200 ft
    Airbus Helicopters H125 REG. N413LP
    """)
    assert rec["origin_code"] == "PSE"
    assert rec["destination_code"] == "SIG"


def test_parse_panel_text_extracts_fr24_arrow_route_table():
    rec = parse_panel_text("""
    N407PR (B407
    SIG »- NRR BAROMETRIC ALT.
    SAN JUAN CEIBA 879 ft
    """)
    assert rec["aircraft_type"] == "Bell 407"
    assert rec["origin_code"] == "SIG"
    assert rec["destination_code"] == "NRR"


def test_parse_panel_text_prefers_route_tokens_nearest_baro_line():
    rec = parse_panel_text("N407PR (B407 SIG NRR BAROMETRIC ALT.")
    assert rec["aircraft_type"] == "Bell 407"
    assert rec["origin_code"] == "SIG"
    assert rec["destination_code"] == "NRR"


def test_parse_panel_text_extracts_origin_when_destination_not_available():
    rec = parse_panel_text("""
    N684JB (Ec30
    SBH N/A BAROMETRIC ALT.
    ST. JEAN NOT AVAILABLE 300 ft
    Airbus Helicopters H130 REG. N684JB
    """)
    assert rec["aircraft_type"] == "Airbus Helicopters H130"
    assert rec["origin_code"] == "SBH"
    assert rec["destination_code"] == ""


def test_parse_panel_text_extracts_fr24_utc_timestamp_line():
    rec = parse_panel_text("Tue, Oct 14, 2025 | 12:51 PM uTC -04:00")
    assert rec["timeline_present"] == "true"
    assert rec["ocr_timeline_timestamp"] == "2025-10-14T12:51:00-04:00"


def test_parse_panel_text_ignores_invalid_fr24_utc_month():
    rec = parse_panel_text("Tue, Ocr 14, 2025 | 12:51 PM UTC -04:00")
    assert rec["timeline_present"] == "true"
    assert rec["ocr_timeline_timestamp"] == ""
