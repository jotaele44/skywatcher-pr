"""
PR INTEL ADAPTER
Exports flight intelligence to parquet, GeoJSON, and JSON formats
suitable for integration with PR Integrated Intel System (PIIS).
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError as _pyarrow_err:
    raise ImportError(
        "pyarrow is required for PR Intel export. "
        "Install it with: pip install 'pyarrow>=14.0'"
    ) from _pyarrow_err

try:
    from integration.schema_validation import SchemaValidator
    _SCHEMA_VALIDATION_AVAILABLE = True
except ImportError:
    _SCHEMA_VALIDATION_AVAILABLE = False

from provenance_utils import (
    reproducibility_metadata,
    feature_collection_summary,
    geojson_feature_meta,
)

# Best-effort artifact → schema mapping (full mapping lives in
# schemas/schema_index.json — Tier 2). None where no schema is registered yet.
SCHEMA_BY_OUTPUT = {
    "airspace_events.parquet": "flight_event",
    "screenshot_evidence.parquet": "screenshot",
}


PROVENANCE_COLS = [
    ("screenshot_id", pa.string()),
    ("source_path", pa.string()),
    ("sha256", pa.string()),
    ("ocr_confidence", pa.float64()),
    ("coordinate_method", pa.string()),
    ("coordinate_confidence", pa.float64()),
    ("review_status", pa.string()),
]


class PRIntelAdapter:
    REQUIRED_OUTPUTS = [
        "airspace_events.parquet",
        "aircraft_profiles.parquet",
        "track_points.parquet",
        "screenshot_evidence.parquet",
        "mission_inferences.parquet",
        "anomaly_index.parquet",
        "gis_airspace_features.geojson",
        "route_lines.geojson",
        "source_manifest.json",
        "integration_report.json",
    ]

    def __init__(self, db_path: str, output_dir: str):
        self.db_path = db_path
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def export_all(self) -> Dict[str, Any]:
        generated = []
        missing = []
        schema_invalid = 0
        schema_validated = 0

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        flights = self._safe_query(conn, "SELECT * FROM flights")
        screenshots = self._safe_query(conn, "SELECT * FROM screenshots")
        track_pts = self._safe_query(conn, "SELECT * FROM track_points")
        mission_scores = self._safe_query(conn, "SELECT * FROM mission_scores")
        alerts = self._safe_query(conn, "SELECT * FROM alerts")
        aircraft_profiles = self._safe_query(conn, "SELECT * FROM aircraft_profiles")
        conn.close()

        # Build screenshot lookup (flight_id → first screenshot)
        ss_by_flight: Dict[str, dict] = {}
        for ss in screenshots:
            fid = ss.get("flight_id") or ""
            if fid and fid not in ss_by_flight:
                ss_by_flight[fid] = ss

        # Schema validation
        if _SCHEMA_VALIDATION_AVAILABLE:
            validator = SchemaValidator()
            review_path = str(self.output_dir / "review_queue.csv")
            _, n_inv_f = validator.validate_batch(flights, "flight_event", review_path)
            _, n_inv_s = validator.validate_batch(screenshots, "screenshot", review_path)
            schema_invalid = n_inv_f + n_inv_s
            schema_validated = len(flights) + len(screenshots)

        # Temporal integrity
        temporal_violations = self._count_temporal_violations(track_pts)

        # Export parquet files (pyarrow required — checked at import time)
        self._export_airspace_events(flights, ss_by_flight)
        self._export_aircraft_profiles(aircraft_profiles, ss_by_flight)
        self._export_track_points(track_pts, ss_by_flight)
        self._export_screenshot_evidence(screenshots)
        self._export_mission_inferences(mission_scores, ss_by_flight)
        self._export_anomaly_index(alerts, ss_by_flight)

        # GeoJSON exports (return feature lists for manifest geo-summaries)
        gis_features = self._export_gis_features(flights, ss_by_flight)
        route_features = self._export_route_lines(flights, ss_by_flight)
        geo_summaries = {
            "gis_airspace_features.geojson": feature_collection_summary(gis_features),
            "route_lines.geojson": feature_collection_summary(route_features),
        }

        # source_manifest.json (write before completeness check)
        manifest = {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "db_path": self.db_path,
            "schema_version": "1.0",
            "reproducibility": reproducibility_metadata(
                command=f"PRIntelAdapter.export_all db={self.db_path}",
                input_paths=[self.db_path],
            ),
            "files": [],  # populated after completeness check
        }
        manifest_path = self.output_dir / "source_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2))

        # Check which required outputs exist (excluding integration_report.json,
        # which is written last as the gate summary itself)
        checkable = [f for f in self.REQUIRED_OUTPUTS if f != "integration_report.json"]
        for fname in checkable:
            if (self.output_dir / fname).exists():
                generated.append(fname)
            else:
                missing.append(fname)

        # Update manifest with actual generated list + per-file metadata
        files_block = []
        for f in generated:
            path = self.output_dir / f
            try:
                size_bytes = path.stat().st_size
            except OSError:
                size_bytes = None
            count = self._count_output(f)
            entry = {
                "filename": f,
                "record_count": count,
                "exists": path.exists(),
                "size_bytes": size_bytes,
                "row_count": count,
                "crs": "EPSG:4326" if f.endswith(".geojson") else None,
                "schema_name": SCHEMA_BY_OUTPUT.get(f),
            }
            if f in geo_summaries:
                entry["geo_summary"] = geo_summaries[f]
            files_block.append(entry)
        manifest["files"] = files_block
        manifest_path.write_text(json.dumps(manifest, indent=2))

        # Gate thresholds
        COORD_THRESHOLD = 0.70    # 70% of flights must have at least one coord pair
        OCR_THRESHOLD = 0.50      # average OCR confidence must be ≥ 0.50
        EVIDENCE_THRESHOLD = 0.50 # 50% of screenshots must be linked to a flight

        # Coordinate coverage (skip gate when no flights)
        flights_with_coords = sum(
            1 for f in flights
            if (f.get("origin_lat") or f.get("dest_lat"))
        )
        pct_coords = (flights_with_coords / len(flights)) if flights else 1.0
        coord_status = "PASS" if (not flights or pct_coords >= COORD_THRESHOLD) else "FAIL"

        # OCR confidence gate (skip when no screenshots)
        confidences = [
            ss.get("ocr_confidence") or 0.0
            for ss in screenshots
            if ss.get("ocr_confidence") is not None
        ]
        avg_conf = sum(confidences) / len(confidences) if confidences else 1.0
        ocr_status = "PASS" if (not screenshots or avg_conf >= OCR_THRESHOLD) else "FAIL"

        # Evidence chain coverage (skip when no screenshots)
        ss_with_flight = sum(1 for ss in screenshots if ss.get("flight_id"))
        pct_ss = (ss_with_flight / len(screenshots)) if screenshots else 1.0
        evidence_status = "PASS" if (not screenshots or pct_ss >= EVIDENCE_THRESHOLD) else "FAIL"

        # Schema validation gate (any invalid record fails)
        schema_status = "PASS" if schema_invalid == 0 else "FAIL"

        gates = {
            "schema_validation": {
                "status": schema_status,
                "records_validated": schema_validated,
                "invalid": schema_invalid,
            },
            "coordinate_coverage": {
                "status": coord_status,
                "pct_with_coords": round(pct_coords, 4),
                "threshold": COORD_THRESHOLD,
            },
            "ocr_confidence_gate": {
                "status": ocr_status,
                "avg_confidence": round(avg_conf, 4),
                "threshold": OCR_THRESHOLD,
            },
            "evidence_chain_coverage": {
                "status": evidence_status,
                "pct_with_screenshot": round(pct_ss, 4),
                "threshold": EVIDENCE_THRESHOLD,
            },
            "export_completeness": {
                "status": "PASS" if not missing else "FAIL",
                "files_generated": len(generated),
                "missing": missing,
            },
            "temporal_integrity": {
                "status": "PASS" if (temporal_violations == 0 or not track_pts) else "FAIL",
                "violations": temporal_violations,
            },
        }

        overall_status = "PASS" if all(g["status"] == "PASS" for g in gates.values()) else "FAIL"

        report = {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "overall_status": overall_status,
            "gates": gates,
        }
        (self.output_dir / "integration_report.json").write_text(json.dumps(report, indent=2))

        return report

    # ------------------------------------------------------------------ parquet

    def _export_airspace_events(self, flights: List[dict], ss_by_flight: Dict[str, dict]):
        rows = []
        for f in flights:
            ss = ss_by_flight.get(f.get("flight_id", ""), {})
            rows.append({
                "flight_id": f.get("flight_id", ""),
                "callsign": f.get("callsign", ""),
                "aircraft_type": f.get("aircraft_type", ""),
                "operator": f.get("operator", ""),
                "origin_airport": f.get("origin_airport", ""),
                "destination_airport": f.get("destination_airport", ""),
                "takeoff_time": f.get("takeoff_time", ""),
                "landing_time": f.get("landing_time", ""),
                "flight_duration_minutes": f.get("flight_duration_minutes") or 0,
                "max_altitude_ft": f.get("max_altitude_ft") or 0,
                "avg_speed_mph": float(f.get("avg_speed_mph") or 0.0),
                "mission_type": f.get("mission_type", ""),
                "origin_lat": float(f.get("origin_lat") or 0.0),
                "origin_lon": float(f.get("origin_lon") or 0.0),
                "dest_lat": float(f.get("dest_lat") or 0.0),
                "dest_lon": float(f.get("dest_lon") or 0.0),
                "num_screenshots": f.get("num_screenshots") or 0,
                **self._provenance(ss),
            })
        rows.sort(key=lambda r: str(r.get("flight_id") or ""))
        self._write_parquet("airspace_events.parquet", rows)

    def _export_aircraft_profiles(self, profiles: List[dict], ss_by_flight: Dict[str, dict]):
        rows = []
        for p in profiles:
            callsign = p.get("callsign", "")
            ss = next((v for v in ss_by_flight.values() if v.get("callsign") == callsign), {})
            rows.append({
                "callsign": callsign,
                "aircraft_type": p.get("aircraft_type", ""),
                "operator": p.get("operator", ""),
                "primary_mission": p.get("primary_mission", ""),
                "confidence_level": float(p.get("confidence_level") or 0.0),
                "last_seen": p.get("last_seen", ""),
                "flight_count": p.get("total_flights") or 0,
                **self._provenance(ss),
            })
        rows.sort(key=lambda r: str(r.get("callsign") or ""))
        self._write_parquet("aircraft_profiles.parquet", rows)

    def _export_track_points(self, track_pts: List[dict], ss_by_flight: Dict[str, dict]):
        rows = []
        for tp in track_pts:
            ss = ss_by_flight.get(tp.get("flight_id", ""), {})
            rows.append({
                "id": tp.get("id") or 0,
                "flight_id": tp.get("flight_id", ""),
                "timestamp": tp.get("timestamp", ""),
                "latitude": float(tp.get("latitude") or 0.0),
                "longitude": float(tp.get("longitude") or 0.0),
                "altitude_ft": tp.get("altitude_ft") or 0,
                "ground_speed_mph": tp.get("ground_speed_mph") or 0,
                **self._provenance(ss),
            })
        rows.sort(key=lambda r: (str(r.get("flight_id") or ""), str(r.get("timestamp") or ""), r.get("id") or 0))
        self._write_parquet("track_points.parquet", rows)

    def _export_screenshot_evidence(self, screenshots: List[dict]):
        rows = []
        for ss in screenshots:
            rows.append({
                "screenshot_id": ss.get("screenshot_id", ""),
                "image_path": ss.get("image_path", ""),
                "flight_id": ss.get("flight_id", ""),
                "processed_at": ss.get("processed_at", ""),
                "callsign": ss.get("callsign", ""),
                "altitude_ft": ss.get("altitude_ft") or 0,
                "ground_speed_mph": ss.get("ground_speed_mph") or 0,
                "latitude": float(ss.get("latitude") or 0.0),
                "longitude": float(ss.get("longitude") or 0.0),
                "timestamp": ss.get("timestamp", ""),
                "ocr_confidence": float(ss.get("ocr_confidence") or 0.0),
                "sha256": ss.get("sha256", ""),
                "coordinate_method": ss.get("coordinate_method", "fixed_pr_bounds"),
                "coordinate_confidence": float(ss.get("coordinate_confidence") or 0.65),
                "estimated_error_m": float(ss.get("estimated_error_m") or 1500.0),
                "review_status": ss.get("review_status", "pending"),
            })
        rows.sort(key=lambda r: str(r.get("screenshot_id") or ""))
        self._write_parquet("screenshot_evidence.parquet", rows)

    def _export_mission_inferences(self, scores: List[dict], ss_by_flight: Dict[str, dict]):
        rows = []
        for ms in scores:
            ss = ss_by_flight.get(ms.get("flight_id", ""), {})
            rows.append({
                "flight_id": ms.get("flight_id", ""),
                "mission_type": ms.get("mission_type", ""),
                "total_score": float(ms.get("total_score") or 0.0),
                "confidence_level": float(ms.get("confidence_level") or 0.0),
                "signal_scores": ms.get("signal_scores", ""),
                "explanation": ms.get("explanation", ""),
                "scored_at": ms.get("scored_at", ""),
                **self._provenance(ss),
            })
        rows.sort(key=lambda r: str(r.get("flight_id") or ""))
        self._write_parquet("mission_inferences.parquet", rows)

    def _export_anomaly_index(self, alerts: List[dict], ss_by_flight: Dict[str, dict]):
        rows = []
        for a in alerts:
            ss = ss_by_flight.get(a.get("flight_id", ""), {})
            rows.append({
                "alert_id": a.get("alert_id", ""),
                "flight_id": a.get("flight_id", ""),
                "callsign": a.get("callsign", ""),
                "category": a.get("category", ""),
                "severity": a.get("severity", ""),
                "title": a.get("title", ""),
                "description": a.get("description", ""),
                "timestamp": a.get("timestamp", ""),
                **self._provenance(ss),
            })
        rows.sort(key=lambda r: str(r.get("alert_id") or ""))
        self._write_parquet("anomaly_index.parquet", rows)

    # ----------------------------------------------------------------- geojson

    def _export_gis_features(self, flights: List[dict], ss_by_flight: Dict[str, dict]):
        features = []
        seen: set = set()
        meta_block = geojson_feature_meta(
            producer_module="integration.pr_intel_adapter",
            source_artifact="gis_airspace_features.geojson",
        )
        # Deterministic: sort flights so first-occurrence-wins dedup is stable (Open Risk #5).
        for f in sorted(flights, key=lambda x: str(x.get("flight_id") or "")):
            ss = ss_by_flight.get(f.get("flight_id", ""), {})
            for prefix, lat_k, lon_k, name_k in [
                ("origin", "origin_lat", "origin_lon", "origin_airport"),
                ("dest", "dest_lat", "dest_lon", "destination_airport"),
            ]:
                lat = f.get(lat_k)
                lon = f.get(lon_k)
                name = f.get(name_k, "")
                if lat and lon and name and name not in seen:
                    seen.add(name)
                    features.append({
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [lon, lat]},
                        "properties": {
                            "feature_id": f"{prefix}_{name}",
                            "name": name,
                            "type": "airport",
                            "radius_nm": None,
                            "operational_notes": "",
                            "screenshot_id": ss.get("screenshot_id", ""),
                            "sha256": ss.get("sha256", ""),
                            "source_path": ss.get("image_path", ""),
                            "_meta": meta_block,
                        },
                    })

        geojson = {
            "type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::4326"}},
            "features": features,
        }
        (self.output_dir / "gis_airspace_features.geojson").write_text(json.dumps(geojson, indent=2))
        return features

    def _export_route_lines(self, flights: List[dict], ss_by_flight: Dict[str, dict]):
        features = []
        meta_block = geojson_feature_meta(
            producer_module="integration.pr_intel_adapter",
            source_artifact="route_lines.geojson",
        )
        for f in sorted(flights, key=lambda x: str(x.get("flight_id") or "")):
            olat = f.get("origin_lat")
            olon = f.get("origin_lon")
            dlat = f.get("dest_lat")
            dlon = f.get("dest_lon")
            if olat and olon and dlat and dlon:
                ss = ss_by_flight.get(f.get("flight_id", ""), {})
                features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[olon, olat], [dlon, dlat]],
                    },
                    "properties": {
                        "flight_id": f.get("flight_id", ""),
                        "callsign": f.get("callsign", ""),
                        "duration_min": f.get("flight_duration_minutes") or 0,
                        "screenshot_id": ss.get("screenshot_id", ""),
                        "sha256": ss.get("sha256", ""),
                        "source_path": ss.get("image_path", ""),
                        "_meta": meta_block,
                    },
                })

        geojson = {
            "type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::4326"}},
            "features": features,
        }
        (self.output_dir / "route_lines.geojson").write_text(json.dumps(geojson, indent=2))
        return features

    # ----------------------------------------------------------------- helpers

    def _provenance(self, ss: dict) -> dict:
        return {
            "screenshot_id": ss.get("screenshot_id", ""),
            "source_path": ss.get("image_path", ""),
            "sha256": ss.get("sha256", ""),
            "ocr_confidence": float(ss.get("ocr_confidence") or 0.0),
            "coordinate_method": ss.get("coordinate_method", "fixed_pr_bounds"),
            "coordinate_confidence": float(ss.get("coordinate_confidence") or 0.65),
            "review_status": ss.get("review_status", "pending"),
        }

    def _write_parquet(self, filename: str, rows: List[dict]):
        if not rows:
            pq.write_table(pa.table({}), self.output_dir / filename)
            return

        keys = list(rows[0].keys())
        columns: Dict[str, list] = {k: [] for k in keys}
        for row in rows:
            for k in keys:
                columns[k].append(row.get(k))

        arrays = []
        fields = []
        for k in keys:
            vals = columns[k]
            # Infer type
            non_none = [v for v in vals if v is not None]
            if not non_none or isinstance(non_none[0], str):
                arr = pa.array([v if isinstance(v, str) else (str(v) if v is not None else None) for v in vals], type=pa.string())
                fields.append(pa.field(k, pa.string()))
            elif isinstance(non_none[0], float):
                arr = pa.array([float(v) if v is not None else None for v in vals], type=pa.float64())
                fields.append(pa.field(k, pa.float64()))
            elif isinstance(non_none[0], int):
                arr = pa.array([int(v) if v is not None else None for v in vals], type=pa.int64())
                fields.append(pa.field(k, pa.int64()))
            else:
                arr = pa.array([str(v) if v is not None else None for v in vals], type=pa.string())
                fields.append(pa.field(k, pa.string()))
            arrays.append(arr)

        schema = pa.schema(fields)
        table = pa.table({k: arrays[i] for i, k in enumerate(keys)}, schema=schema)
        pq.write_table(table, self.output_dir / filename)

    def _safe_query(self, conn: sqlite3.Connection, sql: str) -> List[dict]:
        try:
            return [dict(r) for r in conn.execute(sql)]
        except Exception:
            return []

    def _count_output(self, filename: str) -> int:
        path = self.output_dir / filename
        if not path.exists():
            return 0
        if filename.endswith(".parquet"):
            try:
                return pq.read_table(path).num_rows
            except Exception:
                return 0
        if filename.endswith(".json"):
            try:
                data = json.loads(path.read_text())
                if isinstance(data, dict) and "files" in data:
                    return len(data["files"])
                return 1
            except Exception:
                return 0
        if filename.endswith(".geojson"):
            try:
                data = json.loads(path.read_text())
                return len(data.get("features", []))
            except Exception:
                return 0
        return 0

    def _count_temporal_violations(self, track_pts: List[dict]) -> int:
        try:
            from pipeline.hardening_layer import TemporalValidator
            by_flight: Dict[str, list] = {}
            for tp in track_pts:
                fid = tp.get("flight_id", "")
                by_flight.setdefault(fid, []).append(tp)
            validator = TemporalValidator()
            total = 0
            for pts in by_flight.values():
                results = validator.validate_track(pts)
                total += validator.count_violations(results)
            return total
        except Exception:
            return 0
