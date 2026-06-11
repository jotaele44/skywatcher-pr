"""
PHASE 1: ENSEMBLE OCR ENGINE

Runs multiple OCR engines in parallel and combines results via consensus voting.
Gracefully degrades to Tesseract-only when heavy ML engines are not installed.

Engines (in order of preference):
  1. Tesseract  — always available; baseline
  2. PaddleOCR  — optional; requires paddlepaddle + paddleocr
  3. EasyOCR    — optional; requires torch + easyocr

Consensus rule:
  - If 2+ engines agree on a value → boost confidence × 1.1 (cap 1.0)
  - If engines disagree → use highest-confidence value, flag for review
"""

import re
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

from pipeline.hardening_layer import ExtractedField


# ============================================================================
# SINGLE-ENGINE WRAPPERS
# ============================================================================

class TesseractEngine:
    """Tesseract OCR wrapper — always present."""

    name = "tesseract"

    def __init__(self):
        self.available = False
        try:
            import pytesseract
            pytesseract.get_tesseract_version()
            self.available = True
        except Exception:
            pass

    def extract_text(self, image_path: str) -> Tuple[str, float]:
        """Return (raw_text, confidence). Confidence is estimated from char count."""
        if not self.available:
            return "", 0.0
        try:
            import pytesseract
            from PIL import Image

            img = Image.open(image_path)
            data = pytesseract.image_to_data(img, config="--psm 6",
                                             output_type=pytesseract.Output.DICT)
            confidences = [c for c in data["conf"] if isinstance(c, (int, float)) and c >= 0]
            text = " ".join(t for t in data["text"] if t.strip())
            avg_conf = sum(confidences) / len(confidences) / 100.0 if confidences else 0.5
            return text, round(avg_conf, 3)
        except Exception:
            return "", 0.0


class PaddleOCREngine:
    """PaddleOCR wrapper — optional heavy dependency."""

    name = "paddleocr"

    def __init__(self):
        self.available = False
        self._ocr = None
        try:
            from paddleocr import PaddleOCR
            self._ocr = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
            self.available = True
        except Exception:
            pass

    def extract_text(self, image_path: str) -> Tuple[str, float]:
        if not self.available or self._ocr is None:
            return "", 0.0
        try:
            result = self._ocr.ocr(image_path, cls=True)
            lines = []
            confs = []
            for page in (result or []):
                for line in (page or []):
                    if line and len(line) >= 2:
                        text_data = line[1]
                        if isinstance(text_data, (list, tuple)) and len(text_data) >= 2:
                            lines.append(str(text_data[0]))
                            confs.append(float(text_data[1]))
            text = " ".join(lines)
            avg_conf = sum(confs) / len(confs) if confs else 0.5
            return text, round(avg_conf, 3)
        except Exception:
            return "", 0.0


class EasyOCREngine:
    """EasyOCR wrapper — optional heavy dependency (requires torch)."""

    name = "easyocr"

    def __init__(self):
        self.available = False
        self._reader = None
        try:
            import easyocr
            self._reader = easyocr.Reader(["en"], gpu=False, verbose=False)
            self.available = True
        except Exception:
            pass

    def extract_text(self, image_path: str) -> Tuple[str, float]:
        if not self.available or self._reader is None:
            return "", 0.0
        try:
            results = self._reader.readtext(image_path, detail=1)
            lines = [r[1] for r in results]
            confs = [r[2] for r in results]
            text = " ".join(lines)
            avg_conf = sum(confs) / len(confs) if confs else 0.5
            return text, round(avg_conf, 3)
        except Exception:
            return "", 0.0


# ============================================================================
# FIELD PARSERS
# ============================================================================

PR_AIRPORTS = {"SJU", "BQN", "PSE", "NRR", "SIG", "MAZ", "ARE", "CPX", "VQS"}
_SKIP_TOKENS = {"OCR", "GPS", "AGL", "MSL", "UTC", "IFR", "VFR", "ETA", "ETD"}


def _parse_callsign(text: str) -> str:
    m = re.search(r'\b(N\d{1,5}[A-Z]{0,2})\b', text)
    if m:
        return m.group(1)
    m = re.search(r'\b(C\d{4,6})\b', text)
    if m:
        return m.group(1)
    return ""


def _parse_altitude(text: str) -> int:
    m = re.search(r'(\d[\d,]+)\s*ft', text, re.IGNORECASE)
    if m:
        try:
            return int(m.group(1).replace(",", ""))
        except ValueError:
            pass
    return 0


def _parse_speed(text: str) -> int:
    m = re.search(r'(\d{2,3})\s*mph', text, re.IGNORECASE)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return 0


def _parse_aircraft_type(text: str) -> str:
    known = ["H125", "H130", "AS50", "AS55", "MH60", "MH-60", "B429",
             "B407", "EC35", "EC45", "AW139", "S76", "R44", "R66", "A109"]
    tu = text.upper()
    for t in known:
        if t.upper() in tu:
            return t
    return ""


def _parse_origin_dest(text: str) -> Tuple[str, str]:
    airports = re.findall(r'\b([A-Z]{3})\b', text)
    pr = [a for a in airports if a in PR_AIRPORTS]
    origin = pr[0] if pr else ""
    dest = pr[1] if len(pr) > 1 else ""
    return origin, dest


PARSERS = {
    "callsign":      _parse_callsign,
    "altitude_ft":   _parse_altitude,
    "speed_mph":     _parse_speed,
    "aircraft_type": _parse_aircraft_type,
}


# ============================================================================
# ENSEMBLE OCR
# ============================================================================

class EnsembleOCR:
    """
    Runs available OCR engines in parallel and combines their text outputs
    via field-level consensus voting.

    Usage:
        ocr = EnsembleOCR()
        fields = ocr.extract("screenshot.jpg")
        callsign_field = fields.get("callsign")
        if callsign_field and callsign_field.is_reliable():
            print(callsign_field.value)
    """

    AGREEMENT_BOOST = 0.08  # Added to avg confidence when engines agree

    def __init__(self):
        self.engines = [
            TesseractEngine(),
            PaddleOCREngine(),
            EasyOCREngine(),
        ]
        self.active_engines = [e for e in self.engines if e.available]
        engine_names = [e.name for e in self.active_engines]
        print(f"  EnsembleOCR: {len(self.active_engines)} engine(s) active — {engine_names}")

    def extract(self, image_path: str) -> Dict[str, ExtractedField]:
        """
        Extract fields from image_path using all available engines.
        Returns dict of field_name → ExtractedField.
        """
        if not self.active_engines:
            return {}

        image_filename = os.path.basename(image_path)

        # Run engines in parallel
        engine_results: Dict[str, Tuple[str, float]] = {}
        with ThreadPoolExecutor(max_workers=len(self.active_engines)) as executor:
            futures = {
                executor.submit(e.extract_text, image_path): e.name
                for e in self.active_engines
            }
            for future in as_completed(futures):
                engine_name = futures[future]
                try:
                    text, conf = future.result()
                    engine_results[engine_name] = (text, conf)
                except Exception:
                    engine_results[engine_name] = ("", 0.0)

        # Parse each field from each engine's text
        field_candidates: Dict[str, List[Tuple[str, float]]] = {
            f: [] for f in PARSERS
        }

        for engine_name, (text, engine_conf) in engine_results.items():
            if not text:
                continue
            for field_name, parser in PARSERS.items():
                value = parser(text)
                if value:
                    field_candidates[field_name].append((str(value), engine_conf))

        # Also parse origin/dest separately (returns two values)
        for engine_name, (text, engine_conf) in engine_results.items():
            if not text:
                continue
            origin, dest = _parse_origin_dest(text)
            if origin:
                field_candidates.setdefault("origin_airport", []).append((origin, engine_conf))
            if dest:
                field_candidates.setdefault("destination_airport", []).append((dest, engine_conf))

        # Build consensus ExtractedField per field
        extracted: Dict[str, ExtractedField] = {}

        for field_name, candidates in field_candidates.items():
            if not candidates:
                continue

            ef = self._vote(field_name, candidates, image_filename)
            if ef:
                extracted[field_name] = ef

        return extracted

    def _vote(self, field_name: str, candidates: List[Tuple[str, float]],
              source_frame: str) -> Optional[ExtractedField]:
        """Choose the best value via majority vote; compute confidence."""
        if not candidates:
            return None

        # Count agreement
        value_groups: Dict[str, List[float]] = {}
        for value, conf in candidates:
            value_groups.setdefault(value, []).append(conf)

        # Best value = most votes (tie-break: higher avg confidence)
        best_value = max(
            value_groups,
            key=lambda v: (len(value_groups[v]), sum(value_groups[v]) / len(value_groups[v]))
        )
        best_confs = value_groups[best_value]
        total_engines = len(candidates)
        agreement = len(best_confs) / total_engines
        avg_conf = sum(best_confs) / len(best_confs)

        # Boost confidence for inter-engine agreement
        if agreement > 0.5:
            boosted_conf = min(1.0, avg_conf + self.AGREEMENT_BOOST * agreement)
        else:
            boosted_conf = avg_conf

        # Try to restore original typed value
        typed_value: Any = best_value
        for parser_name, parser in PARSERS.items():
            if parser_name == field_name:
                try:
                    parsed = parser(" " + best_value + " ")
                    if parsed:
                        typed_value = parsed
                except Exception:
                    pass
                break

        return ExtractedField(
            value=typed_value,
            ocr_confidence=round(boosted_conf, 4),
            validation_score=1.0,
            consistency_score=round(agreement, 4),
            extraction_method="ensemble" if len(self.active_engines) > 1 else "tesseract",
            source_frame=source_frame,
            field_name=field_name,
        )

    def get_engine_status(self) -> Dict[str, bool]:
        return {e.name: e.available for e in self.engines}


if __name__ == "__main__":
    ocr = EnsembleOCR()
    status = ocr.get_engine_status()
    print(f"\nEngine availability: {status}")
    print(f"Active engines: {sum(status.values())}/{len(status)}")
