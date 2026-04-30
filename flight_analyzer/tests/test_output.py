"""Tests for output.py CSV writing utilities."""

import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from flight_analyzer.output import CSV_COLUMNS, build_row, open_csv, write_error_row


_SAMPLE_OCR = {
    'flight_number': 'AA1234',
    'registration': 'N12345',
    'aircraft_type': 'B738',
    'callsign': '',
    'origin': 'KJFK',
    'destination': 'KLAX',
    'altitude_ft': 'FL350',
    'speed_kts': '450',
    'squawk': '2000',
    'operator': 'American Airlines',
    'ocr_raw_text': 'AA1234 B738 N12345 KJFK KLAX FL350 450kts 2000',
}

_SAMPLE_CLASS = {
    'purpose_label': 'commercial_airline',
    'confidence': 0.95,
    'route_shape': 'straight_cruise',
    'reasoning': 'Scheduled airline.',
}


class TestBuildRow:
    def test_filename_present(self):
        row = build_row('shot.png', _SAMPLE_OCR, _SAMPLE_CLASS)
        assert row['filename'] == 'shot.png'

    def test_ocr_fields_merged(self):
        row = build_row('shot.png', _SAMPLE_OCR, _SAMPLE_CLASS)
        assert row['flight_number'] == 'AA1234'
        assert row['aircraft_type'] == 'B738'
        assert row['origin'] == 'KJFK'

    def test_classification_merged(self):
        row = build_row('shot.png', _SAMPLE_OCR, _SAMPLE_CLASS)
        assert row['purpose_label'] == 'commercial_airline'
        assert row['confidence'] == 0.95
        assert row['route_shape'] == 'straight_cruise'

    def test_all_csv_columns_present(self):
        row = build_row('shot.png', _SAMPLE_OCR, _SAMPLE_CLASS)
        for col in CSV_COLUMNS:
            assert col in row

    def test_missing_fields_default_empty(self):
        row = build_row('shot.png', {}, {})
        for col in CSV_COLUMNS:
            assert col in row
            assert row[col] == '' or row[col] is None or col == 'filename'


class TestOpenCsv:
    def test_creates_file_with_header(self, tmp_path):
        out = tmp_path / 'results.csv'
        fh, writer = open_csv(str(out))
        fh.close()

        assert out.exists()
        with open(out, newline='') as f:
            reader = csv.DictReader(f)
            assert reader.fieldnames == CSV_COLUMNS

    def test_write_row_roundtrip(self, tmp_path):
        out = tmp_path / 'results.csv'
        fh, writer = open_csv(str(out))
        row = build_row('img.png', _SAMPLE_OCR, _SAMPLE_CLASS)
        writer.writerow(row)
        fh.close()

        with open(out, newline='') as f:
            rows = list(csv.DictReader(f))

        assert len(rows) == 1
        assert rows[0]['filename'] == 'img.png'
        assert rows[0]['purpose_label'] == 'commercial_airline'
        assert rows[0]['aircraft_type'] == 'B738'


class TestWriteErrorRow:
    def test_error_row_written(self, tmp_path):
        out = tmp_path / 'results.csv'
        fh, writer = open_csv(str(out))
        write_error_row(writer, 'bad.png', 'OCR failed: timeout')
        fh.close()

        with open(out, newline='') as f:
            rows = list(csv.DictReader(f))

        assert len(rows) == 1
        assert rows[0]['filename'] == 'bad.png'
        assert rows[0]['purpose_label'] == 'error'
        assert 'timeout' in rows[0]['reasoning']

    def test_error_row_has_all_columns(self, tmp_path):
        out = tmp_path / 'results.csv'
        fh, writer = open_csv(str(out))
        write_error_row(writer, 'bad.png', 'some error')
        fh.close()

        with open(out, newline='') as f:
            rows = list(csv.DictReader(f))

        for col in CSV_COLUMNS:
            assert col in rows[0]
