"""Tests for analyze.py CLI logic (_collect_images and run)."""

import csv
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from flight_analyzer.analyze import _collect_images, _load_already_processed, run
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
# Helpers
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
    'heading_deg': '090',
    'utc_time': '14:30',
    'squawk': '2000',
    'operator': 'Delta',
    'ocr_raw_text': 'DL500 B738 N12345 KATL KJFK FL350 460kts',
}

_FAKE_CLASS_COMMERCIAL = {
    'purpose_label': 'commercial_airline',
    'confidence': 0.97,
    'route_shape': 'straight_cruise',
    'reasoning': 'Delta scheduled service.',
}

_FAKE_CLASS_SURVEILLANCE = {
    'purpose_label': 'surveillance_recon',
    'confidence': 0.88,
    'route_shape': 'orbit_loiter',
    'reasoning': 'ISR aircraft orbiting.',
}

_FAKE_CLASS_MILITARY = {
    'purpose_label': 'military_law_enforcement',
    'confidence': 0.82,
    'route_shape': 'straight_cruise',
    'reasoning': 'Military transport.',
}

_FAKE_CLASS_SAR = {
    'purpose_label': 'search_rescue',
    'confidence': 0.90,
    'route_shape': 'sweep_pattern',
    'reasoning': 'Coast Guard SAR sweep.',
}


# ---------------------------------------------------------------------------
# run() core tests
# ---------------------------------------------------------------------------

class TestRun:
    def _run_with_mocks(self, tmp_path, images,
                        classification=None, extra_args=None):
        for name in images:
            _make_screenshot(tmp_path / name)

        out_csv = tmp_path / 'out.csv'
        argv = ['--input', str(tmp_path), '--output', str(out_csv),
                '--openai-key', 'fake-key'] + (extra_args or [])

        cls = classification or _FAKE_CLASS_COMMERCIAL
        with patch('flight_analyzer.analyze.extract_text', return_value=_FAKE_OCR), \
             patch('flight_analyzer.analyze.classify_flight', return_value=cls):
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
        assert rows[0]['heading_deg'] == '090'
        assert rows[0]['utc_time'] == '14:30'

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
             patch('flight_analyzer.analyze.classify_flight',
                   return_value=_FAKE_CLASS_COMMERCIAL):
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

    def test_api_failure_falls_back_to_rule_classifier(self, tmp_path):
        """When GPT-4o raises RuntimeError, fallback classifier is used (no error row)."""
        _make_screenshot(tmp_path / 'flight.png')
        out_csv = tmp_path / 'out.csv'

        with patch('flight_analyzer.analyze.extract_text', return_value=_FAKE_OCR), \
             patch('flight_analyzer.analyze.classify_flight',
                   side_effect=RuntimeError('API down')):
            code = run(['--input', str(tmp_path), '--output', str(out_csv),
                        '--openai-key', 'fake-key'])

        with open(out_csv, newline='') as f:
            rows = list(csv.DictReader(f))

        assert len(rows) == 1
        assert rows[0]['purpose_label'] != 'error'
        assert '[fallback]' in rows[0]['reasoning']
        assert code == 0


# ---------------------------------------------------------------------------
# --flagged-only (item 1)
# ---------------------------------------------------------------------------

class TestFlaggedOnly:
    def _run_mixed(self, tmp_path):
        """3 images: commercial, surveillance, SAR. Returns (out_csv, flagged_csv)."""
        for name in ['commercial.png', 'surveillance.png', 'sar.png']:
            _make_screenshot(tmp_path / name)

        out_csv = tmp_path / 'out.csv'

        classifications = {
            'commercial.png': _FAKE_CLASS_COMMERCIAL,
            'surveillance.png': _FAKE_CLASS_SURVEILLANCE,
            'sar.png': _FAKE_CLASS_SAR,
        }

        def classify_side_effect(img_path, ocr_fields, api_key):
            return classifications[Path(img_path).name]

        with patch('flight_analyzer.analyze.extract_text', return_value=_FAKE_OCR), \
             patch('flight_analyzer.analyze.classify_flight',
                   side_effect=classify_side_effect):
            run(['--input', str(tmp_path), '--output', str(out_csv),
                 '--openai-key', 'fake-key', '--flagged-only'])

        p = Path(str(out_csv))
        flagged_csv = p.with_name(p.stem + '.flagged' + p.suffix)
        return out_csv, flagged_csv

    def test_main_csv_has_all_rows(self, tmp_path):
        out_csv, _ = self._run_mixed(tmp_path)
        with open(out_csv, newline='') as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 3

    def test_flagged_csv_created(self, tmp_path):
        _, flagged_csv = self._run_mixed(tmp_path)
        assert flagged_csv.exists()

    def test_flagged_csv_only_has_surveillance_and_sar(self, tmp_path):
        _, flagged_csv = self._run_mixed(tmp_path)
        with open(flagged_csv, newline='') as f:
            rows = list(csv.DictReader(f))
        labels = {r['purpose_label'] for r in rows}
        assert 'commercial_airline' not in labels
        assert 'surveillance_recon' in labels
        assert 'search_rescue' in labels

    def test_flagged_csv_correct_count(self, tmp_path):
        _, flagged_csv = self._run_mixed(tmp_path)
        with open(flagged_csv, newline='') as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 2

    def test_no_flagged_csv_without_flag(self, tmp_path):
        _make_screenshot(tmp_path / 'shot.png')
        out_csv = tmp_path / 'out.csv'
        p = Path(str(out_csv))
        flagged_csv = p.with_name(p.stem + '.flagged' + p.suffix)

        with patch('flight_analyzer.analyze.extract_text', return_value=_FAKE_OCR), \
             patch('flight_analyzer.analyze.classify_flight',
                   return_value=_FAKE_CLASS_SURVEILLANCE):
            run(['--input', str(tmp_path), '--output', str(out_csv),
                 '--openai-key', 'fake-key'])

        assert not flagged_csv.exists()


# ---------------------------------------------------------------------------
# --resume (item 5)
# ---------------------------------------------------------------------------

class TestResume:
    def test_skips_already_processed(self, tmp_path):
        for name in ['a.png', 'b.png', 'c.png']:
            _make_screenshot(tmp_path / name)

        out_csv = tmp_path / 'out.csv'

        # First run: process all 3
        with patch('flight_analyzer.analyze.extract_text', return_value=_FAKE_OCR), \
             patch('flight_analyzer.analyze.classify_flight',
                   return_value=_FAKE_CLASS_COMMERCIAL):
            run(['--input', str(tmp_path), '--output', str(out_csv),
                 '--openai-key', 'fake-key'])

        # Add a new image
        _make_screenshot(tmp_path / 'd.png')

        call_count = []

        def counting_ocr(path):
            call_count.append(Path(path).name)
            return _FAKE_OCR

        # Second run with --resume: should only process d.png
        with patch('flight_analyzer.analyze.extract_text',
                   side_effect=counting_ocr), \
             patch('flight_analyzer.analyze.classify_flight',
                   return_value=_FAKE_CLASS_COMMERCIAL):
            run(['--input', str(tmp_path), '--output', str(out_csv),
                 '--openai-key', 'fake-key', '--resume'])

        assert call_count == ['d.png']

    def test_load_already_processed_empty_file(self, tmp_path):
        assert _load_already_processed(str(tmp_path / 'missing.csv')) == set()

    def test_load_already_processed_reads_filenames(self, tmp_path):
        out_csv = tmp_path / 'out.csv'
        with patch('flight_analyzer.analyze.extract_text', return_value=_FAKE_OCR), \
             patch('flight_analyzer.analyze.classify_flight',
                   return_value=_FAKE_CLASS_COMMERCIAL):
            _make_screenshot(tmp_path / 'x.png')
            run(['--input', str(tmp_path), '--output', str(out_csv),
                 '--openai-key', 'fake-key'])

        result = _load_already_processed(str(out_csv))
        assert 'x.png' in result


# ---------------------------------------------------------------------------
# --dry-run (item 7)
# ---------------------------------------------------------------------------

class TestDryRun:
    def test_dry_run_skips_api(self, tmp_path):
        _make_screenshot(tmp_path / 'shot.png')
        out_csv = tmp_path / 'out.csv'

        mock_classify = MagicMock()
        with patch('flight_analyzer.analyze.extract_text', return_value=_FAKE_OCR), \
             patch('flight_analyzer.analyze.classify_flight', mock_classify):
            run(['--input', str(tmp_path), '--output', str(out_csv),
                 '--openai-key', 'fake-key', '--dry-run'])

        mock_classify.assert_not_called()

    def test_dry_run_writes_ocr_fields(self, tmp_path):
        _make_screenshot(tmp_path / 'shot.png')
        out_csv = tmp_path / 'out.csv'

        with patch('flight_analyzer.analyze.extract_text', return_value=_FAKE_OCR), \
             patch('flight_analyzer.analyze.classify_flight', MagicMock()):
            run(['--input', str(tmp_path), '--output', str(out_csv),
                 '--openai-key', 'fake-key', '--dry-run'])

        with open(out_csv, newline='') as f:
            rows = list(csv.DictReader(f))

        assert rows[0]['flight_number'] == 'DL500'
        assert rows[0]['aircraft_type'] == 'B738'

    def test_dry_run_no_api_key_required(self, tmp_path):
        """--dry-run should work without an API key."""
        import os
        _make_screenshot(tmp_path / 'shot.png')
        out_csv = tmp_path / 'out.csv'
        env_backup = os.environ.pop('OPENAI_API_KEY', None)
        try:
            with patch('flight_analyzer.analyze.extract_text', return_value=_FAKE_OCR):
                code = run(['--input', str(tmp_path), '--output', str(out_csv),
                            '--dry-run'])
        finally:
            if env_backup is not None:
                os.environ['OPENAI_API_KEY'] = env_backup
        assert code == 0


# ---------------------------------------------------------------------------
# --workers (item 4 — concurrency)
# ---------------------------------------------------------------------------

class TestWorkers:
    def test_workers_produces_same_count_as_sequential(self, tmp_path):
        for name in ['a.png', 'b.png', 'c.png']:
            _make_screenshot(tmp_path / name)

        out_csv = tmp_path / 'out.csv'
        with patch('flight_analyzer.analyze.extract_text', return_value=_FAKE_OCR), \
             patch('flight_analyzer.analyze.classify_flight',
                   return_value=_FAKE_CLASS_COMMERCIAL):
            run(['--input', str(tmp_path), '--output', str(out_csv),
                 '--openai-key', 'fake-key', '--workers', '2'])

        with open(out_csv, newline='') as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 3

    def test_workers_correct_columns(self, tmp_path):
        _make_screenshot(tmp_path / 'shot.png')
        out_csv = tmp_path / 'out.csv'
        with patch('flight_analyzer.analyze.extract_text', return_value=_FAKE_OCR), \
             patch('flight_analyzer.analyze.classify_flight',
                   return_value=_FAKE_CLASS_COMMERCIAL):
            run(['--input', str(tmp_path), '--output', str(out_csv),
                 '--openai-key', 'fake-key', '--workers', '2'])

        with open(out_csv, newline='') as f:
            assert csv.DictReader(f).fieldnames == CSV_COLUMNS


# ---------------------------------------------------------------------------
# EasyOCR first-run warning (item 1)
# ---------------------------------------------------------------------------

class TestEasyOCRWarning:
    def test_warning_printed_when_cache_missing(self, tmp_path, capsys):
        _make_screenshot(tmp_path / 'shot.png')
        out_csv = tmp_path / 'out.csv'

        with patch('flight_analyzer.analyze._EASYOCR_CACHE') as mock_cache, \
             patch('flight_analyzer.analyze.extract_text', return_value=_FAKE_OCR), \
             patch('flight_analyzer.analyze.classify_flight',
                   return_value=_FAKE_CLASS_COMMERCIAL):
            mock_cache.exists.return_value = False
            run(['--input', str(tmp_path), '--output', str(out_csv),
                 '--openai-key', 'fake-key'])

        captured = capsys.readouterr()
        assert '1.5 GB' in captured.out

    def test_no_warning_when_cache_present(self, tmp_path, capsys):
        _make_screenshot(tmp_path / 'shot.png')
        out_csv = tmp_path / 'out.csv'

        with patch('flight_analyzer.analyze._EASYOCR_CACHE') as mock_cache, \
             patch('flight_analyzer.analyze.extract_text', return_value=_FAKE_OCR), \
             patch('flight_analyzer.analyze.classify_flight',
                   return_value=_FAKE_CLASS_COMMERCIAL):
            mock_cache.exists.return_value = True
            run(['--input', str(tmp_path), '--output', str(out_csv),
                 '--openai-key', 'fake-key'])

        captured = capsys.readouterr()
        assert '1.5 GB' not in captured.out
