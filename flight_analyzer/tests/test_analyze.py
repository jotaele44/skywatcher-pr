"""Tests for analyze.py CLI logic (_collect_images and run)."""

import csv
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from flight_analyzer.analyze import _collect_images, run
from flight_analyzer.output import CSV_COLUMNS


# ---------------------------------------------------------------------------
# _collect_images
# ---------------------------------------------------------------------------

class TestCollectImages:
    def test_finds_png_and_jpg(self, tmp_path):
        (tmp_path / 'a.png').touch()
        (tmp_path / 'b.jpg').touch()
        (tmp_path / 'notes.txt').touch()

        images = _collect_images(str(tmp_path), recursive=False)
        names = {p.name for p in images}
        assert 'a.png' in names
        assert 'b.jpg' in names
        assert 'notes.txt' not in names

    def test_recursive_flag(self, tmp_path):
        sub = tmp_path / 'sub'
        sub.mkdir()
        (sub / 'deep.png').touch()
        (tmp_path / 'top.png').touch()

        flat = _collect_images(str(tmp_path), recursive=False)
        assert not any(p.name == 'deep.png' for p in flat)

        deep = _collect_images(str(tmp_path), recursive=True)
        assert any(p.name == 'deep.png' for p in deep)

    def test_empty_directory_returns_empty_list(self, tmp_path):
        assert _collect_images(str(tmp_path), recursive=False) == []

    def test_non_directory_raises(self, tmp_path):
        f = tmp_path / 'file.txt'
        f.touch()
        with pytest.raises(NotADirectoryError):
            _collect_images(str(f), recursive=False)


# ---------------------------------------------------------------------------
# run() end-to-end (OCR + classifier mocked)
# ---------------------------------------------------------------------------

def _make_screenshot(path: Path) -> None:
    Image.new('RGB', (800, 600), color=(20, 20, 20)).save(path)


_FAKE_OCR = {
    'flight_number': 'DL500',
    'registration': 'N12345',
    'aircraft_type': 'B738',
    'callsign': '',
    'origin': 'KATL',
    'destination': 'KJFK',
    'altitude_ft': 'FL350',
    'speed_kts': '460',
    'squawk': '2000',
    'operator': 'Delta',
    'ocr_raw_text': 'DL500 B738 N12345 KATL KJFK FL350 460kts',
}

_FAKE_CLASSIFICATION = {
    'purpose_label': 'commercial_airline',
    'confidence': 0.97,
    'route_shape': 'straight_cruise',
    'reasoning': 'Delta scheduled service.',
}


class TestRun:
    def _run_with_mocks(self, tmp_path, images, extra_args=None):
        for name in images:
            _make_screenshot(tmp_path / name)

        out_csv = tmp_path / 'out.csv'
        argv = ['--input', str(tmp_path), '--output', str(out_csv),
                '--openai-key', 'fake-key'] + (extra_args or [])

        with patch('flight_analyzer.analyze.extract_text', return_value=_FAKE_OCR), \
             patch('flight_analyzer.analyze.classify_flight', return_value=_FAKE_CLASSIFICATION):
            exit_code = run(argv)

        return exit_code, out_csv

    def test_produces_csv_with_correct_columns(self, tmp_path):
        _, out_csv = self._run_with_mocks(tmp_path, ['shot.png'])
        with open(out_csv, newline='') as f:
            reader = csv.DictReader(f)
            assert reader.fieldnames == CSV_COLUMNS

    def test_one_row_per_image(self, tmp_path):
        _, out_csv = self._run_with_mocks(tmp_path, ['a.png', 'b.jpg', 'c.jpeg'])
        with open(out_csv, newline='') as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 3

    def test_row_content_correct(self, tmp_path):
        _, out_csv = self._run_with_mocks(tmp_path, ['shot.png'])
        with open(out_csv, newline='') as f:
            rows = list(csv.DictReader(f))
        assert rows[0]['purpose_label'] == 'commercial_airline'
        assert rows[0]['flight_number'] == 'DL500'

    def test_returns_zero_on_success(self, tmp_path):
        code, _ = self._run_with_mocks(tmp_path, ['shot.png'])
        assert code == 0

    def test_ocr_error_writes_error_row_and_continues(self, tmp_path):
        _make_screenshot(tmp_path / 'good.png')
        _make_screenshot(tmp_path / 'bad.png')
        out_csv = tmp_path / 'out.csv'

        def ocr_side_effect(path):
            if 'bad' in path:
                raise RuntimeError('OCR exploded')
            return _FAKE_OCR

        with patch('flight_analyzer.analyze.extract_text', side_effect=ocr_side_effect), \
             patch('flight_analyzer.analyze.classify_flight', return_value=_FAKE_CLASSIFICATION):
            code = run(['--input', str(tmp_path), '--output', str(out_csv),
                        '--openai-key', 'fake-key'])

        with open(out_csv, newline='') as f:
            rows = list(csv.DictReader(f))

        assert len(rows) == 2
        error_rows = [r for r in rows if r['purpose_label'] == 'error']
        good_rows = [r for r in rows if r['purpose_label'] == 'commercial_airline']
        assert len(error_rows) == 1
        assert len(good_rows) == 1

    def test_no_openai_key_returns_one(self, tmp_path):
        import os
        env_backup = os.environ.pop('OPENAI_API_KEY', None)
        try:
            code = run(['--input', str(tmp_path), '--output', str(tmp_path / 'out.csv')])
        finally:
            if env_backup is not None:
                os.environ['OPENAI_API_KEY'] = env_backup
        assert code == 1

    def test_empty_directory_returns_one(self, tmp_path):
        code = run(['--input', str(tmp_path), '--output', str(tmp_path / 'out.csv'),
                    '--openai-key', 'fake-key'])
        assert code == 1
