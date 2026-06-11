"""
PHASE 0: IMAGE PROCESSING ENGINE

FlightRadarOCR   — Extracts callsign, type, route, altitude, speed from images
CoordinateMapper — Pixel ↔ geographic coordinate conversion
FlightDatabase   — SQLite persistent storage for flights and track points
FlightAnalyzer   — Orchestrates image processing and database population
"""

import os
import re
import sqlite3
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pipeline.db_utils import configure_connection


# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class ExtractedFlightData:
    callsign: str = ""
    aircraft_type: str = ""
    operator: str = ""
    origin_airport: str = ""
    destination_airport: str = ""
    altitude_ft: int = 0
    ground_speed_mph: int = 0
    departed_seconds_ago: int = 0
    arriving_in_seconds: int = 0
    latitude: float = 0.0
    longitude: float = 0.0
    timestamp: str = ""
    raw_text: str = ""
    ocr_confidence: float = 0.0


@dataclass
class FlightRecord:
    flight_id: str
    callsign: str
    aircraft_type: str
    operator: str
    origin_airport: str
    destination_airport: str
    origin_lat: float
    origin_lon: float
    dest_lat: float
    dest_lon: float
    takeoff_time: str
    landing_time: str
    flight_duration_minutes: int
    max_altitude_ft: int
    avg_speed_mph: float
    mission_type: str
    num_screenshots: int
    track_points: List[Dict] = field(default_factory=list)


# Puerto Rico geographic bounds for coordinate mapping
PR_BOUNDS = {
    "north": 18.65,
    "south": 17.92,
    "east": -65.20,
    "west": -67.30,
}


# ============================================================================
# OCR ENGINE (Tesseract-based)
# ============================================================================

class FlightRadarOCR:
    """
    Extracts structured flight data from FlightRadar24 screenshots using Tesseract.
    Targets the bottom information panel which contains structured text.
    """

    # Known Puerto Rico airports for origin/destination parsing
    PR_AIRPORTS = {"SJU", "BQN", "PSE", "NRR", "SIG", "MAZ", "ARE", "CPX", "VQS"}

    def __init__(self):
        self._tesseract_available = self._check_tesseract()

    def _check_tesseract(self) -> bool:
        try:
            import pytesseract
            pytesseract.get_tesseract_version()
            return True
        except Exception:
            return False

    def extract_from_image(self, image_path: str) -> ExtractedFlightData:
        """Extract all flight data fields from a screenshot."""
        data = ExtractedFlightData()
        data.timestamp = self._extract_timestamp(image_path)

        if not self._tesseract_available:
            return data

        try:
            import pytesseract
            from PIL import Image
            import numpy as np

            img = Image.open(image_path)
            width, height = img.size

            # Bottom panel: roughly the lower 25% of the image
            panel_top = int(height * 0.75)
            panel = img.crop((0, panel_top, width, height))

            # Full-image OCR for callsign (usually large text)
            full_text = pytesseract.image_to_string(img, config="--psm 6")
            panel_text = pytesseract.image_to_string(panel, config="--psm 6")

            combined = full_text + "\n" + panel_text
            data.raw_text = combined

            data.callsign = self._extract_callsign(combined)
            data.aircraft_type = self._extract_aircraft_type(combined)
            data.operator = self._extract_operator(combined)
            data.origin_airport, data.destination_airport = self._extract_route(combined)
            data.altitude_ft = self._extract_altitude(combined)
            data.ground_speed_mph = self._extract_speed(combined)
            data.departed_seconds_ago, data.arriving_in_seconds = self._extract_timing(combined)
            data.ocr_confidence = 0.85 if data.callsign else 0.20

        except Exception:
            pass

        return data

    def _extract_timestamp(self, image_path: str) -> str:
        """Extract timestamp from image EXIF data or filename."""
        try:
            from PIL import Image
            img = Image.open(image_path)
            exif = img._getexif() or {}
            # EXIF tag 36867 = DateTimeOriginal
            dt_str = exif.get(36867, "")
            if dt_str:
                dt = datetime.strptime(dt_str, "%Y:%m:%d %H:%M:%S")
                return dt.isoformat()
        except Exception:
            pass

        # Fall back to modification time
        try:
            mtime = os.path.getmtime(image_path)
            return datetime.utcfromtimestamp(mtime).isoformat()
        except Exception:
            return datetime.utcnow().isoformat()

    def _extract_callsign(self, text: str) -> str:
        """Extract N-number or ICAO callsign from OCR text."""
        # N-number pattern (US civil aircraft)
        match = re.search(r'\b(N\d{1,5}[A-Z]{0,2})\b', text)
        if match:
            return match.group(1)

        # Coast Guard pattern (C followed by digits)
        match = re.search(r'\b(C\d{4,6})\b', text)
        if match:
            return match.group(1)

        # Generic ICAO callsign (3 letters + digits)
        match = re.search(r'\b([A-Z]{3}\d{3,4})\b', text)
        if match:
            return match.group(1)

        return ""

    def _extract_aircraft_type(self, text: str) -> str:
        known_types = [
            "H125", "H130", "AS50", "AS55", "MH60", "MH-60", "B429", "B407",
            "EC35", "EC45", "AW139", "S76", "R44", "R66", "A109",
        ]
        text_upper = text.upper()
        for t in known_types:
            if t.upper() in text_upper:
                return t
        return ""

    def _extract_operator(self, text: str) -> str:
        operator_patterns = [
            (r"(?i)coast\s*guard", "US Coast Guard"),
            (r"(?i)PREPA|electric\s*power", "Puerto Rico Electric Power Authority"),
            (r"(?i)FURA|policia|police", "Puerto Rico Police FURA"),
            (r"(?i)charter|private", "Private/Charter"),
        ]
        for pattern, name in operator_patterns:
            if re.search(pattern, text):
                return name
        return ""

    def _extract_route(self, text: str) -> Tuple[str, str]:
        # Look for airport codes: 3 capital letters
        airports = re.findall(r'\b([A-Z]{3})\b', text)
        pr_airports = [a for a in airports if a in self.PR_AIRPORTS]
        other_airports = [a for a in airports if a not in self.PR_AIRPORTS and a not in
                          {"OCR", "GPS", "AGL", "MSL", "UTC", "IFR", "VFR"}]

        origin = pr_airports[0] if pr_airports else (other_airports[0] if other_airports else "")
        destination = pr_airports[1] if len(pr_airports) > 1 else ""

        return origin, destination

    def _extract_altitude(self, text: str) -> int:
        # Look for altitude patterns like "5,250 ft" or "5250ft" or "5,250"
        match = re.search(r'(\d[\d,]+)\s*ft', text, re.IGNORECASE)
        if match:
            try:
                return int(match.group(1).replace(",", ""))
            except ValueError:
                pass

        # Bare number between 100 and 20000 near "alt" keyword
        match = re.search(r'alt[itude]*\s*:?\s*(\d[\d,]+)', text, re.IGNORECASE)
        if match:
            try:
                return int(match.group(1).replace(",", ""))
            except ValueError:
                pass

        return 0

    def _extract_speed(self, text: str) -> int:
        # "112 mph" or "112mph" or "spd: 112"
        match = re.search(r'(\d{2,3})\s*mph', text, re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                pass

        match = re.search(r'(?:spd|speed)\s*:?\s*(\d{2,3})', text, re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                pass

        return 0

    def _extract_timing(self, text: str) -> Tuple[int, int]:
        departed_sec = 0
        arriving_sec = 0

        # "Departed 1h 23m ago" or "23m ago"
        match = re.search(r'(\d+)\s*h\s*(\d+)\s*m\s*ago', text, re.IGNORECASE)
        if match:
            departed_sec = int(match.group(1)) * 3600 + int(match.group(2)) * 60
        else:
            match = re.search(r'(\d+)\s*m\s*ago', text, re.IGNORECASE)
            if match:
                departed_sec = int(match.group(1)) * 60

        # "Arriving in 45m" or "arriving in 1h 12m"
        match = re.search(r'arriving\s+in\s+(\d+)\s*h\s*(\d+)\s*m', text, re.IGNORECASE)
        if match:
            arriving_sec = int(match.group(1)) * 3600 + int(match.group(2)) * 60
        else:
            match = re.search(r'arriving\s+in\s+(\d+)\s*m', text, re.IGNORECASE)
            if match:
                arriving_sec = int(match.group(1)) * 60

        return departed_sec, arriving_sec


# ============================================================================
# COORDINATE MAPPER
# ============================================================================

class CoordinateMapper:
    """
    Converts pixel positions in a FlightRadar24 screenshot to
    geographic coordinates using the known Puerto Rico map bounds.
    """

    def __init__(self, image_width: int, image_height: int,
                 map_bounds: Dict = None):
        self.image_width = image_width
        self.image_height = image_height
        # Portion of image that is the map (approximately)
        self.map_top_fraction = 0.15     # header
        self.map_bottom_fraction = 0.75  # map ends here
        self.bounds = map_bounds or PR_BOUNDS

    def pixel_to_latlon(self, px: int, py: int) -> Tuple[float, float]:
        """Convert pixel (px, py) to (latitude, longitude)."""
        map_top_px = self.image_height * self.map_top_fraction
        map_bottom_px = self.image_height * self.map_bottom_fraction
        map_height_px = map_bottom_px - map_top_px

        if map_height_px <= 0:
            return 0.0, 0.0

        # Normalize to [0, 1] within the map area
        rel_y = (py - map_top_px) / map_height_px
        rel_x = px / self.image_width

        # Map to geographic coordinates
        lat = self.bounds["north"] - rel_y * (self.bounds["north"] - self.bounds["south"])
        lon = self.bounds["west"] + rel_x * (self.bounds["east"] - self.bounds["west"])

        return round(lat, 5), round(lon, 5)

    def detect_aircraft_position(self, image_path: str) -> Tuple[float, float]:
        """Detect the orange helicopter icon and return its lat/lon."""
        try:
            from PIL import Image
            import numpy as np

            img = Image.open(image_path).convert("RGB")
            arr = np.array(img)

            # Orange pixels: R > 200, G 80-160, B < 80
            orange_mask = (arr[:, :, 0] > 200) & (arr[:, :, 1] > 80) & \
                          (arr[:, :, 1] < 160) & (arr[:, :, 2] < 80)

            ys, xs = np.where(orange_mask)
            if len(xs) == 0:
                return 0.0, 0.0

            cx = int(xs.mean())
            cy = int(ys.mean())
            return self.pixel_to_latlon(cx, cy)

        except Exception:
            return 0.0, 0.0


# ============================================================================
# FLIGHT DATABASE
# ============================================================================

class FlightDatabase:
    """
    SQLite-backed storage for flights, track points, and screenshots.
    """

    def __init__(self, db_path: str = str(Path.home() / "flight_database.db")):
        self.db_path = db_path
        self._init_tables()

    def _init_tables(self):
        conn = sqlite3.connect(self.db_path)
        configure_connection(conn)
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS flights (
                flight_id TEXT PRIMARY KEY,
                callsign TEXT,
                aircraft_type TEXT,
                operator TEXT,
                origin_airport TEXT,
                destination_airport TEXT,
                origin_lat REAL,
                origin_lon REAL,
                dest_lat REAL,
                dest_lon REAL,
                takeoff_time TEXT,
                landing_time TEXT,
                flight_duration_minutes INTEGER,
                max_altitude_ft INTEGER,
                avg_speed_mph REAL,
                mission_type TEXT,
                num_screenshots INTEGER
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS track_points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                flight_id TEXT,
                timestamp TEXT,
                latitude REAL,
                longitude REAL,
                altitude_ft INTEGER,
                ground_speed_mph INTEGER,
                FOREIGN KEY(flight_id) REFERENCES flights(flight_id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS screenshots (
                screenshot_id TEXT PRIMARY KEY,
                image_path TEXT,
                flight_id TEXT,
                processed_at TEXT,
                callsign TEXT,
                altitude_ft INTEGER,
                ground_speed_mph INTEGER,
                latitude REAL,
                longitude REAL,
                timestamp TEXT,
                raw_text TEXT,
                ocr_confidence REAL
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS aircraft_profiles (
                callsign TEXT PRIMARY KEY,
                aircraft_type TEXT,
                owner TEXT,
                operator TEXT,
                primary_mission TEXT,
                confidence_level REAL,
                total_flights INTEGER,
                first_seen TEXT,
                last_seen TEXT,
                operational_patterns TEXT
            )
        ''')

        # Indexes for fast queries
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_flights_callsign ON flights(callsign)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_track_flight ON track_points(flight_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_screenshots_flight ON screenshots(flight_id)")
        # T4-25: covering indexes for hot bridge and pipeline queries
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_flights_origin ON flights(origin_airport)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_flights_dest ON flights(destination_airport)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_flights_mission ON flights(mission_type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_screenshots_conf ON screenshots(ocr_confidence)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_track_coords ON track_points(latitude, longitude)")

        # Evidence-chain columns added in integration hardening upgrade
        _NEW_SCREENSHOT_COLS = [
            ("sha256", "TEXT"),
            ("coordinate_method", "TEXT"),
            ("coordinate_confidence", "REAL"),
            ("estimated_error_m", "REAL"),
            ("review_status", "TEXT DEFAULT 'pending'"),
        ]
        for col_name, col_type in _NEW_SCREENSHOT_COLS:
            try:
                cursor.execute(f"ALTER TABLE screenshots ADD COLUMN {col_name} {col_type}")
            except sqlite3.OperationalError:
                pass

        conn.commit()
        conn.close()

    def store_screenshot(self, screenshot_id: str, image_path: str,
                        data: ExtractedFlightData,
                        coordinate_method: str = "fixed_pr_bounds",
                        coordinate_confidence: float = 0.65,
                        estimated_error_m: float = 1500.0):
        # When screenshot_id is the sha256 (content-addressed), reuse it directly.
        # Fall back to computing from file when called with a non-hash id.
        if len(screenshot_id) == 64 and all(c in "0123456789abcdef" for c in screenshot_id):
            sha256_hex = screenshot_id
        else:
            try:
                sha256_hex = hashlib.sha256(Path(image_path).read_bytes()).hexdigest()
            except Exception:
                sha256_hex = None

        conn = sqlite3.connect(self.db_path)
        configure_connection(conn)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO screenshots
            (screenshot_id, image_path, flight_id, processed_at,
             callsign, altitude_ft, ground_speed_mph,
             latitude, longitude, timestamp, raw_text, ocr_confidence,
             sha256, coordinate_method, coordinate_confidence,
             estimated_error_m, review_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            screenshot_id, image_path, None,
            datetime.utcnow().isoformat(),
            data.callsign, data.altitude_ft, data.ground_speed_mph,
            data.latitude, data.longitude, data.timestamp,
            data.raw_text[:2000], data.ocr_confidence,
            sha256_hex, coordinate_method, coordinate_confidence,
            estimated_error_m, "pending",
        ))
        conn.commit()
        conn.close()

    def store_flight(self, record: FlightRecord):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO flights
            (flight_id, callsign, aircraft_type, operator,
             origin_airport, destination_airport,
             origin_lat, origin_lon, dest_lat, dest_lon,
             takeoff_time, landing_time, flight_duration_minutes,
             max_altitude_ft, avg_speed_mph, mission_type, num_screenshots)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            record.flight_id, record.callsign, record.aircraft_type, record.operator,
            record.origin_airport, record.destination_airport,
            record.origin_lat, record.origin_lon, record.dest_lat, record.dest_lon,
            record.takeoff_time, record.landing_time, record.flight_duration_minutes,
            record.max_altitude_ft, record.avg_speed_mph,
            record.mission_type, record.num_screenshots,
        ))

        for pt in record.track_points:
            cursor.execute('''
                INSERT INTO track_points
                (flight_id, timestamp, latitude, longitude, altitude_ft, ground_speed_mph)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                record.flight_id, pt.get("timestamp", ""),
                pt.get("latitude", 0.0), pt.get("longitude", 0.0),
                pt.get("altitude_ft", 0), pt.get("ground_speed_mph", 0),
            ))

        conn.commit()
        conn.close()

    def get_screenshots_by_callsign(self, callsign: str) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM screenshots WHERE callsign = ? ORDER BY timestamp",
            (callsign,)
        )
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return rows

    def query_flights_by_callsign(self, callsign: str) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM flights WHERE callsign = ? ORDER BY takeoff_time DESC",
            (callsign,)
        )
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return rows

    def get_all_callsigns(self) -> List[str]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT callsign FROM screenshots WHERE callsign != '' ORDER BY callsign")
        rows = [r[0] for r in cursor.fetchall()]
        conn.close()
        return rows


# ============================================================================
# FLIGHT GROUPER
# ============================================================================

class FlightGrouper:
    """
    Groups consecutive screenshots of the same aircraft into flight records.
    Uses a 30-minute gap to detect separate flights.
    """

    GAP_MINUTES = 30

    def group_screenshots(self, screenshots: List[Dict]) -> List[FlightRecord]:
        if not screenshots:
            return []

        screenshots_sorted = sorted(screenshots, key=lambda s: s.get("timestamp", ""))
        flights = []
        current_group = [screenshots_sorted[0]]

        for s in screenshots_sorted[1:]:
            try:
                prev_time = datetime.fromisoformat(current_group[-1]["timestamp"])
                curr_time = datetime.fromisoformat(s["timestamp"])
                gap_min = (curr_time - prev_time).total_seconds() / 60
            except Exception:
                gap_min = 0

            if gap_min > self.GAP_MINUTES:
                flights.append(self._build_flight_record(current_group))
                current_group = [s]
            else:
                current_group.append(s)

        if current_group:
            flights.append(self._build_flight_record(current_group))

        return flights

    def _build_flight_record(self, screenshots: List[Dict]) -> FlightRecord:
        callsign = screenshots[0].get("callsign", "UNKNOWN")

        # Sort by timestamp
        screenshots = sorted(screenshots, key=lambda s: s.get("timestamp", ""))

        takeoff_time = screenshots[0].get("timestamp", "")
        landing_time = screenshots[-1].get("timestamp", "")

        try:
            t0 = datetime.fromisoformat(takeoff_time)
            t1 = datetime.fromisoformat(landing_time)
            duration_min = int((t1 - t0).total_seconds() / 60)
        except Exception:
            duration_min = 0

        altitudes = [s.get("altitude_ft") or 0 for s in screenshots]
        speeds = [s.get("ground_speed_mph") or 0 for s in screenshots]
        max_alt = max(altitudes) if altitudes else 0
        avg_speed = sum(speeds) / len(speeds) if speeds else 0

        origin_lat = screenshots[0].get("latitude") or 0.0
        origin_lon = screenshots[0].get("longitude") or 0.0
        dest_lat = screenshots[-1].get("latitude") or 0.0
        dest_lon = screenshots[-1].get("longitude") or 0.0

        track_points = [
            {
                "timestamp": s.get("timestamp", ""),
                "latitude": s.get("latitude") or 0.0,
                "longitude": s.get("longitude") or 0.0,
                "altitude_ft": s.get("altitude_ft") or 0,
                "ground_speed_mph": s.get("ground_speed_mph") or 0,
            }
            for s in screenshots
            if s.get("latitude") and s.get("longitude")
        ]

        flight_id = f"{callsign}_{takeoff_time[:10]}_{hashlib.md5(takeoff_time.encode()).hexdigest()[:6]}"

        return FlightRecord(
            flight_id=flight_id,
            callsign=callsign,
            aircraft_type=screenshots[0].get("aircraft_type", ""),
            operator=screenshots[0].get("operator", ""),
            origin_airport=screenshots[0].get("origin_airport", ""),
            destination_airport=screenshots[-1].get("destination_airport", ""),
            origin_lat=origin_lat,
            origin_lon=origin_lon,
            dest_lat=dest_lat,
            dest_lon=dest_lon,
            takeoff_time=takeoff_time,
            landing_time=landing_time,
            flight_duration_minutes=duration_min,
            max_altitude_ft=max_alt,
            avg_speed_mph=round(avg_speed, 1),
            mission_type="",
            num_screenshots=len(screenshots),
            track_points=track_points,
        )


# ============================================================================
# FLIGHT ANALYZER (ORCHESTRATOR)
# ============================================================================

class FlightAnalyzer:
    """
    Main orchestrator: reads images, extracts data, stores to DB.
    """

    SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}

    def __init__(self, image_dir: str = "/mnt/user-data/uploads",
                 db_path: str = str(Path.home() / "flight_database.db")):
        self.image_dir = Path(image_dir)
        self.db = FlightDatabase(db_path)
        self.ocr = FlightRadarOCR()

    def process_all_images(self, max_images: Optional[int] = None):
        """Process every image in image_dir and store OCR results."""
        image_files = sorted([
            p for p in self.image_dir.iterdir()
            if p.suffix.lower() in self.SUPPORTED_EXTENSIONS
        ])

        if max_images:
            image_files = image_files[:max_images]

        total = len(image_files)
        print(f"  Processing {total} images from {self.image_dir}")

        for i, image_path in enumerate(image_files, 1):
            try:
                self._process_single_image(image_path)
            except Exception as e:
                print(f"  [WARN] {image_path.name}: {e}")

            if i % 100 == 0 or i == total:
                print(f"  Progress: {i}/{total} ({i*100//total}%)")

    def _process_single_image(self, image_path: Path):
        # Content-addressed ID: sha256 of file bytes → deduplicates identical images
        try:
            screenshot_id = hashlib.sha256(image_path.read_bytes()).hexdigest()
        except OSError:
            screenshot_id = hashlib.sha256(image_path.name.encode()).hexdigest()

        # Skip already-processed
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM screenshots WHERE screenshot_id = ?", (screenshot_id,))
        already_done = cursor.fetchone() is not None
        conn.close()

        if already_done:
            return

        # Extract data via OCR
        data = self.ocr.extract_from_image(str(image_path))

        # Try to get aircraft position from visual detection
        try:
            from PIL import Image
            img = Image.open(str(image_path))
            w, h = img.size
            mapper = CoordinateMapper(w, h)
            lat, lon = mapper.detect_aircraft_position(str(image_path))
            if lat != 0.0 and lon != 0.0:
                data.latitude = lat
                data.longitude = lon
        except Exception:
            pass

        self.db.store_screenshot(screenshot_id, str(image_path), data)

    def link_screenshots_to_flights(self):
        """Group screenshots by callsign into flight records and store them."""
        callsigns = self.db.get_all_callsigns()
        grouper = FlightGrouper()
        total_flights = 0

        for callsign in callsigns:
            screenshots = self.db.get_screenshots_by_callsign(callsign)
            flights = grouper.group_screenshots(screenshots)

            for flight in flights:
                self.db.store_flight(flight)

            total_flights += len(flights)
            print(f"  {callsign}: {len(flights)} flight(s) from {len(screenshots)} screenshots")

        print(f"\n  Total flights stored: {total_flights}")


if __name__ == "__main__":
    analyzer = FlightAnalyzer()
    analyzer.process_all_images()
    analyzer.link_screenshots_to_flights()
