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
# Known ICAO aircraft type codes — grouped by mission category
# ---------------------------------------------------------------------------

_SURVEILLANCE_TYPES = {
    # Classic ISR platforms
    'U2', 'TR1',
    'RC135', 'WC135', 'OC135',
    'EC130', 'EC135', 'EC137',
    'E3', 'E3A', 'E3B', 'E3C', 'E3D',
    'E6', 'E6B',
    'E8', 'E8C',
    'P3', 'P3C', 'EP3',
    'P8', 'P8A',
    'ES3',
    'RQ4',
    'MQ9', 'MQ1',
    'MC12',
    # Common law-enforcement ISR airframes
    'DHC8', 'DHC6',
    'PC12', 'PC6',
    'B350', 'BE20', 'BE9L', 'BE9T',   # King Air variants used for surveillance
    'C208',                             # Cessna Caravan (surveillance/ISR config)
    'C12',  'RC12',                     # C-12 Huron, RC-12 Guardrail
    'UC35',                             # Citation Encore military utility
    'LJ60',                             # Learjet 60 ISR
}

_MILITARY_TRANSPORT_TYPES = {
    'C130', 'C17', 'C5', 'C141', 'C2', 'C12',
    'KC135', 'KC10', 'KC46',
    'V22', 'CV22',
    'CH47', 'MH47',
    'UH60', 'HH60', 'MH60',
    'UH72',
    'AH64',
    'F15', 'F16', 'F18', 'F22', 'F35',
    'T6', 'T38', 'T45',
    'E6', 'E6B',
}

_MEDEVAC_CALLSIGN_PREFIXES = ('MEDEVAC', 'MEDIVAC', 'LIFEGUARD', 'ANGEL',
                               'AEROCARE', 'AIRCARE', 'CAREFLIGHT')

_SAR_CALLSIGN_PREFIXES = ('RESCUE', 'COAST', 'SAR', 'GUARDEX', 'CGAS')

# PR/Caribbean-specific callsign prefixes added alongside generic military ones
_MILITARY_CALLSIGN_PREFIXES = (
    'REACH', 'JAKE', 'NIGHT', 'BRONCO', 'IRON',
    'HAVOC', 'SWIFT', 'STEEL', 'COPPER', 'TUSK',
    'BISON', 'ATLAS', 'BOXER', 'MAGIC', 'EAGLE',
    # CBP Air and Marine Operations (Aguadilla-based)
    'OMAHA', 'DOMAIN', 'SENTRY',
    # Puerto Rico ANG
    'COQUI', 'PRESTO',
)

_SQUAWK_MILITARY_IFR = {'1000'}
_SQUAWK_EMERGENCY = {'7500', '7600', '7700'}
# USCG-assigned squawk block
_SQUAWK_USCG = {str(c) for c in range(4400, 4478)}

_COMMERCIAL_TYPES = {
    # Boeing 737 family
    'B735', 'B736', 'B737', 'B738', 'B739', 'B73X',
    'B37M', 'B38M', 'B39M',          # 737 MAX 7/8/9
    # Boeing 747/757/767/777/787
    'B742', 'B743', 'B744', 'B748', 'B74F', 'B74S',
    'B752', 'B753',
    'B762', 'B763', 'B764',
    'B772', 'B773', 'B77W', 'B77L',
    'B788', 'B789', 'B78X',
    # Boeing 717 / MD family
    'B712', 'MD11', 'MD80', 'MD81', 'MD82', 'MD83', 'MD88', 'MD90',
    # Airbus A220/A320/A330/A340/A350/A380
    'BCS1', 'BCS3',                   # A220-100/300
    'A318', 'A319', 'A320', 'A321',
    'A19N', 'A20N', 'A21N',           # neo variants
    'A332', 'A333', 'A338', 'A339',
    'A342', 'A343', 'A345', 'A346',
    'A358', 'A359', 'A35K',
    'A388',
    # Embraer E-jets
    'E135', 'E140', 'E145',
    'E170', 'E175', 'E190', 'E195',
    'E290', 'E295',
    # Bombardier CRJ / Q-series
    'CRJ2', 'CRJ7', 'CRJ9', 'CRJX',
    'DH8A', 'DH8B', 'DH8C', 'DH8D',
    'AT42', 'AT43', 'AT45', 'AT72', 'AT75', 'AT76',
    # Fokker
    'F100', 'F70', 'F50', 'F28',
    # BAe 146 / Avro RJ
    'B461', 'B462', 'B463', 'B464',
    'RJ1H', 'RJ85', 'RJ70',
    # Saab
    'SB20', 'SF34',
    # Sukhoi Superjet / COMAC
    'SU95', 'C919', 'AR21',
}

_CARGO_OPERATORS = {
    'FEDEX', 'FDX', 'UPS', 'UPSCO', 'DHL', 'AMAZON',
    'ATLAS', 'GTI', 'SOUTHERN', 'ABX', 'KALITTA', 'POLAR', 'CARGOLUX',
    'AIRBRIDGE', 'SILK', 'CARGOJET',
}

_GA_TYPES = {
    # Cessna piston
    'C150', 'C152', 'C162', 'C172', 'C177', 'C180', 'C182', 'C185',
    'C206', 'C207', 'C208', 'C210', 'C303', 'C310', 'C337',
    'C340', 'C402', 'C404', 'C414', 'C421', 'C425', 'C441',
    # Cessna Citation jets
    'C25A', 'C25B', 'C25C', 'C510', 'C525', 'C526',
    'C550', 'C560', 'C56X', 'C680', 'C68A', 'C750',
    # Piper
    'PA18', 'PA28', 'PA32', 'PA34', 'PA44', 'PA46', 'P46T',
    # Beechcraft / Textron
    'BE18', 'BE19', 'BE23', 'BE24', 'BE35', 'B36T',
    'BE36', 'BE58', 'BE60', 'BE76', 'BE90', 'BE99',
    'BE10', 'BE20', 'BE30', 'B350',
    # Cirrus
    'SR20', 'SR22', 'SF50',
    # TBM
    'TBM7', 'TBM8', 'TBM9',
    # Diamond
    'DA20', 'DA40', 'DA42', 'DA50', 'DA62',
    # Mooney
    'M20P', 'M20T', 'M20U',
    # Gulfstream / Dassault / Bombardier business jets
    'GLF4', 'GLF5', 'GLF6',
    'F2TH', 'FA50', 'FA7X', 'FA8X',
    'LJ35', 'LJ45', 'LJ60', 'LJ75',
    'CL30', 'CL35', 'CL60',
    # Embraer biz
    'E50P', 'E55P', 'PC24',
    # HondaJet
    'HA4T',
    # Pilatus
    'PC12', 'PC24', 'PC6',
    # Helicopters (GA / commercial operators)
    'R22', 'R44', 'R66',              # Robinson
    'B06', 'B07', 'B47',              # Bell GA
    'EC20', 'EC30', 'EC35', 'EC45',   # Airbus Helicopters light
    'AS50', 'AS55', 'AS65',           # Aérospatiale
}

# ---------------------------------------------------------------------------
# Non-airport token exclusion set (item 2 — airport disambiguation)
#
# All 3–4 letter uppercase tokens in this set are NOT airport codes and should
# be excluded when scanning OCR text for ICAO/IATA airport identifiers.
# ---------------------------------------------------------------------------

_NON_AIRPORT_CODES: set = (
    # All known aircraft type codes (strip hyphens since OCR may omit them)
    _SURVEILLANCE_TYPES
    | _MILITARY_TRANSPORT_TYPES
    | _COMMERCIAL_TYPES
    | _GA_TYPES
    | {c.replace('-', '') for c in _SURVEILLANCE_TYPES | _MILITARY_TRANSPORT_TYPES}
    # ATC / airspace abbreviations
    | {
        'IFR', 'VFR', 'GPS', 'AGL', 'MSL', 'ASL',
        'ATC', 'NDB', 'VOR', 'DME', 'ILS', 'LOC', 'GLS',
        'FMS', 'FMC', 'ATIS', 'ASOS', 'AWOS',
        'SID', 'STAR', 'IAF', 'FAF', 'MAP',
        'FIR', 'UIR', 'TMA', 'CTA', 'CTR', 'ATZ', 'MATZ', 'ADIZ',
        'GND', 'TWR', 'APP', 'DEP', 'CTL', 'OPS',
        'RVSM', 'ETOPS', 'PBN', 'RNP', 'RNAV',
        'LPV', 'APV', 'CAT', 'SFC', 'MDA',
        'QNH', 'QFE', 'QNE', 'ISA', 'OAT', 'SAT', 'TAT',
        'TCAS', 'ACAS', 'EGPWS', 'TAWS', 'GPWS',
        'ADS', 'ADSB', 'MLAT',
        'EFIS', 'EICAS', 'ECAM', 'AFDS', 'LNAV', 'VNAV',
        'FDR', 'CVR', 'ELT', 'SELCAL', 'CPDLC',
        'ETD', 'ETA', 'ETE', 'TAS',
        'METAR', 'TAF', 'SIGMET', 'PIREP', 'NOTAM',
        # squawk / transponder
        'SQK', 'XPDR', 'SSR', 'IDENT',
        # FR24 UI labels OCR may pick up
        'LIVE', 'PLAY', 'RADAR', 'TYPE', 'ICAO', 'IATA',
        'CALL', 'SIGN', 'FROM', 'DEST', 'ORIG', 'DSTN',
        'TRK', 'HDG', 'SPD', 'ALT', 'VS',
        'AGO', 'UTC', 'EDT', 'EST', 'CDT', 'MDT', 'PDT', 'PST',
        # Cargo operator abbreviations (not airports)
        'UPS', 'DHL', 'ABX', 'ATN', 'GTI', 'PAC', 'SWC',
    }
)


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
        'heading_deg': '',
        'utc_time': '',
        'squawk': '',
        'operator': '',
    }

    # Flight number: IATA (2-char prefix) or ICAO (3-char prefix)
    fn = _search(r'\b([A-Z]{2,3}\s?\d{1,4}[A-Z]?)\b', raw)
    if fn:
        fields['flight_number'] = fn.replace(' ', '')

    # Aircraft registration (covers common formats)
    reg_patterns = [
        r'\b(N\d{1,5}[A-Z]{0,2})\b',          # US
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
        r'\b(YV-[A-Z0-9]{3,4})\b',              # Venezuela
        r'\b(HP-[A-Z0-9]{3,4})\b',              # Panama
        r'\b(YN-[A-Z]{3})\b',                    # Nicaragua
        r'\b([A-Z]{2}-[A-Z]{3,4})\b',           # generic 2-letter prefix
    ]
    for pat in reg_patterns:
        reg = _search(pat, raw)
        if reg:
            fields['registration'] = reg
            break

    # ICAO aircraft type — known sets first, then generic fallback
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

    # Callsign — group prefixes in (?:...) so \w* extends all alternatives
    _all_cs_prefixes = '|'.join(
        _MEDEVAC_CALLSIGN_PREFIXES + _SAR_CALLSIGN_PREFIXES + _MILITARY_CALLSIGN_PREFIXES
    )
    cs_match = re.search(
        r'\b((?:' + _all_cs_prefixes + r')\w*)\b',
        raw, re.IGNORECASE)
    if cs_match:
        fields['callsign'] = cs_match.group(1).upper()

    # Airport codes — three-pass strategy to avoid type-code confusion:
    # Pass 1: explicit arrow/route pattern "KJFK → KLAX"
    arrow_match = re.search(
        r'\b([A-Z]{3,4})\s*[→\-–>]\s*([A-Z]{3,4})\b', raw)
    if arrow_match:
        orig, dest = arrow_match.group(1), arrow_match.group(2)
        if orig not in _NON_AIRPORT_CODES:
            fields['origin'] = orig
        if dest not in _NON_AIRPORT_CODES:
            fields['destination'] = dest
    else:
        # Pass 2: "From:" / "To:" labels
        orig_match = re.search(r'\bFrom\s*:?\s*([A-Z]{3,4})\b', raw, re.IGNORECASE)
        dest_match = re.search(r'\bTo\s*:?\s*([A-Z]{3,4})\b', raw, re.IGNORECASE)
        if orig_match and orig_match.group(1).upper() not in _NON_AIRPORT_CODES:
            fields['origin'] = orig_match.group(1).upper()
        if dest_match and dest_match.group(1).upper() not in _NON_AIRPORT_CODES:
            fields['destination'] = dest_match.group(1).upper()

        if not fields['origin']:
            # Pass 3: generic token scan filtered by exclusion set
            candidates = [
                a for a in re.findall(r'\b([A-Z]{3,4})\b', raw_upper)
                if a not in _NON_AIRPORT_CODES
            ]
            if len(candidates) >= 2:
                fields['origin'] = candidates[0]
                fields['destination'] = candidates[1]
            elif candidates:
                fields['origin'] = candidates[0]

    # Altitude: FL notation or feet
    alt = _search(r'\b(FL\s*\d{2,3})\b', raw, re.IGNORECASE)
    if not alt:
        alt = _search(r'\b(\d{2,5})\s*(?:ft|feet)\b', raw, re.IGNORECASE)
    fields['altitude_ft'] = alt

    # Speed in knots
    spd = _search(r'\b(\d{2,4})\s*(?:kt|kts|knots)\b', raw, re.IGNORECASE)
    fields['speed_kts'] = spd

    # Heading / track in degrees
    hdg = _search(r'\b(?:heading|hdg|trk|track)\s*:?\s*(\d{1,3})\b', raw, re.IGNORECASE)
    if not hdg:
        hdg = _search(r'\b(\d{1,3})\s*°\s*(?:heading|hdg|trk|track|true|mag)?\b',
                      raw, re.IGNORECASE)
    fields['heading_deg'] = hdg

    # UTC timestamp (HH:MM or HH:MM:SS, optionally followed by UTC/Z)
    ts = _search(r'\b(\d{2}:\d{2}(?::\d{2})?)\s*(?:UTC|Z)?\b', raw, re.IGNORECASE)
    fields['utc_time'] = ts

    # Squawk code: 4-digit octal near "squawk" keyword, or USCG range match
    sq = _search(r'squawk\D{0,5}([0-7]{4})', raw, re.IGNORECASE)
    if not sq:
        sq_candidates = re.findall(r'\b([0-7]{4})\b', raw)
        if sq_candidates:
            sq = sq_candidates[0]
    fields['squawk'] = sq

    # Operator / airline name (word(s) immediately before the flight number)
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
        origin, destination, altitude_ft, speed_kts, heading_deg,
        utc_time, squawk, operator
    """
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(f"Image not found: {image_path}")

    img = Image.open(path).convert('RGB')

    # Enhance contrast/sharpness to improve OCR on varied screenshot backgrounds
    img = ImageEnhance.Contrast(img).enhance(1.5)
    img = ImageEnhance.Sharpness(img).enhance(1.3)

    img_array = np.array(img)

    reader = _get_reader()
    results = reader.readtext(img_array, detail=1, paragraph=False)

    texts = [text for (_bbox, text, conf) in results if conf >= 0.3]
    raw = ' '.join(texts)

    fields = _parse_fields(raw)
    fields['ocr_raw_text'] = raw
    return fields
