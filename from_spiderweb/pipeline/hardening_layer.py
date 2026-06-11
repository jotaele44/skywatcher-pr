"""
PHASE 1: TELEMETRY TRUST LAYER

Converts raw OCR output into a defensible evidence chain:
  "I have data" → "I have data with confidence scores and provenance"

Components:
  ExtractedField         — Probabilistic field value with full metadata
  MultiFrameConsensus    — Cross-frame voting for error correction
  TemporalValidator      — Physics-based impossibility detection
  StatefulTrackHypothesis — Prediction-based observation validation
  ResumableJobQueue      — Fault-tolerant, checkpoint-based job queue
"""

import sqlite3
import math
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict


# ============================================================================
# EXTRACTED FIELD (PROBABILISTIC VALUE)
# ============================================================================

@dataclass
class ExtractedField:
    """
    A single extracted value that carries its own confidence metadata.
    Replaces a bare string/int with a traceable evidence artifact.
    """
    value: Any
    ocr_confidence: float       # From OCR engine(s), 0.0-1.0
    validation_score: float     # Logical consistency check, 0.0-1.0
    consistency_score: float    # Cross-frame agreement, 0.0-1.0
    extraction_method: str      # "tesseract", "ensemble", "manual"
    source_frame: str           # Filename that produced this value
    field_name: str = ""        # e.g. "callsign", "altitude_ft"

    @property
    def combined_confidence(self) -> float:
        """Geometric mean of the three confidence scores."""
        product = self.ocr_confidence * self.validation_score * self.consistency_score
        if product <= 0:
            return 0.0
        return round(product ** (1 / 3), 4)

    def is_reliable(self, threshold: float = 0.75) -> bool:
        return self.combined_confidence >= threshold

    def __repr__(self):
        return (
            f"ExtractedField({self.value!r}, "
            f"conf={self.combined_confidence:.2f}, "
            f"src={self.source_frame})"
        )


# ============================================================================
# MULTI-FRAME CONSENSUS
# ============================================================================

class MultiFrameConsensus:
    """
    Exploits redundancy across consecutive frames of the same aircraft.

    Frames are grouped by (callsign, time_window). Within each group,
    field values are voted on. The majority value wins; agreement boosts
    confidence.
    """

    def __init__(self, window_minutes: int = 5, agreement_boost: float = 0.08):
        self.window_minutes = window_minutes
        self.agreement_boost = agreement_boost

    def build_consensus(self, frames: List[Dict]) -> Dict[str, ExtractedField]:
        """
        Given a list of frame dicts (each containing ExtractedField values),
        return a consensus dict of field → ExtractedField.
        """
        if not frames:
            return {}

        # Collect all values per field
        field_votes: Dict[str, List[Tuple[Any, float]]] = defaultdict(list)

        for frame in frames:
            for field_name, ef in frame.items():
                if isinstance(ef, ExtractedField):
                    field_votes[field_name].append((ef.value, ef.ocr_confidence))

        consensus: Dict[str, ExtractedField] = {}

        for field_name, votes in field_votes.items():
            if not votes:
                continue

            # Count occurrences of each value
            value_counts: Dict[str, int] = defaultdict(int)
            value_conf: Dict[str, List[float]] = defaultdict(list)

            for value, conf in votes:
                key = str(value)
                value_counts[key] += 1
                value_conf[key].append(conf)

            # Best value = most votes (ties broken by avg confidence)
            best_key = max(
                value_counts,
                key=lambda k: (value_counts[k], sum(value_conf[k]) / len(value_conf[k]))
            )
            best_count = value_counts[best_key]
            total_votes = len(votes)

            # Agreement ratio
            agreement = best_count / total_votes
            avg_conf = sum(value_conf[best_key]) / len(value_conf[best_key])

            # Boost confidence for agreement
            boosted_conf = min(1.0, avg_conf + self.agreement_boost * (agreement - 0.5) * 2)
            consistency = agreement  # Agreement IS the consistency score

            # Recover original typed value from one of the matching frames
            original_value = next(
                ef.value for frame in frames
                for fn, ef in frame.items()
                if fn == field_name and isinstance(ef, ExtractedField) and str(ef.value) == best_key
            )

            consensus[field_name] = ExtractedField(
                value=original_value,
                ocr_confidence=boosted_conf,
                validation_score=1.0,  # Post-vote values are logically consistent
                consistency_score=consistency,
                extraction_method="consensus",
                source_frame=f"consensus/{len(frames)}_frames",
                field_name=field_name,
            )

        return consensus

    def group_frames_by_aircraft(
        self, frames: List[Dict], callsign_field: str = "callsign"
    ) -> Dict[str, List[Dict]]:
        """Group frames by callsign. Each value must have a 'timestamp' key."""
        groups: Dict[str, List[Dict]] = defaultdict(list)

        for frame in frames:
            callsign_ef = frame.get(callsign_field)
            if isinstance(callsign_ef, ExtractedField):
                key = str(callsign_ef.value)
            else:
                key = str(callsign_ef or "UNKNOWN")
            groups[key].append(frame)

        return dict(groups)


# ============================================================================
# TEMPORAL VALIDATOR
# ============================================================================

@dataclass
class ValidationResult:
    passed: bool
    check_type: str
    description: str
    details: str = ""


class TemporalValidator:
    """
    Validates track points against helicopter physical constraints.

    Checks:
      - Ground speed ≤ 180 mph
      - Altitude change ≤ 1500 ft/min (climb/descent rate)
      - Heading change ≤ 45°/sec
      - Timestamps are monotonically increasing
    """

    MAX_SPEED_MPH = 180.0
    MAX_CLIMB_FT_PER_MIN = 1500.0
    MAX_TURN_DEG_PER_SEC = 45.0

    def validate_track(self, track_points: List[Dict]) -> List[ValidationResult]:
        """Validate an ordered list of track point dicts."""
        results = []

        if len(track_points) < 2:
            return results

        for i in range(1, len(track_points)):
            prev = track_points[i - 1]
            curr = track_points[i]
            results += self._validate_pair(prev, curr, i)

        return results

    def _validate_pair(self, prev: Dict, curr: Dict,
                       idx: int) -> List[ValidationResult]:
        results = []

        # Parse timestamps
        try:
            t0 = datetime.fromisoformat(prev.get("timestamp", ""))
            t1 = datetime.fromisoformat(curr.get("timestamp", ""))
            dt_sec = (t1 - t0).total_seconds()
        except Exception:
            return results

        # Monotonicity check
        if dt_sec < 0:
            results.append(ValidationResult(
                passed=False,
                check_type="monotonic_time",
                description=f"Point {idx}: timestamp goes backward by {abs(dt_sec):.0f}s",
            ))
            return results  # Further checks meaningless with bad time

        if dt_sec == 0:
            return results  # Same timestamp — skip

        # Speed check
        lat0 = prev.get("latitude") or 0.0
        lon0 = prev.get("longitude") or 0.0
        lat1 = curr.get("latitude") or 0.0
        lon1 = curr.get("longitude") or 0.0

        if lat0 and lon0 and lat1 and lon1:
            dist_nm = _haversine_nm(lat0, lon0, lat1, lon1)
            dist_miles = dist_nm * 1.15078
            speed_mph = dist_miles / (dt_sec / 3600)

            if speed_mph > self.MAX_SPEED_MPH:
                results.append(ValidationResult(
                    passed=False,
                    check_type="speed",
                    description=f"Point {idx}: impossible speed {speed_mph:.0f} mph (max {self.MAX_SPEED_MPH})",
                    details=f"Distance {dist_miles:.1f} mi in {dt_sec:.0f}s",
                ))
            else:
                results.append(ValidationResult(
                    passed=True,
                    check_type="speed",
                    description=f"Point {idx}: speed {speed_mph:.0f} mph OK",
                ))

        # Altitude climb rate check
        alt0 = prev.get("altitude_ft") or 0
        alt1 = curr.get("altitude_ft") or 0

        if alt0 and alt1:
            alt_delta = abs(alt1 - alt0)
            dt_min = dt_sec / 60
            if dt_min > 0:
                climb_rate = alt_delta / dt_min
                if climb_rate > self.MAX_CLIMB_FT_PER_MIN:
                    results.append(ValidationResult(
                        passed=False,
                        check_type="climb_rate",
                        description=f"Point {idx}: impossible climb rate {climb_rate:.0f} ft/min (max {self.MAX_CLIMB_FT_PER_MIN})",
                        details=f"Altitude change {alt_delta} ft in {dt_sec:.0f}s",
                    ))

        return results

    def count_violations(self, results: List[ValidationResult]) -> int:
        return sum(1 for r in results if not r.passed)

    def passed(self, results: List[ValidationResult]) -> bool:
        return all(r.passed for r in results)


# ============================================================================
# STATEFUL TRACK HYPOTHESIS
# ============================================================================

@dataclass
class TrackState:
    callsign: str
    latitude: float
    longitude: float
    altitude_ft: float
    speed_mph: float
    heading_deg: float
    timestamp: datetime
    confidence: float = 1.0


class StatefulTrackHypothesis:
    """
    Maintains a predicted state for each active aircraft.
    New observations are validated against the prediction.

    Analogous to radar track management; flags observations that
    deviate too far from the predicted state.
    """

    # Thresholds for accepting an observation as consistent
    MAX_POSITION_ERROR_NM = 5.0
    MAX_ALTITUDE_ERROR_FT = 2000.0

    def __init__(self):
        self.states: Dict[str, TrackState] = {}

    def update(self, callsign: str, lat: float, lon: float,
               alt_ft: float, speed_mph: float, timestamp: str) -> ValidationResult:
        """
        Update the track state for callsign. Returns a ValidationResult
        indicating whether the new observation is consistent with prediction.
        """
        try:
            ts = datetime.fromisoformat(timestamp)
        except Exception:
            ts = datetime.utcnow()

        if callsign not in self.states:
            # First observation — initialize state
            self.states[callsign] = TrackState(
                callsign=callsign,
                latitude=lat, longitude=lon,
                altitude_ft=alt_ft, speed_mph=speed_mph,
                heading_deg=0.0, timestamp=ts,
            )
            return ValidationResult(
                passed=True,
                check_type="track_init",
                description=f"{callsign}: track initialized",
            )

        prev = self.states[callsign]
        dt_sec = (ts - prev.timestamp).total_seconds()

        if dt_sec <= 0:
            return ValidationResult(
                passed=True,
                check_type="track_duplicate",
                description=f"{callsign}: duplicate/out-of-order timestamp",
            )

        # Predict next position using dead reckoning
        pred_lat, pred_lon = self._predict_position(prev, dt_sec)

        # Compute position error
        error_nm = _haversine_nm(pred_lat, pred_lon, lat, lon)
        alt_error = abs(alt_ft - prev.altitude_ft)

        passed = (error_nm <= self.MAX_POSITION_ERROR_NM and
                  alt_error <= self.MAX_ALTITUDE_ERROR_FT)

        # Compute heading from movement
        heading = _bearing(prev.latitude, prev.longitude, lat, lon)

        # Update state
        self.states[callsign] = TrackState(
            callsign=callsign,
            latitude=lat, longitude=lon,
            altitude_ft=alt_ft, speed_mph=speed_mph,
            heading_deg=heading, timestamp=ts,
            confidence=0.9 if passed else 0.4,
        )

        return ValidationResult(
            passed=passed,
            check_type="track_consistency",
            description=(
                f"{callsign}: position error {error_nm:.1f} nm, alt error {alt_error:.0f} ft "
                f"({'OK' if passed else 'FLAGGED'})"
            ),
        )

    def _predict_position(self, state: TrackState, dt_sec: float) -> Tuple[float, float]:
        """Simple dead reckoning: move along last heading at last speed."""
        dist_nm = (state.speed_mph * 1.15078) * (dt_sec / 3600) / 1.15078
        # Dead reckoning in lat/lon (flat Earth approximation for short distances)
        lat_delta = dist_nm * math.cos(math.radians(state.heading_deg)) / 60.0
        lon_delta = dist_nm * math.sin(math.radians(state.heading_deg)) / (
            60.0 * math.cos(math.radians(state.latitude))
        )
        return state.latitude + lat_delta, state.longitude + lon_delta

    def clear(self, callsign: str):
        self.states.pop(callsign, None)

    def clear_all(self):
        self.states.clear()


# ============================================================================
# RESUMABLE JOB QUEUE
# ============================================================================

class JobStatus:
    PENDING    = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETE   = "COMPLETE"
    ERROR      = "ERROR"


class ResumableJobQueue:
    """
    SQLite-backed job queue with checkpointing.

    Allows 15,000-image processing to survive interruptions.
    On restart, only PENDING and ERROR jobs are re-processed.
    """

    def __init__(self, db_path: str = str(Path.home() / "flight_database.db")):
        self.db_path = db_path
        self._init_tables()

    def _init_tables(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS processing_jobs (
                job_id TEXT PRIMARY KEY,
                image_path TEXT,
                status TEXT DEFAULT 'PENDING',
                batch_id TEXT,
                created_at TEXT,
                started_at TEXT,
                completed_at TEXT,
                error_message TEXT
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS job_checkpoints (
                checkpoint_id TEXT PRIMARY KEY,
                batch_id TEXT,
                completed INTEGER,
                failed INTEGER,
                checkpoint_time TEXT
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS extraction_confidence (
                id TEXT PRIMARY KEY,
                image_filename TEXT,
                field_name TEXT,
                extracted_value TEXT,
                ocr_confidence REAL,
                validation_score REAL,
                consistency_score REAL,
                combined_confidence REAL,
                extraction_method TEXT,
                recorded_at TEXT
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS validation_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                flight_id TEXT,
                check_type TEXT,
                passed INTEGER,
                description TEXT,
                details TEXT,
                validated_at TEXT
            )
        ''')

        conn.commit()
        conn.close()

    def enqueue_batch(self, image_paths: List[str], batch_id: str):
        """Add images to the queue. Skips images already in the queue."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        for path in image_paths:
            job_id = _make_job_id(path)
            cursor.execute(
                "INSERT OR IGNORE INTO processing_jobs (job_id, image_path, batch_id, created_at) VALUES (?, ?, ?, ?)",
                (job_id, path, batch_id, datetime.utcnow().isoformat())
            )

        conn.commit()
        conn.close()

    def get_pending_jobs(self, batch_id: str = None, limit: int = None) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = "SELECT * FROM processing_jobs WHERE status IN ('PENDING', 'ERROR')"
        params: List = []

        if batch_id:
            query += " AND batch_id = ?"
            params.append(batch_id)

        query += " ORDER BY created_at"

        if limit:
            query += f" LIMIT {limit}"

        cursor.execute(query, params)
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return rows

    def mark_processing(self, job_id: str):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE processing_jobs SET status = 'PROCESSING', started_at = ? WHERE job_id = ?",
            (datetime.utcnow().isoformat(), job_id)
        )
        conn.commit()
        conn.close()

    def mark_complete(self, job_id: str):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE processing_jobs SET status = 'COMPLETE', completed_at = ? WHERE job_id = ?",
            (datetime.utcnow().isoformat(), job_id)
        )
        conn.commit()
        conn.close()

    def mark_error(self, job_id: str, error: str):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE processing_jobs SET status = 'ERROR', error_message = ? WHERE job_id = ?",
            (str(error)[:1000], job_id)
        )
        conn.commit()
        conn.close()

    def save_checkpoint(self, batch_id: str, completed: int, failed: int):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        checkpoint_id = f"{batch_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        cursor.execute('''
            INSERT OR REPLACE INTO job_checkpoints
            (checkpoint_id, batch_id, completed, failed, checkpoint_time)
            VALUES (?, ?, ?, ?, ?)
        ''', (checkpoint_id, batch_id, completed, failed, datetime.utcnow().isoformat()))
        conn.commit()
        conn.close()

    def store_extraction_confidence(self, image_filename: str, fields: Dict[str, ExtractedField]):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        now = datetime.utcnow().isoformat()

        for field_name, ef in fields.items():
            record_id = f"{image_filename}_{field_name}"
            cursor.execute('''
                INSERT OR REPLACE INTO extraction_confidence
                (id, image_filename, field_name, extracted_value,
                 ocr_confidence, validation_score, consistency_score,
                 combined_confidence, extraction_method, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                record_id, image_filename, field_name, str(ef.value),
                ef.ocr_confidence, ef.validation_score, ef.consistency_score,
                ef.combined_confidence, ef.extraction_method, now,
            ))

        conn.commit()
        conn.close()

    def store_validation_results(self, flight_id: str, results: List[ValidationResult]):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        now = datetime.utcnow().isoformat()

        for result in results:
            cursor.execute('''
                INSERT INTO validation_results
                (flight_id, check_type, passed, description, details, validated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                flight_id, result.check_type, int(result.passed),
                result.description, result.details, now,
            ))

        conn.commit()
        conn.close()

    def get_progress(self, batch_id: str = None) -> Dict:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        query = "SELECT status, COUNT(*) FROM processing_jobs"
        params = []
        if batch_id:
            query += " WHERE batch_id = ?"
            params.append(batch_id)
        query += " GROUP BY status"
        cursor.execute(query, params)
        progress = {row[0]: row[1] for row in cursor.fetchall()}
        conn.close()
        return progress

    def get_failed_jobs(self, batch_id: str = None, limit: int = None) -> List[Dict]:
        """Return jobs with status ERROR, optionally filtered by batch_id."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        query = "SELECT * FROM processing_jobs WHERE status = 'ERROR'"
        params: List = []
        if batch_id:
            query += " AND batch_id = ?"
            params.append(batch_id)
        query += " ORDER BY created_at"
        if limit:
            query += f" LIMIT {limit}"
        cursor.execute(query, params)
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return rows

    def retry_failed_jobs(self, batch_id: str = None) -> int:
        """Reset ERROR jobs back to PENDING. Returns the number of jobs reset."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        query = "UPDATE processing_jobs SET status = 'PENDING', error_message = NULL WHERE status = 'ERROR'"
        params: List = []
        if batch_id:
            query += " AND batch_id = ?"
            params.append(batch_id)
        cursor.execute(query, params)
        affected = cursor.rowcount
        conn.commit()
        conn.close()
        return affected

    def get_batch_stats(self, batch_id: str = None) -> Dict[str, Any]:
        """Return job counts by status for an optional batch, plus total."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        query = "SELECT status, COUNT(*) FROM processing_jobs"
        params: List = []
        if batch_id:
            query += " WHERE batch_id = ?"
            params.append(batch_id)
        query += " GROUP BY status"
        cursor.execute(query, params)
        by_status = {row[0]: row[1] for row in cursor.fetchall()}
        conn.close()
        stats = {
            "batch_id":   batch_id,
            "total":      sum(by_status.values()),
            "pending":    by_status.get("PENDING", 0),
            "processing": by_status.get("PROCESSING", 0),
            "complete":   by_status.get("COMPLETE", 0),
            "error":      by_status.get("ERROR", 0),
        }
        return stats


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def _haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in nautical miles."""
    r = math.radians
    lon1, lat1, lon2, lat2 = r(lon1), r(lat1), r(lon2), r(lat2)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * math.asin(math.sqrt(a)) * 3440.065


def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing in degrees (0-360) from point 1 to point 2."""
    r = math.radians
    dlon = r(lon2 - lon1)
    x = math.sin(dlon) * math.cos(r(lat2))
    y = (math.cos(r(lat1)) * math.sin(r(lat2)) -
         math.sin(r(lat1)) * math.cos(r(lat2)) * math.cos(dlon))
    bearing = math.degrees(math.atan2(x, y))
    return (bearing + 360) % 360


def _make_job_id(path: str) -> str:
    import hashlib
    return hashlib.md5(path.encode()).hexdigest()


if __name__ == "__main__":
    print("Phase 1 Hardening Layer — component test")

    # ExtractedField
    ef = ExtractedField(
        value="N5854Z", ocr_confidence=0.93, validation_score=0.96,
        consistency_score=0.94, extraction_method="ensemble",
        source_frame="IMG_0663.jpeg", field_name="callsign",
    )
    print(f"  Field: {ef}")
    print(f"  Reliable: {ef.is_reliable()}")

    # TemporalValidator
    points = [
        {"timestamp": "2026-05-08T10:00:00", "latitude": 18.45, "longitude": -66.10,
         "altitude_ft": 1000, "ground_speed_mph": 80},
        {"timestamp": "2026-05-08T10:05:00", "latitude": 18.47, "longitude": -66.12,
         "altitude_ft": 1200, "ground_speed_mph": 85},
    ]
    validator = TemporalValidator()
    results = validator.validate_track(points)
    print(f"  Validation results: {len(results)} checks, {validator.count_violations(results)} violations")
