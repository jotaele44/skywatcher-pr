"""
AASB AIRSPACE BRIDGE
Exports airport-node edge CSV and Spiderweb ingest manifest for AASB/UGCN integration.
"""

import csv
import json
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from provenance_utils import reproducibility_metadata, feature_collection_summary
from integration.mbil import is_mbil_high, mbil_class


# Known PR airport coordinates for node anchoring
AIRPORT_COORDS: Dict[str, Tuple[float, float]] = {
    "SJU": (18.4373, -66.0018),
    "BQN": (18.4948, -67.1294),
    "PSE": (18.0083, -66.5632),
    "SIG": (18.4561, -66.0978),
    "NRR": (18.2453, -65.6435),
    "MAZ": (18.2557, -67.1489),
    "ARE": (18.4500, -66.6757),
    "CPX": (18.3133, -65.3043),
    "VQS": (18.1348, -65.4935),
}

EDGE_FIELDNAMES = [
    "edge_id", "from_node", "to_node",
    "from_lat", "from_lon", "to_lat", "to_lon",
    "weight", "flight_count", "avg_duration_min",
    "dominant_callsign", "confidence_score",
    "aasb_mbil_corridor_flag",
]


class AASBAirspaceBridge:
    def __init__(self, db_path: str, output_dir: str):
        self.db_path = db_path
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def export_all(self) -> Dict[str, Any]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        flights = self._safe_query(conn, "SELECT * FROM flights")
        conn.close()

        edges = self._build_edges(flights)
        edge_path = self._write_edges(edges)

        # Gather all files produced by both bridges (ilap + aasb)
        all_files = self._inventory_output_files()

        manifest = {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "db_path": self.db_path,
            "schema_version": "1.0",
            # Manifest-level CRS so consumers know the datum without opening a file (T7-65).
            "crs": "EPSG:4326",
            "epsg": 4326,
            "reproducibility": reproducibility_metadata(
                command=f"AASBAirspaceBridge.export_all db={self.db_path}",
                input_paths=[self.db_path],
            ),
            "files": all_files,
        }
        manifest_path = self.output_dir / "spiderweb_ingest_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2))

        return {
            "generated_at": manifest["generated_at"],
            "output_dir": str(self.output_dir),
            "edge_count": len(edges),
            "files": {f["filename"]: f["record_count"] for f in all_files},
        }

    # ------------------------------------------------------------------ edges

    def _build_edges(self, flights: List[dict]) -> List[dict]:
        # Aggregate by (origin, destination) pair
        RouteKey = Tuple[str, str]
        agg: Dict[RouteKey, Dict] = defaultdict(lambda: {
            "flight_count": 0,
            "total_duration": 0.0,
            "callsign_counts": defaultdict(int),
        })

        for f in flights:
            origin = (f.get("origin_airport") or "").strip()
            dest = (f.get("destination_airport") or "").strip()
            if not origin or not dest or origin == dest:
                continue
            key: RouteKey = (origin, dest)
            agg[key]["flight_count"] += 1
            dur = f.get("flight_duration_minutes") or 0
            agg[key]["total_duration"] += float(dur)
            callsign = (f.get("callsign") or "").strip()
            if callsign:
                agg[key]["callsign_counts"][callsign] += 1

        edges = []
        for idx, ((origin, dest), data) in enumerate(agg.items()):
            from_lat, from_lon = AIRPORT_COORDS.get(origin, (0.0, 0.0))
            to_lat, to_lon = AIRPORT_COORDS.get(dest, (0.0, 0.0))
            flight_count = data["flight_count"]
            avg_dur = data["total_duration"] / flight_count if flight_count else 0.0
            dominant = max(data["callsign_counts"], key=data["callsign_counts"].get) \
                if data["callsign_counts"] else ""
            confidence = min(1.0, flight_count / 5.0)

            # T3-28: flag edges where both endpoints are MBIL-2+ (inner periurban
            # or closer), indicating the corridor links two high-activity municipal zones.
            mbil_from = mbil_class(from_lat, from_lon) if (from_lat or from_lon) else "MBIL-X"
            mbil_to = mbil_class(to_lat, to_lon) if (to_lat or to_lon) else "MBIL-X"
            corridor_flag = is_mbil_high(mbil_from) and is_mbil_high(mbil_to)

            edges.append({
                "edge_id": f"EDGE_{idx:04d}_{origin}_{dest}",
                "from_node": origin,
                "to_node": dest,
                "from_lat": from_lat,
                "from_lon": from_lon,
                "to_lat": to_lat,
                "to_lon": to_lon,
                "weight": flight_count,
                "flight_count": flight_count,
                "avg_duration_min": round(avg_dur, 2),
                "dominant_callsign": dominant,
                "confidence_score": round(confidence, 4),
                "aasb_mbil_corridor_flag": corridor_flag,
            })

        return edges

    def _write_edges(self, edges: List[dict]) -> Path:
        path = self.output_dir / "aasb_airspace_edges.csv"
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=EDGE_FIELDNAMES)
            writer.writeheader()
            writer.writerows(edges)
        return path

    # ----------------------------------------------------------------- manifest helpers

    def _inventory_output_files(self) -> List[dict]:
        target_files = [
            "airspace_poi_candidates.geojson",
            "airspace_ilap_candidates.geojson",
            "airspace_corridor_candidates.geojson",
            "aasb_airspace_edges.csv",
        ]
        result = []
        for fname in target_files:
            fpath = self.output_dir / fname
            if fpath.exists():
                result.append({
                    "filename": fname,
                    "record_count": self._count_records(fpath),
                    "bbox": self._bbox_for(fpath),
                    # Every geo artifact carries an explicit CRS/EPSG stamp (T7-65).
                    "crs": "EPSG:4326",
                    "epsg": 4326,
                })
        return result

    def _bbox_for(self, path: Path):
        """[min_lon, min_lat, max_lon, max_lat] in EPSG:4326, or None."""
        try:
            if path.suffix == ".geojson":
                data = json.loads(path.read_text())
                return feature_collection_summary(data.get("features", []))["bbox"]
            if path.suffix == ".csv":
                lons: List[float] = []
                lats: List[float] = []
                with open(path, newline="") as f:
                    for row in csv.DictReader(f):
                        for lat_k, lon_k in (("from_lat", "from_lon"), ("to_lat", "to_lon")):
                            try:
                                lat = float(row.get(lat_k) or 0)
                                lon = float(row.get(lon_k) or 0)
                            except ValueError:
                                continue
                            if lat or lon:  # skip (0,0) unknown-airport sentinels
                                lats.append(lat)
                                lons.append(lon)
                if lons and lats:
                    return [round(min(lons), 6), round(min(lats), 6),
                            round(max(lons), 6), round(max(lats), 6)]
        except Exception:
            return None
        return None

    def _count_records(self, path: Path) -> int:
        if path.suffix == ".geojson":
            try:
                data = json.loads(path.read_text())
                return len(data.get("features", []))
            except Exception:
                return 0
        if path.suffix == ".csv":
            try:
                with open(path, newline="") as f:
                    return sum(1 for _ in csv.reader(f)) - 1  # exclude header
            except Exception:
                return 0
        return 0

    def _safe_query(self, conn: sqlite3.Connection, sql: str) -> List[dict]:
        try:
            return [dict(r) for r in conn.execute(sql)]
        except Exception:
            return []
