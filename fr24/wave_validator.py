"""
FR24 WAVE PHYSICS VALIDATOR

Validates temporal and physical coherence within each multi-obs temporal wave.
For each wave with ≥2 observations the validator applies three checks to
consecutive (timestamp-sorted) observation pairs:

  1. Monotonic timestamps   — t[i] must not precede t[i-1]
  2. Altitude climb rate    — |Δalt| / Δt_min ≤ 1500 ft/min
  3. Speed plausibility     — 0 ≤ ground_speed_mph ≤ 180

Thresholds are taken from TemporalValidator in hardening_layer.py (MAX_SPEED_MPH,
MAX_CLIMB_FT_PER_MIN). Haversine speed is skipped because lat/lon are not
available from OCR; only the OCR-extracted ground_speed_mph field is range-checked.

Outputs remain candidate records. No event is confirmed by this layer.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

VALIDATOR_VERSION = "fr24_wave_validator_v0.1.0"

# Thresholds from hardening_layer.TemporalValidator
MAX_SPEED_MPH = 180.0
MAX_CLIMB_FT_PER_MIN = 1500.0

PROHIBITED_LABELS = {
    "confirmed",
    "confirmed_aircraft_event",
    "confirmed_anomaly",
    "confirmed_route",
    "verified_event",
    "validated_aircraft_event",
}


# ── helpers ────────────────────────────────────────────────────────────────────

def _as_float(value: object) -> Optional[float]:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _parse_iso(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


# ── physics checks ─────────────────────────────────────────────────────────────

def _check_pair(
    prev: dict,
    curr: dict,
    pair_idx: int,
) -> Tuple[List[str], int]:
    """
    Return (violations, checks_run) for one consecutive observation pair.

    violations: list of human-readable violation strings
    checks_run: number of checks attempted on this pair
    """
    violations: List[str] = []
    checks_run = 0

    # Timestamp monotonicity
    t0 = _parse_iso(prev.get("vector_playback_iso", ""))
    t1 = _parse_iso(curr.get("vector_playback_iso", ""))
    if t0 is not None and t1 is not None:
        checks_run += 1
        dt_sec = (t1 - t0).total_seconds()
        if dt_sec < 0:
            violations.append(
                f"pair{pair_idx}:non_monotonic_timestamp({abs(dt_sec):.0f}s backward)"
            )
        else:
            # Altitude climb rate (only meaningful with a positive time delta)
            alt0 = _as_float(prev.get("barometric_altitude_ft"))
            alt1 = _as_float(curr.get("barometric_altitude_ft"))
            if alt0 is not None and alt1 is not None and dt_sec > 0:
                checks_run += 1
                dt_min = dt_sec / 60.0
                climb_rate = abs(alt1 - alt0) / dt_min
                if climb_rate > MAX_CLIMB_FT_PER_MIN:
                    violations.append(
                        f"pair{pair_idx}:climb_rate_exceeded"
                        f"({climb_rate:.0f}ft/min>max{MAX_CLIMB_FT_PER_MIN:.0f})"
                    )

    # Speed plausibility (each observation independently)
    for obs_label, obs in (("prev", prev), ("curr", curr)):
        speed = _as_float(obs.get("ground_speed_mph"))
        if speed is not None:
            checks_run += 1
            if speed < 0 or speed > MAX_SPEED_MPH:
                violations.append(
                    f"pair{pair_idx}:{obs_label}:speed_out_of_range"
                    f"({speed:.0f}mph)"
                )

    return violations, checks_run


def _sort_obs(obs_list: List[dict]) -> List[dict]:
    """Sort observations: parsed timestamps first (ascending), unparsed last."""
    return sorted(
        obs_list,
        key=lambda r: (
            0 if r.get("vector_playback_iso") else 1,
            r.get("vector_playback_iso") or "",
            r.get("image_name") or "",
        ),
    )


def validate_wave(wave: dict, obs_list: List[dict]) -> dict:
    """Enrich one wave row with physics check results."""
    out = dict(wave)

    sorted_obs = _sort_obs(obs_list)
    n = len(sorted_obs)

    all_violations: List[str] = []
    total_checks = 0
    obs_with_data = sum(
        1 for o in sorted_obs
        if o.get("vector_playback_iso") or _as_float(o.get("barometric_altitude_ft")) is not None
    )

    if n >= 2:
        for i in range(1, n):
            violations, checks = _check_pair(sorted_obs[i - 1], sorted_obs[i], i)
            all_violations.extend(violations)
            total_checks += checks

    out["physics_check_passed"] = 0 if all_violations else 1
    out["physics_violation_count"] = len(all_violations)
    out["physics_violation_details"] = ";".join(all_violations)
    out["physics_checks_run"] = total_checks
    out["physics_obs_with_data"] = obs_with_data
    out["validator_confirmation_status"] = "not_confirmed"
    out["validator_version"] = VALIDATOR_VERSION

    return out


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

def run(vectors_csv: Path, waves_csv: Path, output_dir: Path) -> dict:
    obs_rows = read_csv(vectors_csv)
    wave_rows = read_csv(waves_csv)

    # Index observations by aircraft identity
    obs_by_identity: Dict[str, List[dict]] = defaultdict(list)
    for row in obs_rows:
        identity = (row.get("vector_aircraft_identity") or "").strip()
        if identity:
            obs_by_identity[identity].append(row)

    # Validate each wave
    validated: List[dict] = []
    check_counter: Counter = Counter()
    for wave in wave_rows:
        identity = (wave.get("wave_aircraft_identity") or "").strip()
        obs = obs_by_identity.get(identity, [])
        result = validate_wave(wave, obs)
        validated.append(result)
        check_counter["total_waves"] += 1
        if result["physics_check_passed"]:
            check_counter["passed"] += 1
        else:
            check_counter["failed"] += 1

    review_queue = [r for r in validated if not r["physics_check_passed"]]
    review_queue.sort(key=lambda r: -int(r.get("physics_violation_count") or 0))

    output_dir.mkdir(parents=True, exist_ok=True)
    report_csv = output_dir / "fr24_wave_physics_report.csv"
    review_csv = output_dir / "fr24_wave_physics_review_queue.csv"
    summary_json = output_dir / "fr24_wave_validator_summary.json"

    write_csv(report_csv, validated)
    write_csv(review_csv, review_queue)

    summary = {
        "vectors_csv": str(vectors_csv),
        "waves_csv": str(waves_csv),
        "wave_count": len(validated),
        "violation_count": int(check_counter["failed"]),
        "passed_count": int(check_counter["passed"]),
        "check_breakdown": {
            "max_speed_mph": MAX_SPEED_MPH,
            "max_climb_ft_per_min": MAX_CLIMB_FT_PER_MIN,
            "checks": ["monotonic_timestamp", "altitude_climb_rate", "speed_plausibility"],
        },
        "outputs": {
            "report_csv": str(report_csv),
            "review_csv": str(review_csv),
            "summary_json": str(summary_json),
        },
        "validator_version": VALIDATOR_VERSION,
        "policy": "candidate_only_no_auto_confirmation",
    }
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate temporal wave physics coherence")
    parser.add_argument(
        "--vectors-csv",
        default="data/_manifests/fr24_audit/fr24_ocr_analysis_vectors.csv",
    )
    parser.add_argument(
        "--waves-csv",
        default="data/_manifests/fr24_audit/fr24_temporal_waves.csv",
    )
    parser.add_argument(
        "--output-dir",
        default="data/_manifests/fr24_audit",
    )
    args = parser.parse_args()
    print(json.dumps(run(Path(args.vectors_csv), Path(args.waves_csv), Path(args.output_dir)), indent=2))


if __name__ == "__main__":
    main()
