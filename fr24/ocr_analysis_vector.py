"""
FR24 OCR ANALYSIS VECTOR

Computes a per-candidate analysis vector from FR24 field-selected OCR rows and
groups observations by aircraft identity into temporal waves.

This is the temporal-wave building block: each screenshot gets a named
multi-dimensional feature vector (field presence, confidence, conflict signals,
temporal parse quality). Waves then group same-aircraft observations ordered by
playback timestamp.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

VECTOR_VERSION = "fr24_ocr_analysis_vector_v0.1.0"

SELECT_FIELDS = [
    "callsign_or_label",
    "operator",
    "aircraft_type",
    "registration",
    "origin_code",
    "destination_code",
    "barometric_altitude_ft",
    "ground_speed_mph",
    "flight_status",
    "elapsed_departed",
    "elapsed_arrived",
    "playback_date",
    "playback_time",
    "playback_timezone",
]

# Maps SELECT_FIELDS entry → binary vector column name
FIELD_VECTOR_MAP: Dict[str, str] = {
    "callsign_or_label": "vector_has_callsign",
    "operator": "vector_has_operator",
    "aircraft_type": "vector_has_aircraft_type",
    "registration": "vector_has_registration",
    "origin_code": "vector_has_origin",
    "destination_code": "vector_has_destination",
    "barometric_altitude_ft": "vector_has_altitude",
    "ground_speed_mph": "vector_has_speed",
    "flight_status": "vector_has_flight_status",
    "elapsed_departed": "vector_has_elapsed_departed",
    "elapsed_arrived": "vector_has_elapsed_arrived",
    "playback_date": "vector_has_playback_date",
    "playback_time": "vector_has_playback_time",
    "playback_timezone": "vector_has_playback_tz",
}

PROHIBITED_LABELS = {
    "confirmed",
    "confirmed_aircraft_event",
    "confirmed_anomaly",
    "confirmed_route",
    "verified_event",
    "validated_aircraft_event",
}

# Ordered date / time strptime patterns to try
_DATE_FMTS = (
    "%a, %b %d, %Y",   # Mon, May 23, 2026
    "%b %d, %Y",        # May 23, 2026
    "%Y-%m-%d",         # ISO date
)
_TIME_FMTS = (
    "%I:%M %p",         # 10:30 AM
    "%H:%M",            # 10:30
    "%H:%M:%S",         # 10:30:00
)


# ── helpers ────────────────────────────────────────────────────────────────────

def _as_float(value: object) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _as_int(value: object) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _parse_playback_dt(row: dict) -> Optional[datetime]:
    date_str = (row.get("playback_date") or "").strip()
    time_str = (row.get("playback_time") or "").strip()
    if not date_str:
        return None

    if time_str:
        for dfmt in _DATE_FMTS:
            for tfmt in _TIME_FMTS:
                try:
                    return datetime.strptime(f"{date_str} {time_str}", f"{dfmt} {tfmt}")
                except ValueError:
                    pass

    for dfmt in _DATE_FMTS:
        try:
            return datetime.strptime(date_str, dfmt)
        except ValueError:
            pass

    return None


def _aircraft_identity(row: dict) -> str:
    reg = (row.get("registration") or "").strip()
    if reg:
        return reg
    callsign = (row.get("callsign_or_label") or "").strip()
    if callsign:
        return callsign
    return (row.get("image_name") or row.get("image_path") or "unknown").strip()


def _quality_tier(coverage: float, conflict_count: int, has_disagreements: int) -> int:
    if coverage >= 0.70 and conflict_count == 0 and not has_disagreements:
        return 1
    if coverage >= 0.40 and conflict_count <= 2:
        return 2
    if coverage >= 0.15:
        return 3
    return 4


# ── vector computation ─────────────────────────────────────────────────────────

def compute_vector(row: dict) -> dict:
    """Return a dict of vector columns for one candidate row."""
    vec: dict = {}

    # Field presence (binary 0/1) and coverage count
    populated = 0
    for field, vec_key in FIELD_VECTOR_MAP.items():
        present = 1 if (row.get(field) or "").strip() else 0
        vec[vec_key] = present
        populated += present

    total = len(SELECT_FIELDS)
    vec["vector_field_coverage"] = round(populated / total, 4) if total else 0.0

    # Confidence
    wc = round(_as_float(row.get("whole_confidence")), 4)
    rc = round(_as_float(row.get("region_confidence")), 4)
    vec["vector_whole_confidence"] = wc
    vec["vector_region_confidence"] = rc
    vec["vector_max_confidence"] = round(max(wc, rc), 4)

    # Conflict signals
    conflict_count = _as_int(row.get("conflict_count"))
    vec["vector_conflict_count"] = conflict_count
    vec["vector_conflict_normalized"] = round(min(conflict_count / total, 1.0), 4) if total else 0.0
    vec["vector_has_disagreements"] = 1 if (row.get("selected_field_disagreements") or "").strip() else 0

    # Temporal
    dt = _parse_playback_dt(row)
    vec["vector_temporal_parsed"] = 1 if dt else 0
    vec["vector_playback_iso"] = dt.isoformat() if dt else ""

    # Aircraft identity (registration > callsign > image name)
    vec["vector_aircraft_identity"] = _aircraft_identity(row)

    # Quality tier
    vec["vector_quality_tier"] = _quality_tier(
        vec["vector_field_coverage"],
        conflict_count,
        vec["vector_has_disagreements"],
    )

    # Policy label
    vec["vector_confirmation_status"] = "not_confirmed"
    vec["vector_version"] = VECTOR_VERSION

    return vec


# ── wave grouping ──────────────────────────────────────────────────────────────

def _avg(values: List[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def _duration_minutes(earliest: str, latest: str) -> float:
    if not earliest or not latest or earliest == latest:
        return 0.0
    try:
        t0 = datetime.fromisoformat(earliest)
        t1 = datetime.fromisoformat(latest)
        return round((t1 - t0).total_seconds() / 60.0, 2)
    except Exception:
        return 0.0


def _wave_sort_key(row: dict) -> Tuple:
    has_ts = 0 if row.get("vector_playback_iso") else 1
    return (has_ts, row.get("vector_playback_iso") or "", row.get("image_name") or "")


def build_waves(vectored_rows: List[dict]) -> List[dict]:
    """Group vectored rows by aircraft identity and produce one wave per group."""
    groups: Dict[str, List[dict]] = defaultdict(list)
    for row in vectored_rows:
        groups[row.get("vector_aircraft_identity", "unknown")].append(row)

    waves: List[dict] = []
    for wave_idx, (identity, obs) in enumerate(sorted(groups.items()), 1):
        sorted_obs = sorted(obs, key=_wave_sort_key)
        iso_values = [r["vector_playback_iso"] for r in sorted_obs if r.get("vector_playback_iso")]
        earliest = iso_values[0] if iso_values else ""
        latest = iso_values[-1] if iso_values else ""

        waves.append({
            "wave_id": f"wave_{wave_idx:06d}",
            "wave_aircraft_identity": identity,
            "wave_obs_count": len(sorted_obs),
            "wave_earliest_iso": earliest,
            "wave_latest_iso": latest,
            "wave_duration_minutes": _duration_minutes(earliest, latest),
            "wave_avg_field_coverage": _avg([_as_float(r.get("vector_field_coverage")) for r in sorted_obs]),
            "wave_avg_confidence": _avg([_as_float(r.get("vector_max_confidence")) for r in sorted_obs]),
            "wave_temporal_coherence": 1 if all(r.get("vector_temporal_parsed") for r in sorted_obs) else 0,
            "wave_confirmation_status": "not_confirmed",
            "wave_version": VECTOR_VERSION,
        })

    return waves


# ── IO ─────────────────────────────────────────────────────────────────────────

def read_csv(path: Path) -> List[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    return list(csv.DictReader(path.open(encoding="utf-8")))


def write_csv(path: Path, rows: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


# ── pipeline entry ─────────────────────────────────────────────────────────────

def run(input_csv: Path, output_dir: Path) -> dict:
    rows = read_csv(input_csv)

    vectored: List[dict] = []
    tier_counter: Counter = Counter()
    for row in rows:
        merged = dict(row)
        merged.update(compute_vector(row))
        vectored.append(merged)
        tier_counter[merged["vector_quality_tier"]] += 1

    waves = build_waves(vectored)
    multi_obs = sum(1 for w in waves if w["wave_obs_count"] >= 2)

    output_dir.mkdir(parents=True, exist_ok=True)
    vectors_csv = output_dir / "fr24_ocr_analysis_vectors.csv"
    waves_csv = output_dir / "fr24_temporal_waves.csv"
    summary_json = output_dir / "fr24_analysis_vector_summary.json"

    write_csv(vectors_csv, vectored)
    write_csv(waves_csv, waves)

    summary = {
        "input_csv": str(input_csv),
        "candidate_count": len(vectored),
        "wave_count": len(waves),
        "multi_obs_wave_count": multi_obs,
        "tier_distribution": {str(k): v for k, v in sorted(tier_counter.items())},
        "outputs": {
            "vectors_csv": str(vectors_csv),
            "waves_csv": str(waves_csv),
            "summary_json": str(summary_json),
        },
        "vector_version": VECTOR_VERSION,
        "policy": "candidate_only_no_auto_confirmation",
    }
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute FR24 OCR analysis vectors and temporal waves")
    parser.add_argument(
        "--input-csv",
        default="data/_manifests/fr24_audit/fr24_event_candidates_selected.csv",
    )
    parser.add_argument(
        "--output-dir",
        default="data/_manifests/fr24_audit",
    )
    args = parser.parse_args()
    print(json.dumps(run(Path(args.input_csv), Path(args.output_dir)), indent=2))


if __name__ == "__main__":
    main()
