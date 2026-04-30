"""Tests for the rule-based fallback classifier."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from flight_analyzer.fallback_classifier import classify_fallback


def _fields(**kwargs):
    base = {
        'flight_number': '', 'registration': '', 'aircraft_type': '',
        'callsign': '', 'origin': '', 'destination': '',
        'altitude_ft': '', 'speed_kts': '', 'heading_deg': '',
        'utc_time': '', 'squawk': '', 'operator': '', 'ocr_raw_text': '',
    }
    base.update(kwargs)
    return base


class TestFallbackClassifier:
    def test_medevac_callsign(self):
        r = classify_fallback(_fields(callsign='MEDEVAC1'))
        assert r['purpose_label'] == 'medical_medevac'
        assert r['confidence'] > 0

    def test_lifeguard_callsign(self):
        r = classify_fallback(_fields(callsign='LIFEGUARD12'))
        assert r['purpose_label'] == 'medical_medevac'

    def test_rescue_callsign(self):
        r = classify_fallback(_fields(callsign='RESCUE101'))
        assert r['purpose_label'] == 'search_rescue'

    def test_uscg_squawk_range(self):
        r = classify_fallback(_fields(squawk='4400'))
        assert r['purpose_label'] == 'search_rescue'

    def test_uscg_squawk_upper_bound(self):
        r = classify_fallback(_fields(squawk='4477'))
        assert r['purpose_label'] == 'search_rescue'

    def test_military_ifr_squawk(self):
        r = classify_fallback(_fields(squawk='1000'))
        assert r['purpose_label'] == 'military_law_enforcement'

    def test_military_callsign_reach(self):
        r = classify_fallback(_fields(callsign='REACH201'))
        assert r['purpose_label'] == 'military_law_enforcement'

    def test_pr_cbp_callsign_omaha(self):
        r = classify_fallback(_fields(callsign='OMAHA05'))
        assert r['purpose_label'] == 'military_law_enforcement'

    def test_pr_ang_callsign_coqui(self):
        r = classify_fallback(_fields(callsign='COQUI01'))
        assert r['purpose_label'] == 'military_law_enforcement'

    def test_surveillance_aircraft_type(self):
        r = classify_fallback(_fields(aircraft_type='RC135'))
        assert r['purpose_label'] == 'surveillance_recon'

    def test_isr_p3_type(self):
        r = classify_fallback(_fields(aircraft_type='P3'))
        assert r['purpose_label'] == 'surveillance_recon'

    def test_military_transport_c130(self):
        r = classify_fallback(_fields(aircraft_type='C130'))
        assert r['purpose_label'] == 'military_law_enforcement'

    def test_cargo_operator(self):
        r = classify_fallback(_fields(operator='FEDEX CORPORATION'))
        assert r['purpose_label'] == 'cargo_freight'

    def test_ga_aircraft_type(self):
        r = classify_fallback(_fields(aircraft_type='C172'))
        assert r['purpose_label'] == 'private_ga'

    def test_commercial_type(self):
        r = classify_fallback(_fields(aircraft_type='B738'))
        assert r['purpose_label'] == 'commercial_airline'

    def test_flight_number_implies_commercial(self):
        r = classify_fallback(_fields(flight_number='AA1234'))
        assert r['purpose_label'] == 'commercial_airline'

    def test_empty_fields_returns_result(self):
        r = classify_fallback(_fields())
        assert 'purpose_label' in r
        assert 'confidence' in r
        assert 'route_shape' in r
        assert 'reasoning' in r

    def test_confidence_capped_at_0_65(self):
        r = classify_fallback(_fields(callsign='MEDEVAC1'))
        assert r['confidence'] <= 0.65

    def test_reasoning_has_fallback_marker(self):
        r = classify_fallback(_fields(callsign='RESCUE1'))
        assert '[fallback]' in r['reasoning']

    def test_route_shape_is_unknown(self):
        r = classify_fallback(_fields(aircraft_type='B738'))
        assert r['route_shape'] == 'unknown'
