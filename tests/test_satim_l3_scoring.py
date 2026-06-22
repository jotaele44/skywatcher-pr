import csv
import json

from fr24.calibration.l3_ocr_scoring import calibrate, compare_field, score_records


def test_l3_compare_integer_altitude():
    truth = {"altitude_ft": "1200"}
    pred = {"altitude_ft": "1,200"}
    assert compare_field("altitude_ft", truth, pred) is True


def test_l3_score_records_exact_match():
    truth_rows = [{
        "image_path": "sample.png",
        "callsign": "TEST1",
        "aircraft_type": "TYPE1",
        "altitude_ft": "1200",
        "origin_code": "AAA",
        "destination_code": "BBB",
        "nearest_location": "MOCA",
    }]
    predictions = {"sample.png": dict(truth_rows[0])}
    metrics = score_records(truth_rows, predictions)
    assert metrics["record_count"] == 1
    assert metrics["scored_value_count"] == 6
    assert metrics["field_scores"]["callsign"] == 1.0


def test_l3_blank_truth_values_are_not_scored():
    truth_rows = [{
        "image_path": "sample.png",
        "callsign": "",
        "aircraft_type": "AS350",
        "altitude_ft": "",
        "origin_code": "",
        "destination_code": "",
        "nearest_location": "",
    }]
    predictions = {
        "sample.png": {
            "callsign": "N5854Z",
            "aircraft_type": "AS350",
            "altitude_ft": "150",
        }
    }

    metrics = score_records(truth_rows, predictions)

    assert metrics["record_count"] == 1
    assert metrics["scored_value_count"] == 1
    assert metrics["field_scores"]["aircraft_type"] == 1.0
    assert metrics["field_scores"]["callsign"] is None
    assert metrics["field_scores"]["altitude_ft"] is None
    assert metrics["blank_truth_skips"]["callsign"] == 1
    assert metrics["blank_truth_skips"]["altitude_ft"] == 1


def test_l3_all_blank_truth_values_mark_layer_missing(tmp_path):
    truth_path = tmp_path / "truth.csv"
    pred_path = tmp_path / "predictions.json"

    with truth_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "image_path",
            "callsign",
            "altitude_ft",
            "aircraft_type",
            "origin_code",
            "destination_code",
            "nearest_location",
        ])
        writer.writeheader()
        writer.writerow({
            "image_path": "sample.png",
            "callsign": "",
            "altitude_ft": "",
            "aircraft_type": "",
            "origin_code": "",
            "destination_code": "",
            "nearest_location": "",
        })

    pred_path.write_text(json.dumps({
        "records": [{
            "image_path": "sample.png",
            "callsign": "N5854Z",
            "altitude_ft": "150",
        }]
    }), encoding="utf-8")

    report = calibrate(str(truth_path), str(pred_path))

    assert report["status"] == "MISSING"
    assert report["metrics"]["scored_value_count"] == 0
    assert report["findings"][0]["detail"] == "no nonblank ground-truth values available for scoring"
