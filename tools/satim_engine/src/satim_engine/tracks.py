from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd

LAT_NAMES = ["lat", "latitude", "y", "gps_lat", "position_lat"]
LON_NAMES = ["lon", "lng", "longitude", "x", "gps_lon", "position_lon"]
TIME_NAMES = ["timestamp", "time", "datetime", "date", "utc", "seen", "created_at"]
ALT_NAMES = ["alt", "altitude", "altitude_ft", "baro_altitude", "geo_altitude"]
SPD_NAMES = ["speed", "groundspeed", "gs", "speed_mph", "velocity", "ground_speed"]
HEADING_NAMES = ["heading", "track", "bearing", "course", "direction"]
POSITION_NAMES = ["position", "coordinates", "coordinate", "lat_lon", "latlon"]
SEGMENT_START_LAT_NAMES = ["start_lat", "start_latitude"]
SEGMENT_START_LON_NAMES = ["start_lon", "start_lng", "start_longitude"]
SEGMENT_END_LAT_NAMES = ["end_lat", "end_latitude"]
SEGMENT_END_LON_NAMES = ["end_lon", "end_lng", "end_longitude"]

_HEADER_SCAN_ROWS = 500
_POSITION_RE = re.compile(
    r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*,\s*"
    r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*$"
)


class NonTrackCSV(ValueError):
    """Raised when a CSV is valid but does not contain track coordinates."""


def _norm(value: object) -> str:
    return str(value).strip().lower().replace(" ", "_")


def _find(cols, names):
    low = {_norm(c): c for c in cols}
    for n in names:
        if n in low:
            return low[n]
    return None


def _header_candidate(line: str) -> bool:
    tokens = [_norm(part.strip().strip('"').strip("'")) for part in re.split(r"[,;\t|]", line)]
    names = set(tokens)
    has_split = bool(names.intersection(LAT_NAMES)) and bool(names.intersection(LON_NAMES))
    has_position = bool(names.intersection(POSITION_NAMES))
    has_segment = (
        bool(names.intersection(SEGMENT_START_LAT_NAMES))
        and bool(names.intersection(SEGMENT_START_LON_NAMES))
        and bool(names.intersection(SEGMENT_END_LAT_NAMES))
        and bool(names.intersection(SEGMENT_END_LON_NAMES))
    )
    return has_split or has_position or has_segment


def _read_csv_robust(path: str) -> pd.DataFrame:
    last = None
    for enc in ["utf-8-sig", "utf-8", "cp1252", "latin1"]:
        try:
            with open(path, "r", encoding=enc, errors="strict", newline="") as fh:
                header_row = None
                for idx, line in enumerate(fh):
                    if idx >= _HEADER_SCAN_ROWS:
                        break
                    if _header_candidate(line):
                        header_row = idx
                        break
            if header_row is None:
                raise NonTrackCSV(
                    f"CSV schema unresolved: no coordinate-bearing header found in first "
                    f"{_HEADER_SCAN_ROWS} rows of {path}"
                )
            return pd.read_csv(
                path,
                encoding=enc,
                skiprows=header_row,
                sep=None,
                engine="python",
                low_memory=False,
            )
        except NonTrackCSV:
            raise
        except Exception as e:
            last = e
    raise last


def _base_output(df: pd.DataFrame, latitude, longitude, path: str) -> pd.DataFrame:
    out = pd.DataFrame(
        {
            "latitude": pd.to_numeric(latitude, errors="coerce"),
            "longitude": pd.to_numeric(longitude, errors="coerce"),
        }
    )
    t = _find(df.columns, TIME_NAMES)
    out["timestamp"] = pd.to_datetime(df[t], errors="coerce", utc=True) if t else pd.NaT
    alt = _find(df.columns, ALT_NAMES)
    spd = _find(df.columns, SPD_NAMES)
    hdg = _find(df.columns, HEADING_NAMES)
    out["altitude"] = pd.to_numeric(df[alt], errors="coerce") if alt else pd.NA
    out["speed"] = pd.to_numeric(df[spd], errors="coerce") if spd else pd.NA
    for c in ["callsign", "registration", "aircraft_type"]:
        src = _find(df.columns, [c, c.replace("_", "")])
        out[c] = df[src] if src else pd.NA
    out["heading"] = pd.to_numeric(df[hdg], errors="coerce") if hdg else pd.NA
    out["source"] = str(path)
    return out


def _finalize_track(out: pd.DataFrame, path: str) -> pd.DataFrame:
    out = out.dropna(subset=["latitude", "longitude"])
    out = out[
        (out.latitude.between(-90, 90))
        & (out.longitude.between(-180, 180))
    ]
    if out.empty:
        raise NonTrackCSV(f"Empty track: no valid coordinate rows in {path}")
    return out


def _parse_position_series(series: pd.Series) -> tuple[pd.Series, pd.Series]:
    extracted = series.astype("string").str.extract(_POSITION_RE)
    return extracted[0], extracted[1]


def _parse_segment_table(df: pd.DataFrame, path: str) -> pd.DataFrame | None:
    slat = _find(df.columns, SEGMENT_START_LAT_NAMES)
    slon = _find(df.columns, SEGMENT_START_LON_NAMES)
    elat = _find(df.columns, SEGMENT_END_LAT_NAMES)
    elon = _find(df.columns, SEGMENT_END_LON_NAMES)
    if not all((slat, slon, elat, elon)):
        return None

    start = _base_output(df, df[slat], df[slon], path)
    end = _base_output(df, df[elat], df[elon], path)
    start["source_geometry"] = "segment_start"
    end["source_geometry"] = "segment_end"

    rows = []
    for idx in range(len(df)):
        rows.append(start.iloc[idx])
        rows.append(end.iloc[idx])
    out = pd.DataFrame(rows).reset_index(drop=True)
    return _finalize_track(out, path)


def parse_csv_track(path: str) -> pd.DataFrame:
    df = _read_csv_robust(path)

    segment = _parse_segment_table(df, path)
    if segment is not None:
        return segment

    lat = _find(df.columns, LAT_NAMES)
    lon = _find(df.columns, LON_NAMES)
    if lat and lon:
        return _finalize_track(_base_output(df, df[lat], df[lon], path), path)

    position = _find(df.columns, POSITION_NAMES)
    if position:
        position_lat, position_lon = _parse_position_series(df[position])
        return _finalize_track(_base_output(df, position_lat, position_lon, path), path)

    raise NonTrackCSV(
        f"Non-track CSV: header found but no supported coordinate binding in {path}"
    )


def _empty_track_frame(rows: list[dict], path: str) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        raise ValueError(f"Empty track: no coordinates in {path}")
    for col, default in {
        "timestamp": pd.NaT,
        "speed": pd.NA,
        "callsign": pd.NA,
        "registration": pd.NA,
        "aircraft_type": pd.NA,
        "heading": pd.NA,
    }.items():
        if col not in df.columns:
            df[col] = default
    df["source"] = str(path)
    return df


def parse_kml_coordinates(path: str) -> pd.DataFrame:
    text = Path(path).read_text(errors="ignore")
    coords = []
    for block in re.findall(r"<coordinates>(.*?)</coordinates>", text, re.S | re.I):
        for token in block.split():
            parts = token.split(",")
            if len(parts) >= 2:
                try:
                    lon, lat = float(parts[0]), float(parts[1])
                    alt = float(parts[2]) if len(parts) > 2 and parts[2] else pd.NA
                    if -90 <= lat <= 90 and -180 <= lon <= 180:
                        coords.append({"latitude": lat, "longitude": lon, "altitude": alt})
                except ValueError:
                    continue

    # gx:Track uses separate <when> and <gx:coord> elements.  KML gx:coord
    # ordering is lon lat alt (space-separated), not FR24 CSV Position ordering.
    if not coords:
        root = ET.fromstring(text)
        gx_coords = []
        whens = []
        for elem in root.iter():
            tag = elem.tag.split("}")[-1].lower()
            if tag == "when" and elem.text:
                whens.append(elem.text.strip())
            elif tag == "coord" and elem.text:
                parts = elem.text.split()
                if len(parts) >= 2:
                    try:
                        lon, lat = float(parts[0]), float(parts[1])
                        alt = float(parts[2]) if len(parts) > 2 else pd.NA
                        if -90 <= lat <= 90 and -180 <= lon <= 180:
                            gx_coords.append(
                                {"latitude": lat, "longitude": lon, "altitude": alt}
                            )
                    except ValueError:
                        continue
        for idx, row in enumerate(gx_coords):
            if idx < len(whens):
                row["timestamp"] = pd.to_datetime(whens[idx], errors="coerce", utc=True)
        coords.extend(gx_coords)

    return _empty_track_frame(coords, path)


def parse_gpx_coordinates(path: str) -> pd.DataFrame:
    rows = []
    tree = ET.parse(path)
    root = tree.getroot()
    for elem in root.iter():
        tag = elem.tag.split("}")[-1].lower()
        if tag not in {"trkpt", "rtept", "wpt"}:
            continue
        try:
            lat = float(elem.attrib["lat"])
            lon = float(elem.attrib["lon"])
        except (KeyError, ValueError):
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        row = {"latitude": lat, "longitude": lon, "altitude": pd.NA, "timestamp": pd.NaT}
        for child in elem:
            ctag = child.tag.split("}")[-1].lower()
            if ctag == "ele" and child.text:
                row["altitude"] = pd.to_numeric(child.text, errors="coerce")
            elif ctag == "time" and child.text:
                row["timestamp"] = pd.to_datetime(child.text, errors="coerce", utc=True)
        rows.append(row)
    return _empty_track_frame(rows, path)
