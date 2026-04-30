"""Tests for classifier._parse_response and classify_flight (openai mocked)."""

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from flight_analyzer.classifier import (
    PURPOSE_LABELS,
    ROUTE_SHAPES,
    _format_ocr_fields,
    _parse_response,
    classify_flight,
)


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------

class TestParseResponse:
    def _valid_json(self, label='commercial_airline', shape='straight_cruise',
                    conf=0.9, reasoning='Scheduled passenger service.'):
        import json
        return json.dumps({
            'purpose_label': label,
            'confidence': conf,
            'route_shape': shape,
            'reasoning': reasoning,
        })

    def test_valid_response(self):
        r = _parse_response(self._valid_json())
        assert r['purpose_label'] == 'commercial_airline'
        assert r['route_shape'] == 'straight_cruise'
        assert r['confidence'] == pytest.approx(0.9)
        assert 'Scheduled' in r['reasoning']

    def test_all_purpose_labels_accepted(self):
        for label in PURPOSE_LABELS:
            r = _parse_response(self._valid_json(label=label))
            assert r['purpose_label'] == label

    def test_all_route_shapes_accepted(self):
        for shape in ROUTE_SHAPES:
            r = _parse_response(self._valid_json(shape=shape))
            assert r['route_shape'] == shape

    def test_unknown_label_normalised(self):
        r = _parse_response(self._valid_json(label='alien_spacecraft'))
        assert r['purpose_label'] == 'unknown'

    def test_unknown_shape_normalised(self):
        r = _parse_response(self._valid_json(shape='barrel_roll'))
        assert r['route_shape'] == 'unknown'

    def test_confidence_clamped_above_one(self):
        r = _parse_response(self._valid_json(conf=1.5))
        assert r['confidence'] == pytest.approx(1.0)

    def test_confidence_clamped_below_zero(self):
        r = _parse_response(self._valid_json(conf=-0.3))
        assert r['confidence'] == pytest.approx(0.0)

    def test_confidence_non_numeric_defaults_zero(self):
        import json
        raw = json.dumps({'purpose_label': 'private_ga', 'confidence': 'high',
                          'route_shape': 'unknown', 'reasoning': 'test'})
        r = _parse_response(raw)
        assert r['confidence'] == pytest.approx(0.0)

    def test_strips_markdown_fences(self):
        r = _parse_response(
            '```json\n{"purpose_label":"cargo_freight","confidence":0.8,'
            '"route_shape":"straight_cruise","reasoning":"FedEx 767."}\n```'
        )
        assert r['purpose_label'] == 'cargo_freight'

    def test_garbage_input_returns_unknown(self):
        r = _parse_response('This is not JSON at all!!!')
        assert r['purpose_label'] == 'unknown'
        assert r['confidence'] == pytest.approx(0.0)

    def test_partial_json_via_regex_fallback(self):
        r = _parse_response(
            'Here is the result: {"purpose_label":"training","confidence":0.75,'
            '"route_shape":"touch_and_go","reasoning":"Circuit patterns."} done.'
        )
        assert r['purpose_label'] == 'training'


# ---------------------------------------------------------------------------
# _format_ocr_fields
# ---------------------------------------------------------------------------

class TestFormatOcrFields:
    def test_all_fields_present(self):
        fields = {
            'flight_number': 'AA1234', 'registration': 'N12345',
            'aircraft_type': 'B738', 'callsign': '', 'origin': 'KJFK',
            'destination': 'KLAX', 'altitude_ft': 'FL350', 'speed_kts': '450',
            'squawk': '2000', 'operator': 'American Airlines',
        }
        block = _format_ocr_fields(fields)
        assert 'AA1234' in block
        assert 'N12345' in block
        assert 'KJFK' in block

    def test_missing_field_shows_not_detected(self):
        block = _format_ocr_fields({})
        assert '(not detected)' in block


# ---------------------------------------------------------------------------
# classify_flight (openai fully mocked)
# ---------------------------------------------------------------------------

def _make_mock_openai(content: str):
    """Return a mock openai module whose client returns *content* as the response."""
    mock_choice = MagicMock()
    mock_choice.message.content = content

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response

    mock_openai_mod = MagicMock()
    mock_openai_mod.OpenAI.return_value = mock_client
    return mock_openai_mod, mock_client


class TestClassifyFlight:
    def _make_image(self, tmp_path: Path) -> Path:
        p = tmp_path / 'fr24.png'
        Image.new('RGB', (800, 600), color=(20, 20, 20)).save(p)
        return p

    def test_successful_classification(self, tmp_path):
        import json
        good_json = json.dumps({
            'purpose_label': 'commercial_airline',
            'confidence': 0.95,
            'route_shape': 'straight_cruise',
            'reasoning': 'Airline flight number, B738, scheduled route.',
        })
        mock_openai, _ = _make_mock_openai(good_json)
        img = self._make_image(tmp_path)

        with patch.dict('sys.modules', {'openai': mock_openai}):
            result = classify_flight(str(img), {}, api_key='test-key')

        assert result['purpose_label'] == 'commercial_airline'
        assert result['confidence'] == pytest.approx(0.95)

    def _make_mock_openai_mod(self):
        """
        Build a minimal fake openai module with real exception subclasses so that
        the except-clauses in classify_flight (which reference openai.RateLimitError
        etc. from the patched module) match raised instances correctly.
        This avoids requiring the real openai package to be installed.
        """
        class FakeOpenAIError(Exception):
            pass

        class FakeRateLimitError(FakeOpenAIError):
            pass

        class FakeAPIStatusError(FakeOpenAIError):
            def __init__(self, status_code=500):
                self.status_code = status_code

        mod = MagicMock()
        mod.OpenAIError = FakeOpenAIError
        mod.RateLimitError = FakeRateLimitError
        mod.APIStatusError = FakeAPIStatusError
        return mod, FakeRateLimitError, FakeAPIStatusError

    def test_retries_on_rate_limit_then_succeeds(self, tmp_path):
        import json
        good_json = json.dumps({
            'purpose_label': 'surveillance_recon',
            'confidence': 0.88,
            'route_shape': 'orbit_loiter',
            'reasoning': 'ISR orbit pattern.',
        })
        mock_choice = MagicMock()
        mock_choice.message.content = good_json
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_openai_mod, RateLimitError, _ = self._make_mock_openai_mod()
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [
            RateLimitError(), RateLimitError(), mock_response,
        ]
        mock_openai_mod.OpenAI.return_value = mock_client

        img = self._make_image(tmp_path)

        with patch.dict('sys.modules', {'openai': mock_openai_mod}), \
             patch('flight_analyzer.classifier.time.sleep') as mock_sleep:
            result = classify_flight(str(img), {}, api_key='test-key')

        assert result['purpose_label'] == 'surveillance_recon'
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(2)   # 2 * 2^0
        mock_sleep.assert_any_call(4)   # 2 * 2^1

    def test_raises_runtime_error_after_max_retries(self, tmp_path):
        mock_openai_mod, RateLimitError, _ = self._make_mock_openai_mod()
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = RateLimitError()
        mock_openai_mod.OpenAI.return_value = mock_client

        img = self._make_image(tmp_path)

        with patch.dict('sys.modules', {'openai': mock_openai_mod}), \
             patch('flight_analyzer.classifier.time.sleep'):
            with pytest.raises(RuntimeError, match='retries'):
                classify_flight(str(img), {}, api_key='test-key')

    def test_non_retryable_error_raises_immediately(self, tmp_path):
        mock_openai_mod, _, APIStatusError = self._make_mock_openai_mod()
        mock_client = MagicMock()
        # 400 Bad Request — should NOT retry
        mock_client.chat.completions.create.side_effect = APIStatusError(status_code=400)
        mock_openai_mod.OpenAI.return_value = mock_client

        img = self._make_image(tmp_path)

        with patch.dict('sys.modules', {'openai': mock_openai_mod}), \
             patch('flight_analyzer.classifier.time.sleep') as mock_sleep:
            with pytest.raises(RuntimeError):
                classify_flight(str(img), {}, api_key='test-key')

        mock_sleep.assert_not_called()
        assert mock_client.chat.completions.create.call_count == 1
