"""
OCR-based text extraction from FlightRadar24 screenshots.

Uses EasyOCR (layout-agnostic) to handle mixed web/mobile FR24 layouts.
Applies regex patterns to parse structured aviation fields from raw OCR output.
"""

import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance

_reader = None  # lazy singleton to avoid loading the model on import


def _get_reader():
    global _reader
    if _reader is None:
        import easyocr  # deferred so the module imports fast when easyocr is absent
        _reader = easyocr.Reader(['en'], gpu=False, verbose=False)
    return _reader


# ---------------------------------------------------------------------------
# Known ICAO aircraft type codes that carry strong mission-type signals
# ---------------------------------------------------------------------------
_SURVEILLANCE_TYPES = {
    'U2', 'U-2', 'TR1', 'RC135', 'RC-135', 'WC135', 'EC130', 'EC135',
    'E3', 'E3A', 'E3B', 'E3C', 'E3D', 'E8', 'E8C', 'P3', 'P3C', 'P8',
    'P8A', 'EP3', 'ES3', 'RQ4', 'RQ-4', 'MQ9', 'MQ-9', 'MQ1', 'MQ-1',
    'MC12', 'MC-12', 'DHC8', 'DHC-8', 'PC12', 'PC-12',
}

_MILITARY_TRANSPORT_TYPES = {
    'C130', 'C-130', 'C17', 'C-17', 'C5', 'C-5', 'C141', 'C-141',
    'KC135', 'KC-135', 'KC10', 'KC-10', 'KC46', 'KC-46',
    'V22', 'V-22', 'CH47', 'CH-47', 'UH60', 'UH-60',
}

_MEDEVAC_CALLSIGN_PREFIXES = ('MEDEVAC', 'MEDIVAC', 'LIFEGUARD', 'ANGEL',
                               'AEROCARE', 'AIRCARE', 'CAREFLIGHT')

_SAR_CALLSIGN_PREFIXES = ('RESCUE', 'COAST', 'SAR', 'GUARDEX', 'CGAS')

_MILITARY_CALLSIGN_PREFIXES = ('REACH', 'JAKE', 'NIGHT', 'BRONCO', 'IRON',
                                'HAVOC', 'SWIFT', 'STEEL', 'COPPER', 'TUSK',
                                'BISON', 'ATLAS', 'BOXER', 'MAGIC', 'EAGLE')

# Squawk codes with known mission meanings
_SQUAWK_MILITARY_IFR = {'1000'}
_SQUAWK_EMERGENCY = {'7500', '7600', '7700'}

# ICAO type codes for common commercial/cargo/GA aircraft
_COMMERCIAL_TYPES = {
    'B737', 'B738', 'B739', 'B73X', 'B735', 'B736',
    'B747', 'B748', 'B74F', 'B74S',
    'B757', 'B752', 'B753',
    'B767', 'B762', 'B763', 'B764',
    'B777', 'B772', 'B773', 'B77W', 'B77L',
    'B787', 'B788', 'B789', 'B78X',
    'A318', 'A319', 'A320', 'A321', 'A20N', 'A21N',
    'A330', 'A332', 'A333', 'A338', 'A339',
    'A340', 'A342', 'A343', 'A345', 'A346',
    'A350', 'A358', 'A359', 'A35K',
    'A380', 'A388',
    'E170', 'E175', 'E190', 'E195',
    'CRJ2', 'CRJ7', 'CRJ9', 'CRJX',
    'AT72', 'AT75', 'AT76',
    'DH8A', 'DH8B', 'DH8C', 'DH8D',
}

_CARGO_OPERATORS = {'FEDEX', 'FDX', 'UPS', 'UPSCO', 'DHL', 'AMAZON', 'ATLAS',
                    'SOUTHERN', 'ABX', 'KALITTA', 'POLAR', 'CARGOLUX'}

_GA_TYPES = {
    'C172', 'C182', 'C208', 'C210', 'C310', 'C337', 'C414', 'C421',
    'PA28', 'PA32', 'PA34', 'PA44', 'PA46',
    'BE36', 'BE58', 'BE60', 'BE76', 'BE90', 'BE99',
    'SR20', 'SR22', 'TBM7', 'TBM8', 'TBM9',
    'DA40', 'DA42', 'DA62',
    'M20P', 'M20T', 'M20U',
    'GLF4', 'GLF5', 'GLF6', 'C56X', 'C68A', 'C750',
    'F2TH', 'FA50', 'FA7X',
    'LJ35', 'LJ45', 'LJ60', 'LJ75',
    'CL30', 'CL35', 'CL60',
    'E50P', 'E55P', 'PC24',
}


# ---------------------------------------------------------------------------
# Field extraction helpers
# ---------------------------------------------------------------------------

def _search(pattern: str, text: str, flags: int = re.IGNORECASE) -> str:
    m = re.search(pattern, text, flags)
    return m.group(1).strip() if m else ''


def _parse_fields(raw: str) -> dict:
    """Extract structured aviation fields from concatenated OCR text."""
    fields: dict = {
        'flight_number': '',
        'registration': '',
        'aircraft_type': '',
        'callsign': '',
        'origin': '',
        'destination': '',
        'altitude_ft': '',
        'speed_kts': '',
        'squawk': '',
        'operator': '',
    }

    # Flight number: IATA (2-char prefix) or ICAO (3-char prefix)
    fn = _search(r'\b([A-Z]{2,3}\s?\d{1,4}[A-Z]?)\b', raw)
    if fn:
        fields['flight_number'] = fn.replace(' ', '')

    # Aircraft registration (covers common formats)
    reg_patterns = [
        r'\b(N\d{1,5}[A-Z]{0,2})\b',          # US: N12345, N123AB
        r'\b(G-[A-Z]{4})\b',                     # UK
        r'\b(D-[A-Z]{4})\b',                     # Germany
        r'\b(F-[A-Z]{4})\b',                     # France
        r'\b(VH-[A-Z]{3})\b',                    # Australia
        r'\b(C-[FG][A-Z]{3})\b',                 # Canada
        r'\b(OY-[A-Z]{3})\b',                    # Denmark
        r'\b(SE-[A-Z]{3})\b',                    # Sweden
        r'\b(PH-[A-Z]{3})\b',                    # Netherlands
        r'\b(I-[A-Z]{4})\b',                     # Italy
        r'\b(EC-[A-Z]{3})\b',                    # Spain
        r'\b(HB-[A-Z]{3,4})\b',                 # Switzerland
        r'\b([A-Z]{2}-[A-Z]{3,4})\b',           # generic 2-letter prefix
    ]
    for pat in reg_patterns:
        reg = _search(pat, raw)
        if reg:
            fields['registration'] = reg
            break

    # ICAO aircraft type code (2–4 uppercase letters/digits, not mistaken for ICAO airport)
    # Look for known types first, then fall back to raw match
    raw_upper = raw.upper()
    for known_set in (_SURVEILLANCE_TYPES, _MILITARY_TRANSPORT_TYPES,
                      _COMMERCIAL_TYPES, _CARGO_OPERATORS, _GA_TYPES):
        for code in known_set:
            if re.search(r'\b' + re.escape(code) + r'\b', raw_upper):
                fields['aircraft_type'] = code
                break
        if fields['aircraft_type']:
            break

    if not fields['aircraft_type']:
        ac = _search(r'\b([A-Z][A-Z0-9]{1,3})\b', raw)
        if ac and len(ac) <= 4:
            fields['aircraft_type'] = ac

    # Callsign detection (check known prefix lists)
    # Group prefixes inside (?:...) so \w* applies to the whole match, not just the last alt.
    _all_cs_prefixes = '|'.join(
        _MEDEVAC_CALLSIGN_PREFIXES + _SAR_CALLSIGN_PREFIXES + _MILITARY_CALLSIGN_PREFIXES
    )
    cs_match = re.search(
        r'\b((?:' + _all_cs_prefixes + r')\w*)\b',
        raw, re.IGNORECASE)
    if cs_match:
        fields['callsign'] = cs_match.group(1).upper()

    # ICAO airport codes: 4-letter all-caps (or 3-letter IATA)
    # Look for "from/to", arrows, or proximity patterns
    airports = re.findall(r'\b([A-Z]{3,4})\b', raw)
    # Filter to plausible airport codes (not aircraft types already found)
    airport_candidates = [a for a in airports if len(a) in (3, 4)
                          and a not in ('AGL', 'IFR', 'VFR', 'GPS')]
    if len(airport_candidates) >= 2:
        # Heuristic: first plausible pair found
        fields['origin'] = airport_candidates[0]
        fields['destination'] = airport_candidates[1]
    elif len(airport_candidates) == 1:
        fields['origin'] = airport_candidates[0]

    # Altitude: FL notation or feet
    alt = _search(r'\b(FL\s*\d{2,3})\b', raw, re.IGNORECASE)
    if not alt:
        alt = _search(r'\b(\d{2,5})\s*(?:ft|feet)\b', raw, re.IGNORECASE)
    fields['altitude_ft'] = alt

    # Speed in knots
    spd = _search(r'\b(\d{2,4})\s*(?:kt|kts|knots)\b', raw, re.IGNORECASE)
    fields['speed_kts'] = spd

    # Squawk code: 4-digit octal number near "squawk" or standalone
    sq = _search(r'squawk\D{0,5}([0-7]{4})', raw, re.IGNORECASE)
    if not sq:
        # Look for standalone 4-digit octal (common in FR24 info panels)
        sq_candidates = re.findall(r'\b([0-7]{4})\b', raw)
        if sq_candidates:
            sq = sq_candidates[0]
    fields['squawk'] = sq

    # Operator / airline name (heuristic: word before the flight number)
    if fields['flight_number']:
        op = _search(r'([A-Za-z ]{3,30})\s+' + re.escape(fields['flight_number']), raw)
        if op:
            fields['operator'] = op.strip()

    return fields


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_text(image_path: str) -> dict:
    """
    Run EasyOCR on the screenshot at *image_path* and return a dict of:
      - ocr_raw_text: full concatenated OCR output
      - flight_number, registration, aircraft_type, callsign,
        origin, destination, altitude_ft, speed_kts, squawk, operator
    """
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(f"Image not found: {image_path}")

    img = Image.open(path).convert('RGB')

    # Enhance contrast to improve OCR accuracy on varied screenshot backgrounds
    img = ImageEnhance.Contrast(img).enhance(1.5)
    img = ImageEnhance.Sharpness(img).enhance(1.3)

    img_array = np.array(img)

    reader = _get_reader()
    results = reader.readtext(img_array, detail=1, paragraph=False)

    # Filter by confidence threshold and concatenate
    texts = [text for (_bbox, text, conf) in results if conf >= 0.3]
    raw = ' '.join(texts)

    fields = _parse_fields(raw)
    fields['ocr_raw_text'] = raw
    return fields
