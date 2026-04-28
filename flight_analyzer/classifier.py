"""
GPT-4o Vision classifier for FlightRadar24 flight-purpose analysis.

Sends the screenshot image + OCR-extracted fields in a single API call.
Returns purpose label, confidence, route shape, and reasoning.
"""

import base64
import json
import re
import time
from io import BytesIO
from pathlib import Path

from PIL import Image

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 2  # seconds; doubled each attempt (2 → 4 → 8)

PURPOSE_LABELS = {
    'commercial_airline',
    'cargo_freight',
    'private_ga',
    'medical_medevac',
    'training',
    'surveillance_recon',
    'military_law_enforcement',
    'search_rescue',
}

ROUTE_SHAPES = {
    'straight_cruise',
    'orbit_loiter',
    'holding_pattern',
    'sweep_pattern',
    'touch_and_go',
    'unknown',
}

_MAX_IMAGE_PX = 1024  # resize longest side to this before sending

_SYSTEM_PROMPT = """You are an aviation intelligence analyst specialising in flight-purpose classification from FlightRadar24 screenshots.

Your task: classify the flight shown in the screenshot into EXACTLY ONE purpose label, and describe the route shape.

PURPOSE LABELS (use these exact strings):
  commercial_airline      — Scheduled or charter passenger service operated by an airline
  cargo_freight           — Cargo/freight transport (FedEx, UPS, DHL, Amazon Air, freighters)
  private_ga              — Private, general aviation, business jets, turboprops, small aircraft
  medical_medevac         — Air ambulance, organ transport, medical evacuation flights
  training                — Flight training, proficiency, test/certification, touch-and-go circuits
  surveillance_recon      — ISR/reconnaissance orbit or loiter pattern, no filed destination, sensor aircraft
  military_law_enforcement — Military transport/tanker/fighter/patrol, law enforcement (CBP, DEA, USCG)
  search_rescue           — SAR sweeps, coast guard, parallel track or expanding square search patterns

ROUTE SHAPE LABELS (use these exact strings):
  straight_cruise    — Standard point-to-point flight
  orbit_loiter       — Circular or figure-eight holding over one area (strong surveillance indicator)
  holding_pattern    — Standard rectangular holding pattern (ATC instruction)
  sweep_pattern      — Systematic back-and-forth or expanding grid (SAR indicator)
  touch_and_go       — Repeated circuit patterns at an airport (training indicator)
  unknown            — Route not clearly visible or ambiguous

KEY CLASSIFICATION SIGNALS:
- Circular or loitering route + ISR aircraft type (U-2, RC-135, P-3, RQ-4, MC-12, etc.) → surveillance_recon
- Sweep/grid pattern + coast guard / SAR callsign → search_rescue
- Squawk 1000 → military IFR
- Callsigns: REACH/JAKE/NIGHT/BRONCO/COPPER → likely military
- Callsigns: MEDEVAC/LIFEGUARD/ANGEL → medical_medevac
- Callsigns: RESCUE/COAST/SAR → search_rescue
- No destination filed + loiter route → surveillance_recon
- Registered freight carriers (FedEx, UPS, DHL, Kalitta, Atlas) → cargo_freight
- Circuit patterns at same airport → training

IMPORTANT: Base your classification on ALL available signals: aircraft type, callsign, operator, squawk, route shape, and flight number format. Prefer the most specific label that fits.

Respond with ONLY valid JSON, no markdown, no extra text:
{"purpose_label": "<label>", "confidence": <0.0 to 1.0>, "route_shape": "<shape>", "reasoning": "<1-2 sentence explanation>"}"""


def _encode_image(image_path: str) -> str:
    """Load, resize, and base64-encode the screenshot as JPEG."""
    img = Image.open(image_path).convert('RGB')

    w, h = img.size
    longest = max(w, h)
    if longest > _MAX_IMAGE_PX:
        scale = _MAX_IMAGE_PX / longest
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    buf = BytesIO()
    img.save(buf, format='JPEG', quality=85)
    return base64.b64encode(buf.getvalue()).decode('utf-8')


def _format_ocr_fields(ocr_fields: dict) -> str:
    """Format OCR-extracted fields as a human-readable block for the prompt."""
    keys = ['flight_number', 'registration', 'aircraft_type', 'callsign',
            'origin', 'destination', 'altitude_ft', 'speed_kts', 'squawk', 'operator']
    lines = []
    for k in keys:
        val = ocr_fields.get(k, '') or '(not detected)'
        lines.append(f"  {k}: {val}")
    return '\n'.join(lines)


def _parse_response(content: str) -> dict:
    """Extract JSON from GPT-4o response, tolerating minor formatting issues."""
    # Strip markdown code fences if present
    content = re.sub(r'```(?:json)?\s*', '', content).strip().rstrip('`').strip()

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        # Try to extract the first JSON object via regex
        m = re.search(r'\{.*\}', content, re.DOTALL)
        if m:
            data = json.loads(m.group(0))
        else:
            return {
                'purpose_label': 'unknown',
                'confidence': 0.0,
                'route_shape': 'unknown',
                'reasoning': f'Failed to parse model response: {content[:200]}',
            }

    # Validate and normalise
    label = data.get('purpose_label', 'unknown')
    if label not in PURPOSE_LABELS:
        label = 'unknown'

    shape = data.get('route_shape', 'unknown')
    if shape not in ROUTE_SHAPES:
        shape = 'unknown'

    try:
        conf = float(data.get('confidence', 0.0))
        conf = max(0.0, min(1.0, conf))
    except (TypeError, ValueError):
        conf = 0.0

    return {
        'purpose_label': label,
        'confidence': conf,
        'route_shape': shape,
        'reasoning': str(data.get('reasoning', '')),
    }


def classify_flight(image_path: str, ocr_fields: dict, api_key: str) -> dict:
    """
    Send the screenshot + OCR fields to GPT-4o Vision and return classification.

    Returns dict with keys: purpose_label, confidence, route_shape, reasoning.
    Raises RuntimeError on API error (caller should catch and handle).
    """
    import openai  # deferred import so the module loads without openai installed

    client = openai.OpenAI(api_key=api_key)

    b64_image = _encode_image(image_path)
    ocr_block = _format_ocr_fields(ocr_fields)

    user_content = [
        {
            'type': 'image_url',
            'image_url': {
                'url': f'data:image/jpeg;base64,{b64_image}',
                'detail': 'high',
            },
        },
        {
            'type': 'text',
            'text': (
                'OCR-extracted fields from this FlightRadar24 screenshot:\n'
                + ocr_block
                + '\n\nClassify this flight.'
            ),
        },
    ]

    last_exc: Exception = Exception('no attempts made')
    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model='gpt-4o',
                messages=[
                    {'role': 'system', 'content': _SYSTEM_PROMPT},
                    {'role': 'user', 'content': user_content},
                ],
                max_tokens=256,
                temperature=0.1,
                response_format={'type': 'json_object'},
            )
            return _parse_response(response.choices[0].message.content or '')
        except openai.RateLimitError as exc:
            # 429: back off and retry
            last_exc = exc
        except openai.APIStatusError as exc:
            if exc.status_code >= 500:
                # Transient server error: back off and retry
                last_exc = exc
            else:
                raise RuntimeError(f'OpenAI API error: {exc}') from exc
        except openai.OpenAIError as exc:
            raise RuntimeError(f'OpenAI API error: {exc}') from exc

        if attempt < _MAX_RETRIES:
            time.sleep(_RETRY_BASE_DELAY * (2 ** attempt))

    raise RuntimeError(
        f'OpenAI API error after {_MAX_RETRIES} retries: {last_exc}'
    ) from last_exc
