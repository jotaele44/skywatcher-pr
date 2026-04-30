"""Tests for ocr_extractor field-parsing logic.

_parse_fields() is pure regex/string logic and requires no easyocr install.
extract_text() is tested with easyocr mocked out.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PIL import Image

# Make sure the package root is on sys.path regardless of how pytest is invoked
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from flight_analyzer.ocr_extractor import _parse_fields, extract_text


# ---------------------------------------------------------------------------
# _parse_fields unit tests
# ---------------------------------------------------------------------------

class TestParseFlightNumber:
    def test_iata_two_char(self):
        f = _parse_fields('AA1234 departing KJFK')
        assert f['flight_number'] == 'AA1234'

    def test_iata_three_char(self):
        f = _parse_fields('UAL456 heading to KLAX')
        assert f['flight_number'] == 'UAL456'

    def test_no_flight_number(self):
        f = _parse_fields('N12345 C172 1500ft')
        assert f['flight_number'] == ''


class TestParseRegistration:
    def test_us_n_number(self):
        f = _parse_fields('Registration N12345 altitude 5000ft')
        assert f['registration'] == 'N12345'

    def test_uk_g_prefix(self):
        f = _parse_fields('G-ABCD B738 FL350')
        assert f['registration'] == 'G-ABCD'

    def test_australia_vh(self):
        f = _parse_fields('VH-ABC A320 350kt')
        assert f['registration'] == 'VH-ABC'

    def test_canada_c_prefix(self):
        f = _parse_fields('C-FABC DHC8 FL180')
        assert f['registration'] == 'C-FABC'

    def test_no_registration(self):
        f = _parse_fields('FL350 450kts heading east')
        assert f['registration'] == ''


class TestParseAircraftType:
    def test_commercial_b738(self):
        f = _parse_fields('B738 AA100 KJFK KLAX FL350')
        assert f['aircraft_type'] == 'B738'

    def test_ga_c172(self):
        f = _parse_fields('N12345 C172 1500ft 100kts')
        assert f['aircraft_type'] == 'C172'

    def test_surveillance_rc135(self):
        f = _parse_fields('RC135 squawk 1000 no destination')
        assert f['aircraft_type'] == 'RC135'

    def test_military_c130(self):
        f = _parse_fields('C130 REACH201 FL250')
        assert f['aircraft_type'] == 'C130'


class TestParseCallsign:
    def test_medevac(self):
        f = _parse_fields('MEDEVAC1 N12345 PC12 1500ft')
        assert f['callsign'] == 'MEDEVAC1'

    def test_rescue(self):
        f = _parse_fields('RESCUE101 MH60 500ft')
        assert f['callsign'] == 'RESCUE101'

    def test_reach_military(self):
        f = _parse_fields('REACH201 C17 FL300 500kts')
        assert f['callsign'] == 'REACH201'

    def test_no_callsign(self):
        f = _parse_fields('AA1234 B738 FL350 KJFK KLAX')
        assert f['callsign'] == ''


class TestParseAltitude:
    def test_flight_level(self):
        f = _parse_fields('FL350 450kts KJFK KLAX')
        assert 'FL' in f['altitude_ft'] and '350' in f['altitude_ft']

    def test_feet_explicit(self):
        f = _parse_fields('altitude 5000ft speed 120kts')
        assert '5000' in f['altitude_ft']

    def test_no_altitude(self):
        f = _parse_fields('N12345 C172 KJFK')
        assert f['altitude_ft'] == ''


class TestParseSpeed:
    def test_knots_abbreviation(self):
        f = _parse_fields('450kts heading west')
        assert '450' in f['speed_kts']

    def test_knots_full_word(self):
        f = _parse_fields('speed 320 knots')
        assert '320' in f['speed_kts']

    def test_no_speed(self):
        f = _parse_fields('N12345 C172 FL100')
        assert f['speed_kts'] == ''


class TestParseSquawk:
    def test_squawk_keyword(self):
        f = _parse_fields('squawk 7700 emergency')
        assert f['squawk'] == '7700'

    def test_squawk_military(self):
        f = _parse_fields('RC135 squawk 1000 no destination')
        assert f['squawk'] == '1000'

    def test_standalone_octal(self):
        f = _parse_fields('2000 FL350 450kts')
        assert f['squawk'] == '2000'


class TestParseAirports:
    def test_arrow_pattern_priority(self):
        f = _parse_fields('KJFK → KLAX FL350 450kts')
        assert f['origin'] == 'KJFK'
        assert f['destination'] == 'KLAX'

    def test_arrow_with_dash(self):
        f = _parse_fields('TJBQ - TJSJ 5000ft 180kts')
        assert f['origin'] == 'TJBQ'
        assert f['destination'] == 'TJSJ'

    def test_from_to_labels(self):
        f = _parse_fields('From: KMIA  To: TJSJ altitude 35000ft')
        assert f['origin'] == 'KMIA'
        assert f['destination'] == 'TJSJ'

    def test_aircraft_type_not_mistaken_for_airport(self):
        f = _parse_fields('B738 FL350 450kts')
        assert f['origin'] != 'B738'
        assert f['destination'] != 'B738'

    def test_fallback_two_icao_codes(self):
        f = _parse_fields('KJFK KLAX FL350 450kts')
        assert f['origin'] == 'KJFK'
        assert f['destination'] == 'KLAX'

    def test_single_airport(self):
        f = _parse_fields('EGLL FL200 350kts')
        assert f['origin'] == 'EGLL'
        assert f['destination'] == ''


class TestParseHeading:
    def test_heading_keyword(self):
        f = _parse_fields('heading 270 FL350')
        assert '270' in f['heading_deg']

    def test_hdg_abbreviation(self):
        f = _parse_fields('HDG: 090 speed 450kts')
        assert '090' in f['heading_deg']

    def test_no_heading(self):
        f = _parse_fields('FL350 450kts KJFK KLAX')
        assert f['heading_deg'] == ''


class TestParseUtcTime:
    def test_hh_mm_utc(self):
        f = _parse_fields('14:32 UTC altitude FL350')
        assert '14:32' in f['utc_time']

    def test_hh_mm_ss(self):
        f = _parse_fields('time 09:15:30 FL200')
        assert '09:15:30' in f['utc_time']

    def test_no_time(self):
        f = _parse_fields('FL350 450kts KJFK KLAX B738')
        assert f['utc_time'] == ''


# ---------------------------------------------------------------------------
# extract_text integration (easyocr mocked)
# ---------------------------------------------------------------------------

class TestExtractText:
    def _make_tmp_image(self, tmp_path: Path) -> Path:
        img_path = tmp_path / 'test.png'
        Image.new('RGB', (400, 300), color=(30, 30, 30)).save(img_path)
        return img_path

    def test_returns_expected_keys(self, tmp_path):
        img_path = self._make_tmp_image(tmp_path)

        fake_results = [
            ([[0, 0], [100, 0], [100, 20], [0, 20]], 'AA1234', 0.95),
            ([[0, 25], [100, 25], [100, 45], [0, 45]], 'B738 FL350 450kts KJFK KLAX', 0.90),
        ]

        mock_reader = MagicMock()
        mock_reader.readtext.return_value = fake_results

        with patch('flight_analyzer.ocr_extractor._reader', mock_reader):
            result = extract_text(str(img_path))

        assert 'ocr_raw_text' in result
        assert 'flight_number' in result
        assert 'registration' in result
        assert 'aircraft_type' in result
        assert result['flight_number'] == 'AA1234'
        assert result['aircraft_type'] == 'B738'

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            extract_text('/nonexistent/path/image.png')

    def test_low_confidence_results_filtered(self, tmp_path):
        img_path = self._make_tmp_image(tmp_path)

        fake_results = [
            ([[0, 0], [100, 0], [100, 20], [0, 20]], 'MEDEVAC1', 0.95),
            ([[0, 25], [100, 25], [100, 45], [0, 45]], 'NOISE_TEXT', 0.10),  # below threshold
        ]

        mock_reader = MagicMock()
        mock_reader.readtext.return_value = fake_results

        with patch('flight_analyzer.ocr_extractor._reader', mock_reader):
            result = extract_text(str(img_path))

        assert 'NOISE_TEXT' not in result['ocr_raw_text']
        assert 'MEDEVAC' in result['ocr_raw_text']
