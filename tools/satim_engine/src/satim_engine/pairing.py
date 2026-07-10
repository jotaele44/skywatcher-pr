from __future__ import annotations
import pandas as pd
from .config import load_config
from .graph import stable_id
from .schema import PAIRING_COLUMNS


def _parse_timestamp(value: object) -> pd.Timestamp | None:
    ts = pd.to_datetime(value, errors="coerce", utc=True)
    return None if pd.isna(ts) else ts


def build_pairing_ledger(tracks: pd.DataFrame, visual_rows: list[dict], config: dict | None = None) -> pd.DataFrame:
    """Match visual files to track files within pairing.time_window_minutes.

    spatial_threshold_meters is not evaluated: visual metadata (see
    plugins/visual_ocr.py) currently carries no latitude/longitude, so
    spatial filtering has no coordinates to work with yet.
    """
    if config is None:
        config = load_config()
    pairing_config = config["pairing"]
    time_window_minutes = pairing_config["time_window_minutes"]
    time_window = pd.Timedelta(minutes=time_window_minutes)
    promote_threshold = pairing_config["confidence_threshold_promote"]

    track_times: dict[str, pd.Series] = {}
    track_confidence: dict[str, float] = {}
    if not tracks.empty and "source" in tracks.columns:
        has_timestamp = "timestamp" in tracks.columns
        for source, group in tracks.groupby("source", dropna=False, sort=True):
            track_file = str(source)
            if has_timestamp:
                parsed = pd.to_datetime(group["timestamp"], errors="coerce", utc=True).dropna()
                if not parsed.empty:
                    track_times[track_file] = parsed
            track_confidence[track_file] = float(group.get("verification_score", pd.Series([0.0])).mean())

    rows: list[dict] = []
    for visual in visual_rows:
        visual_file = str(visual.get("visual_path", ""))
        visual_ts = _parse_timestamp(visual.get("timestamp_hint"))

        if visual_ts is None:
            rows.append({
                "pair_id": stable_id("pair", visual_file, "", "no_timestamp"),
                "track_file": "",
                "visual_file": visual_file,
                "match_basis": "NO_TIMESTAMP_HINT",
                "status": "UNMATCHED",
                "confidence": 0.0,
                "notes": "Visual file has no usable timestamp_hint to match against tracks.",
            })
            continue

        candidates: list[tuple[str, float, float]] = []
        for track_file, timestamps in track_times.items():
            delta = (timestamps - visual_ts).abs().min()
            if delta <= time_window:
                delta_minutes = delta.total_seconds() / 60.0
                time_tightness = max(0.0, 1.0 - (delta_minutes / time_window_minutes))
                track_conf = track_confidence.get(track_file, 0.0) / 100.0
                confidence = round(100 * (0.6 * time_tightness + 0.4 * track_conf), 1)
                candidates.append((track_file, delta_minutes, confidence))

        if not candidates:
            rows.append({
                "pair_id": stable_id("pair", visual_file, "", "no_track_in_window"),
                "track_file": "",
                "visual_file": visual_file,
                "match_basis": "NO_TRACK_IN_WINDOW",
                "status": "UNMATCHED",
                "confidence": 0.0,
                "notes": f"No track source has a point within {time_window_minutes} minutes of the visual timestamp_hint.",
            })
            continue

        for track_file, delta_minutes, conf in sorted(candidates, key=lambda c: (-c[2], c[0])):
            status = "PROMOTED" if conf >= promote_threshold else "CANDIDATE"
            rows.append({
                "pair_id": stable_id("pair", visual_file, track_file),
                "track_file": track_file,
                "visual_file": visual_file,
                "match_basis": "TIMESTAMP_WITHIN_WINDOW",
                "status": status,
                "confidence": conf,
                "notes": (
                    f"Nearest track point is {delta_minutes:.1f} minutes from visual timestamp_hint; "
                    "spatial_threshold_meters not evaluated (visual metadata lacks coordinates)."
                ),
            })

    return pd.DataFrame(rows, columns=PAIRING_COLUMNS)
