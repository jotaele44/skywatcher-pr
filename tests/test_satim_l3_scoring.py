from fr24.calibration.l3_ocr_scoring import compare_field, score_records


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
    assert metrics["field_scores"]["callsign"] == 1.0
