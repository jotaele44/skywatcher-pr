from __future__ import annotations
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import pandas as pd

LAT_NAMES = ["lat", "latitude", "y", "gps_lat", "position_lat"]
LON_NAMES = ["lon", "lng", "longitude", "x", "gps_lon", "position_lon"]
TIME_NAMES = ["timestamp", "time", "datetime", "date", "utc", "seen", "created_at"]
ALT_NAMES = ["alt", "altitude", "altitude_ft", "baro_altitude", "geo_altitude"]
SPD_NAMES = ["speed", "groundspeed", "gs", "speed_mph", "velocity", "ground_speed"]
HEADING_NAMES = ["heading", "track", "bearing", "course"]

class NonTrackCSV(ValueError):
    """Raised when a CSV is valid but does not contain track coordinates."""

def _find(cols, names):
    low = {str(c).lower().strip().replace(" ", "_"): c for c in cols}
    for n in names:
        if n in low:
            return low[n]
    return None

def _read_csv_robust(path: str) -> pd.DataFrame:
    last = None
    for enc in ["utf-8", "utf-8-sig", "latin1", "cp1252"]:
        try:
            return pd.read_csv(path, encoding=enc, low_memory=False)
        except Exception as e:
            last = e
    raise last

def parse_csv_track(path: str) -> pd.DataFrame:
    df = _read_csv_robust(path)
    lat, lon, t = _find(df.columns, LAT_NAMES), _find(df.columns, LON_NAMES), _find(df.columns, TIME_NAMES)
    if not lat or not lon:
        raise NonTrackCSV(f"Non-track CSV: missing lat/lon columns in {path}")
    out = pd.DataFrame({"latitude": pd.to_numeric(df[lat], errors="coerce"), "longitude": pd.to_numeric(df[lon], errors="coerce")})
    out["timestamp"] = pd.to_datetime(df[t], errors="coerce", utc=True) if t else pd.NaT
    alt, spd, hdg = _find(df.columns, ALT_NAMES), _find(df.columns, SPD_NAMES), _find(df.columns, HEADING_NAMES)
    out["altitude"] = pd.to_numeric(df[alt], errors="coerce") if alt else pd.NA
    out["speed"] = pd.to_numeric(df[spd], errors="coerce") if spd else pd.NA
    for c in ["callsign", "registration", "aircraft_type"]:
        src = _find(df.columns, [c, c.replace("_", "")])
        out[c] = df[src] if src else pd.NA
    out["heading"] = pd.to_numeric(df[hdg], errors="coerce") if hdg else pd.NA
    out["source"] = str(path)
    out = out.dropna(subset=["latitude", "longitude"])
    out = out[(out.latitude.between(-90,90)) & (out.longitude.between(-180,180))]
    if out.empty:
        raise NonTrackCSV(f"Non-track CSV: no valid coordinate rows in {path}")
    return out

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
    df = pd.DataFrame(coords)
    if df.empty:
        raise ValueError(f"No KML coordinates in {path}")
    df["timestamp"] = pd.NaT
    df["speed"] = pd.NA
    df["callsign"] = pd.NA
    df["registration"] = pd.NA
    df["aircraft_type"] = pd.NA
    df["heading"] = pd.NA
    df["source"] = str(path)
    return df

def parse_gpx_coordinates(path: str) -> pd.DataFrame:
    root = ET.parse(path).getroot()
    coords = []
    for elem in root.iter():
        tag = elem.tag.split("}")[-1].lower()
        if tag not in {"trkpt", "rtept", "wpt"}:
            continue
        lat_raw, lon_raw = elem.attrib.get("lat"), elem.attrib.get("lon")
        if lat_raw is None or lon_raw is None:
            continue
        try:
            lat, lon = float(lat_raw), float(lon_raw)
        except ValueError:
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        ele = pd.NA
        timestamp = pd.NaT
        for child in elem:
            child_tag = child.tag.split("}")[-1].lower()
            text = (child.text or "").strip()
            if child_tag == "ele" and text:
                ele = pd.to_numeric(text, errors="coerce")
            elif child_tag == "time" and text:
                timestamp = pd.to_datetime(text, errors="coerce", utc=True)
        coords.append({"latitude": lat, "longitude": lon, "altitude": ele, "timestamp": timestamp})
    df = pd.DataFrame(coords)
    if df.empty:
        raise ValueError(f"No GPX coordinates in {path}")
    df["speed"] = pd.NA
    df["callsign"] = pd.NA
    df["registration"] = pd.NA
    df["aircraft_type"] = pd.NA
    df["heading"] = pd.NA
    df["source"] = str(path)
    return df

def parse_track_file(path: str) -> pd.DataFrame:
    suffix = Path(path).suffix.lower()
    if suffix == ".csv":
        return parse_csv_track(path)
    if suffix == ".kml":
        return parse_kml_coordinates(path)
    if suffix == ".gpx":
        return parse_gpx_coordinates(path)
    raise ValueError(f"Unsupported track extension: {suffix}")
