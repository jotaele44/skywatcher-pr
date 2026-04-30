"""
Rule-based fallback classifier for when the GPT-4o API is unavailable.

Uses OCR-extracted fields only (no image, no external API call).
Lower accuracy than the vision model but useful for:
  - --dry-run audits of OCR quality
  - offline operation / API outage recovery
  - quick triage of large batches before full classification

Returns the same schema as classifier.classify_flight():
  {purpose_label, confidence, route_shape, reasoning}
"""

from .ocr_extractor import (
    _CARGO_OPERATORS,
    _COMMERCIAL_TYPES,
    _GA_TYPES,
    _MEDEVAC_CALLSIGN_PREFIXES,
    _MILITARY_TRANSPORT_TYPES,
    _SAR_CALLSIGN_PREFIXES,
    _SQUAWK_EMERGENCY,
    _SQUAWK_MILITARY_IFR,
    _SQUAWK_USCG,
    _SURVEILLANCE_TYPES,
)

# Puerto Rico / Caribbean-specific callsign prefixes for law enforcement
_PR_LE_PREFIXES = ('OMAHA', 'DOMAIN', 'SENTRY', 'COQUI', 'PRESTO')
_MILITARY_CALLSIGN_PREFIXES = (
    'REACH', 'JAKE', 'NIGHT', 'BRONCO', 'IRON', 'HAVOC', 'SWIFT',
    'STEEL', 'COPPER', 'TUSK', 'BISON', 'ATLAS', 'BOXER', 'MAGIC', 'EAGLE',
) + _PR_LE_PREFIXES


def _starts_with_any(value: str, prefixes: tuple) -> bool:
    v = value.upper()
    return any(v.startswith(p) for p in prefixes)


def classify_fallback(ocr_fields: dict) -> dict:
    """
    Classify a flight using only OCR-extracted fields.

    Returns dict with keys: purpose_label, confidence, route_shape, reasoning.
    confidence is capped at 0.65 to reflect the lower accuracy of rule-based
    classification vs. the vision model.
    """
    callsign = ocr_fields.get('callsign', '').upper()
    aircraft = ocr_fields.get('aircraft_type', '').upper()
    squawk = ocr_fields.get('squawk', '').strip()
    operator = ocr_fields.get('operator', '').upper()
    flight_num = ocr_fields.get('flight_number', '').upper()

    # --- Hard rules (confidence 0.65) ---

    # 1. Medical / medevac
    if _starts_with_any(callsign, _MEDEVAC_CALLSIGN_PREFIXES):
        return _result('medical_medevac', 0.65,
                       f'Callsign {callsign!r} matches medevac prefix.')

    # 2. Search and rescue
    if _starts_with_any(callsign, _SAR_CALLSIGN_PREFIXES):
        return _result('search_rescue', 0.65,
                       f'Callsign {callsign!r} matches SAR prefix.')

    # 3. USCG squawk range → SAR / military law enforcement
    if squawk in _SQUAWK_USCG:
        return _result('search_rescue', 0.60,
                       f'Squawk {squawk} is in USCG-assigned range (4400–4477).')

    # 4. Military IFR squawk
    if squawk in _SQUAWK_MILITARY_IFR:
        return _result('military_law_enforcement', 0.60,
                       f'Squawk {squawk} indicates military IFR operation.')

    # 5. Emergency squawk — flag as military / law enforcement for review
    if squawk in _SQUAWK_EMERGENCY:
        return _result('military_law_enforcement', 0.40,
                       f'Emergency squawk {squawk} — manual review recommended.')

    # 6. Known military callsign prefix
    if _starts_with_any(callsign, _MILITARY_CALLSIGN_PREFIXES):
        return _result('military_law_enforcement', 0.60,
                       f'Callsign {callsign!r} matches military/LE prefix.')

    # 7. ISR / surveillance aircraft type
    if aircraft in {c.upper() for c in _SURVEILLANCE_TYPES}:
        return _result('surveillance_recon', 0.60,
                       f'Aircraft type {aircraft!r} is a known ISR platform.')

    # 8. Military transport type
    if aircraft in {c.upper() for c in _MILITARY_TRANSPORT_TYPES}:
        return _result('military_law_enforcement', 0.55,
                       f'Aircraft type {aircraft!r} is a known military transport.')

    # 9. Cargo operator
    if any(op in operator for op in _CARGO_OPERATORS) or any(
            op in flight_num[:3] for op in {'FDX', 'UPS', 'ABX', 'GTI', 'KMX'}):
        return _result('cargo_freight', 0.60,
                       f'Operator {operator!r} or flight number matches cargo carrier.')

    # 10. Known GA type
    if aircraft in {c.upper() for c in _GA_TYPES}:
        return _result('private_ga', 0.50,
                       f'Aircraft type {aircraft!r} is a general aviation type.')

    # 11. Known commercial type
    if aircraft in {c.upper() for c in _COMMERCIAL_TYPES}:
        return _result('commercial_airline', 0.55,
                       f'Aircraft type {aircraft!r} is a commercial airliner.')

    # 12. Flight number present → likely commercial
    if flight_num and len(flight_num) >= 4:
        return _result('commercial_airline', 0.40,
                       f'Flight number {flight_num!r} suggests scheduled service.')

    # Default — insufficient signal
    return _result('private_ga', 0.20,
                   'Insufficient OCR data for confident classification.')


def _result(label: str, conf: float, reasoning: str) -> dict:
    return {
        'purpose_label': label,
        'confidence': conf,
        'route_shape': 'unknown',
        'reasoning': f'[fallback] {reasoning}',
    }
