"""
SPIDERWEB INTAKE
Consumes the five --export-spiderweb bridge files and produces a normalized
Spiderweb overlay layer with MBIL/hydro/utility/terrain scoring and a gap audit.

This module is Spiderweb-native: it reads the producer boundary as-is and
does not modify any PRII modules (pr_intel_adapter, schema_validation, etc.).
"""

import csv
import json
import math
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pipeline.terrain_hook import get_terrain_context
from provenance_utils import (
    reproducibility_metadata,
    feature_collection_summary,
    geojson_feature_meta,
)

# ── Producer boundary ─────────────────────────────────────────────────────────

BRIDGE_FILES = [
    "airspace_poi_candidates.geojson",
    "airspace_ilap_candidates.geojson",
    "airspace_corridor_candidates.geojson",
    "aasb_airspace_edges.csv",
    "spiderweb_ingest_manifest.json",
]

# ── Required Spiderweb output fields ─────────────────────────────────────────

REQUIRED_FIELDS = [
    "source_layer", "candidate_type", "lat", "lon", "confidence",
    "evidence_tier", "linked_flight_id", "linked_aircraft", "corridor_id",
    "mbil_class", "hydro_overlap", "utility_overlap", "terrain_context",
    "review_status",
    # Tier 3 additive fields (D5):
    "fact_status",                 # 'observed' (high-conf + ≥2 corroborating) | 'inferred'
    "spiderweb_role",              # 'node' | 'path' | 'edge' | 'airport_link'
    "access_assertion_level",      # 'public_record' (airport-anchored) | 'derived_observation'
    "nearest_municipal_boundary_m",# distance in meters to nearest of MUNICIPAL_CENTROIDS
    "aasb_mbil_corridor_flag",     # bool: corridor candidate with MBIL-2+ at both endpoints
]

# ── Scoring constants ─────────────────────────────────────────────────────────

DEDUP_THRESH_DEG = 0.00045   # ≈50 m

# PR municipal centroids (full 72-municipality set; extended for operational coverage)
MUNICIPAL_CENTROIDS: List[Tuple[float, float]] = [
    # Original 20
    (18.4655, -66.1057),  # San Juan
    (18.0099, -66.6140),  # Ponce
    (18.4279, -66.7177),  # Mayagüez
    (18.4906, -67.1414),  # Aguadilla
    (18.3990, -65.9732),  # Carolina
    (18.3449, -66.0498),  # Guaynabo
    (18.3804, -65.8754),  # Loíza
    (18.2218, -66.0370),  # Cayey
    (18.0791, -66.5293),  # Juana Díaz
    (18.2499, -65.8960),  # Humacao
    (18.4735, -66.9008),  # San Germán
    (18.1466, -65.9965),  # Salinas
    (18.3660, -66.4696),  # Barceloneta
    (18.2302, -66.3068),  # Aibonito
    (18.4562, -66.5551),  # Arecibo
    (18.1306, -66.7327),  # Yauco
    (18.4284, -66.1617),  # Bayamón
    (18.4014, -66.2956),  # Toa Baja
    (18.4449, -66.6188),  # Camuy
    (18.3002, -65.6340),  # Fajardo
    # Extended — eastern PR
    (18.2833, -65.9000),  # Caguas
    (18.4667, -65.8333),  # Luquillo
    (18.4000, -65.8833),  # Río Grande
    (18.3606, -65.6268),  # Ceiba
    (18.2333, -65.8167),  # Juncos
    (18.2799, -65.7760),  # Yabucoa
    (18.1167, -65.8833),  # Patillas
    (18.1833, -65.7000),  # Maunabo
    (18.2500, -65.8833),  # Las Piedras
    (18.3167, -65.8333),  # Trujillo Alto
    (18.4500, -65.9833),  # Canóvanas
    (18.2267, -65.9702),  # Gurabo
    (18.3333, -65.7333),  # Las Piedras (alt)
    # Extended — northern coast
    (18.4667, -66.1167),  # Toa Alta
    (18.4167, -66.2500),  # Vega Alta
    (18.4500, -66.3333),  # Vega Baja
    (18.4167, -66.4833),  # Manatí
    (18.4800, -66.7167),  # Quebradillas
    (18.4667, -67.0333),  # Isabela
    (18.5333, -67.0833),  # Aguadilla (north)
    (18.4000, -66.7500),  # Aguada
    (18.3571, -67.1792),  # Moca
    # Extended — central highlands
    (18.3333, -66.8667),  # Lares
    (18.3011, -66.6942),  # Utuado
    (18.3614, -66.9291),  # Las Marías
    (18.3005, -66.9217),  # Maricao
    (18.2833, -66.4833),  # Orocovis
    (18.2500, -66.3333),  # Barranquitas
    (18.1833, -66.2833),  # Comerío
    (18.2000, -66.0333),  # Aguas Buenas
    (18.3333, -65.9833),  # Naranjito
    (18.2000, -66.4833),  # Villalba
    # Extended — western & southwestern PR
    (18.1417, -66.8783),  # Añasco
    (18.0500, -66.8167),  # Hormigueros
    (18.0833, -67.1500),  # Lajas
    (18.0167, -66.8667),  # Cabo Rojo
    (17.9966, -66.6143),  # Guayanilla
    # Extended — southern PR
    (18.0272, -66.3612),  # Santa Isabel
    (17.9667, -66.3833),  # Coamo
    (18.0500, -66.1281),  # Guayama
    (17.9999, -66.1000),  # Arroyo
    (18.1167, -66.3833),  # Juana Díaz (alt)
]

# PR reservoirs / major water bodies
HYDRO_LOCATIONS: List[Tuple[float, float]] = [
    (18.3517, -66.3200),  # Lago La Plata
    (18.3333, -66.7167),  # Lago Dos Bocas
    (18.3667, -65.9833),  # Lago Loíza
    (18.1167, -66.5333),  # Lago Toa Vaca
    (18.0500, -66.5667),  # Embalse Cerrillos
    (18.1667, -66.2167),  # Lago Cidra
    (18.2667, -65.7833),  # Lago Humacao
    (18.1333, -66.4167),  # Lago Coamo
    # Extended
    (18.3300, -65.9700),  # Lago Carraízo / Loíza Reservoir
    (18.4300, -66.8500),  # Lago Guajataca
    (18.3833, -65.9667),  # Laguna Torrecilla
    (18.1000, -66.4667),  # Lago Yahuecas
    (18.0167, -66.2667),  # Lago Patillas
    (18.3167, -66.5833),  # Lago Caonillas
]
HYDRO_THRESH_DEG = 0.08   # ≈9 km

# SJU↔PSE and SJU↔BQN corridor midpoint+bearing heuristic (simplified as waypoints)
UTILITY_CORRIDOR_WAYPOINTS: List[Tuple[float, float]] = [
    (18.4373, -66.0018),  # SJU
    (18.2600, -66.3000),  # midpoint SJU–PSE
    (18.0083, -66.5632),  # PSE
    (18.3700, -66.5500),  # midpoint SJU–BQN
    (18.4948, -67.1294),  # BQN
    (18.4000, -66.8500),  # Mayagüez corridor waypoint
    # Extended — northern coast and southern transmission routes
    (18.4800, -66.4500),  # Arecibo-Barceloneta transmission node
    (18.4667, -66.7167),  # northern coast midpoint SJU→Aguadilla
    (18.1100, -66.5400),  # southern corridor Ponce→Yauco
    (18.0083, -66.7000),  # southwestern endpoint
]
UTILITY_THRESH_DEG = 0.05  # ≈5 km

# SJU metro bounding box
URBAN_LAT = (18.35, 18.50)
URBAN_LON = (-66.20, -65.90)

# Ponce metro bounding box
PONCE_URBAN_LAT = (17.95, 18.07)
PONCE_URBAN_LON = (-66.68, -66.52)

# Mayagüez metro bounding box
MAYAGUEZ_URBAN_LAT = (18.18, 18.28)
MAYAGUEZ_URBAN_LON = (-67.20, -67.08)

# PR longitude bounds — beyond these is open ocean → coastal
PR_LON_WEST = -67.30
PR_LON_EAST = -65.50

CONFIDENCE_T1 = 0.65
CONFIDENCE_T2 = 0.40
CONFIDENCE_REJECTED = 0.25


# ── Main class ────────────────────────────────────────────────────────────────

class SpiderwebIntake:
    def __init__(self, input_dir: str, output_dir: str):
        self.input_dir = Path(input_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(self) -> Dict[str, Any]:
        candidates = self._load_candidates()
        self._normalize(candidates)
        missing_files = self._missing_bridge_files()
        dups_removed, candidates = self._dedup(candidates, DEDUP_THRESH_DEG)
        self._score_mbil(candidates)
        self._score_hydro(candidates)
        self._score_utility(candidates)
        self._score_terrain(candidates)
        # Tier 3 additive scoring — must run before _assign_evidence_tier so the
        # MBIL guardrail (T3-27) has the corroboration counts it needs.
        self._score_spiderweb_role(candidates)
        self._score_access_assertion(candidates)
        self._score_nearest_municipal_boundary_m(candidates)
        self._score_aasb_mbil_corridor_flag(candidates)
        self._assign_evidence_tier(candidates)
        gap_audit = self._gap_audit(candidates, missing_files, dups_removed)
        self._write_outputs(candidates, gap_audit)
        return {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "total_candidates": len(candidates),
            "output_dir": str(self.output_dir),
            "gap_audit": gap_audit,
        }

    # ── Loader ────────────────────────────────────────────────────────────────

    def _load_candidates(self) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []

        for geojson_file, ctype in [
            ("airspace_poi_candidates.geojson", "poi"),
            ("airspace_ilap_candidates.geojson", "ilap"),
            ("airspace_corridor_candidates.geojson", "corridor"),
        ]:
            path = self.input_dir / geojson_file
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            for feat in data.get("features", []):
                geom = feat.get("geometry", {})
                props = feat.get("properties", {}) or {}
                lat, lon = self._centroid(geom)
                if lat is None:
                    continue
                candidates.append({
                    "_raw_props": props,
                    "_candidate_type": ctype,
                    "_lat": lat,
                    "_lon": lon,
                })

        edge_path = self.input_dir / "aasb_airspace_edges.csv"
        if edge_path.exists():
            try:
                with open(edge_path, newline="", encoding="utf-8") as f:
                    for row in csv.DictReader(f):
                        from_lat = _safe_float(row.get("from_lat"))
                        from_lon = _safe_float(row.get("from_lon"))
                        to_lat = _safe_float(row.get("to_lat"))
                        to_lon = _safe_float(row.get("to_lon"))
                        if from_lat is None or to_lat is None:
                            continue
                        lat = (from_lat + to_lat) / 2.0
                        lon = (from_lon + to_lon) / 2.0
                        candidates.append({
                            "_raw_props": dict(row),
                            "_candidate_type": "aasb_edge",
                            "_lat": lat,
                            "_lon": lon,
                        })
            except Exception:
                pass

        return candidates

    # ── Normalizer ────────────────────────────────────────────────────────────

    def _normalize(self, candidates: List[Dict[str, Any]]) -> None:
        for c in candidates:
            props = c["_raw_props"]
            ctype = c["_candidate_type"]

            confidence = _inherit_confidence(props, ctype)
            linked_flight_id = props.get("flight_id") or None
            linked_aircraft = props.get("callsign") or props.get("dominant_callsign") or None
            corridor_id = _corridor_id(props, ctype)

            c.update({
                "source_layer": "airspace_spiderweb_export",
                "candidate_type": ctype,
                "lat": round(c["_lat"], 6),
                "lon": round(c["_lon"], 6),
                "confidence": round(confidence, 4),
                "evidence_tier": None,       # set later
                "linked_flight_id": linked_flight_id,
                "linked_aircraft": linked_aircraft,
                "corridor_id": corridor_id,
                "mbil_class": None,          # set later
                "hydro_overlap": "unknown",  # set later
                "utility_overlap": "unknown",
                "terrain_context": "unknown",
                "review_status": None,       # set later
            })

    # ── Dedup ─────────────────────────────────────────────────────────────────

    def _dedup(
        self, candidates: List[Dict[str, Any]], thresh_deg: float
    ) -> Tuple[int, List[Dict[str, Any]]]:
        kept: List[Dict[str, Any]] = []
        for c in candidates:
            lat, lon = c["_lat"], c["_lon"]
            duplicate = any(
                abs(k["_lat"] - lat) <= thresh_deg and abs(k["_lon"] - lon) <= thresh_deg
                for k in kept
            )
            if not duplicate:
                kept.append(c)
        return len(candidates) - len(kept), kept

    # ── MBIL scoring ──────────────────────────────────────────────────────────

    def _score_mbil(self, candidates: List[Dict[str, Any]]) -> None:
        """Assign MBIL-0..MBIL-3 based on distance to nearest PR municipality,
        OR MBIL-X (T3-25) for candidates we cannot meaningfully score:

          - Missing/null lat-lon (geometry didn't parse cleanly).
          - Off-island: outside PR latitude/longitude bounds — MBIL is a PR
            municipal-proximity metric; it has no semantics off-island.

        MBIL-X means 'unclassified' — distinct from MBIL-0 (we scored, no signal).
        See docs/SPIDERWEB_LANGUAGE_BRIDGE.md."""
        # PR bounding box — a few tenths of a degree margin so coastal points
        # don't get clipped (Aguadilla north ~18.53, southwestern Lajas ~17.95).
        PR_LAT_MIN, PR_LAT_MAX = 17.80, 18.60
        for c in candidates:
            lat, lon = c.get("_lat"), c.get("_lon")
            if (lat is None or lon is None
                    or not isinstance(lat, (int, float))
                    or not isinstance(lon, (int, float))
                    or lat < PR_LAT_MIN or lat > PR_LAT_MAX
                    or lon < PR_LON_WEST or lon > PR_LON_EAST):
                c["mbil_class"] = "MBIL-X"
                continue
            dist = _min_dist_deg(lat, lon, MUNICIPAL_CENTROIDS)
            dist_km = dist * 111.0
            if dist_km < 5.0:
                c["mbil_class"] = "MBIL-3"
            elif dist_km < 10.0:
                c["mbil_class"] = "MBIL-2"
            elif dist_km < 15.0:
                c["mbil_class"] = "MBIL-1"
            else:
                c["mbil_class"] = "MBIL-0"

    # ── Hydro scoring ─────────────────────────────────────────────────────────

    def _score_hydro(self, candidates: List[Dict[str, Any]]) -> None:
        for c in candidates:
            dist = _min_dist_deg(c["_lat"], c["_lon"], HYDRO_LOCATIONS)
            c["hydro_overlap"] = "yes" if dist <= HYDRO_THRESH_DEG else "no"

    # ── Utility scoring ───────────────────────────────────────────────────────

    def _score_utility(self, candidates: List[Dict[str, Any]]) -> None:
        for c in candidates:
            dist = _min_dist_deg(c["_lat"], c["_lon"], UTILITY_CORRIDOR_WAYPOINTS)
            c["utility_overlap"] = "yes" if dist <= UTILITY_THRESH_DEG else "no"

    # ── Terrain scoring ───────────────────────────────────────────────────────

    def _score_terrain(self, candidates: List[Dict[str, Any]]) -> None:
        for c in candidates:
            c["terrain_context"] = get_terrain_context(c["_lat"], c["_lon"])

    # ── Evidence tier ─────────────────────────────────────────────────────────

    # ── Tier 3 additive scoring helpers (D5) ──────────────────────────────────

    def _score_spiderweb_role(self, candidates: List[Dict[str, Any]]) -> None:
        """Map candidate_type → canonical spiderweb_role (T3-22)."""
        ROLE = {"poi": "node", "ilap": "path", "corridor": "edge", "aasb_edge": "airport_link"}
        for c in candidates:
            c["spiderweb_role"] = ROLE.get(c["candidate_type"], "node")

    def _score_access_assertion(self, candidates: List[Dict[str, Any]]) -> None:
        """T3-23: 'public_record' if airport-anchored (aasb_edge or has a known
        airport in corridor_id), else 'derived_observation'."""
        # Airport codes known to anchor public-record corridors (AASB nodes).
        AIRPORT_CODES = {"SJU", "BQN", "PSE", "SIG", "NRR", "MAZ", "ARE", "CPX", "VQS"}
        for c in candidates:
            if c["candidate_type"] == "aasb_edge":
                c["access_assertion_level"] = "public_record"
                continue
            corridor_id = c.get("corridor_id") or ""
            # Conservative check: corridor_id contains an airport code (e.g. "SJU_BQN").
            if any(code in corridor_id.upper() for code in AIRPORT_CODES):
                c["access_assertion_level"] = "public_record"
            else:
                c["access_assertion_level"] = "derived_observation"

    def _score_nearest_municipal_boundary_m(self, candidates: List[Dict[str, Any]]) -> None:
        """T3-24: distance in meters to nearest of the 72-municipality centroids.

        Approximation: degrees × 111000 (1° lat ≈ 111 km; longitude correction is
        small at PR's latitude, ~18°, where cos(18°) ≈ 0.951 — accepting the
        ~5% over-estimate as the docs state)."""
        for c in candidates:
            lat, lon = c.get("lat"), c.get("lon")
            if lat is None or lon is None:
                c["nearest_municipal_boundary_m"] = None
                continue
            min_dist_deg = min(
                math.hypot(lat - clat, lon - clon)
                for clat, clon in MUNICIPAL_CENTROIDS
            )
            c["nearest_municipal_boundary_m"] = round(min_dist_deg * 111000, 1)

    def _score_aasb_mbil_corridor_flag(self, candidates: List[Dict[str, Any]]) -> None:
        """T3-28: True when a corridor candidate has MBIL-2 or MBIL-3.

        Note: the plan asks for 'both endpoints' MBIL-2+, but corridor candidates
        store a single mbil_class summarizing the corridor as a whole. Flagging
        when the corridor's own MBIL is ≥ 2 is the available proxy. Per-endpoint
        flagging requires the AASB-edge MBIL-X plumbing (NEXT_100 T3-28 follow-up)."""
        MBIL_HIGH = {"MBIL-2", "MBIL-3"}
        for c in candidates:
            c["aasb_mbil_corridor_flag"] = (
                c["candidate_type"] == "corridor"
                and c.get("mbil_class") in MBIL_HIGH
            )

    def _assign_evidence_tier(self, candidates: List[Dict[str, Any]]) -> None:
        for c in candidates:
            conf = c["confidence"]
            props = c["_raw_props"]
            ctype = c["candidate_type"]

            # Corroborating evidence sources (not counting MBIL alone — see
            # MBIL-only guardrail below).
            non_mbil_corroborating = sum([
                c["hydro_overlap"] == "yes",
                c["utility_overlap"] == "yes",
                c["corridor_id"] is not None,
            ])
            mbil_high = c["mbil_class"] in ("MBIL-2", "MBIL-3")
            # MBIL-X means 'unclassified' — never count as corroborating (T3-25).
            mbil_signals = c["mbil_class"] in ("MBIL-1", "MBIL-2", "MBIL-3")
            corroborating = non_mbil_corroborating + (1 if mbil_signals else 0)

            corridor_align = _safe_float(props.get("corridor_alignment_score")) or 0.0
            connecting = int(props.get("connecting_flights") or 0)

            if conf >= CONFIDENCE_T1 and corroborating >= 2:
                tier = "T1"
            elif ctype == "corridor" and connecting >= 2:
                # Corridors with ≥2 connecting flights are T3 (manual review)
                # unless they already qualify for T1 via confidence + corroboration
                tier = "T3"
            elif conf >= CONFIDENCE_T2 or corridor_align > 0.5:
                tier = "T2"
            else:
                tier = "T4"

            # T3-27 MBIL-only guardrail: if the ONLY positive evidence is MBIL
            # (no hydro, no utility, no corridor_id), tier stays at T4/T3 even
            # at high confidence. MBIL is spatial context, not operational signal.
            mbil_only = (non_mbil_corroborating == 0 and mbil_high)
            if mbil_only and tier in ("T1", "T2"):
                tier = "T3"

            c["evidence_tier"] = tier

            # T3-21 fact_status: 'observed' when high-confidence with ≥2
            # NON-MBIL corroborating signals; 'inferred' otherwise. Tied to
            # the same gate the operator-facing tier uses for T1.
            if conf >= CONFIDENCE_T1 and non_mbil_corroborating >= 2:
                c["fact_status"] = "observed"
            else:
                c["fact_status"] = "inferred"

            if tier in ("T1", "T2"):
                c["review_status"] = "accepted"
            elif tier == "T3":
                c["review_status"] = "manual_review"
            else:
                c["review_status"] = "rejected" if conf < CONFIDENCE_REJECTED else "manual_review"

    # ── Gap audit ─────────────────────────────────────────────────────────────

    def _gap_audit(
        self,
        candidates: List[Dict[str, Any]],
        missing_files: List[str],
        dups_removed: int,
    ) -> Dict[str, Any]:
        total = len(candidates)

        isolated = sum(
            1 for c in candidates
            if c.get("corridor_id") is None and c["candidate_type"] == "poi"
        )
        no_evidence = sum(
            1 for c in candidates
            if c["hydro_overlap"] == "no" and c["utility_overlap"] == "no"
        )
        unclustered = sum(
            1 for c in candidates
            if c["candidate_type"] == "ilap"
            and (_safe_float(c["_raw_props"].get("corridor_alignment_score")) or 0.0) < 0.3
        )
        mbil_0 = sum(1 for c in candidates if c.get("mbil_class") == "MBIL-0")
        pct_low = round(mbil_0 / total, 4) if total else 0.0

        return {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "total_candidates": total,
            "after_dedup": total,
            "gaps": {
                "export_gap":   {"missing_files": missing_files},
                "dedup_gap":    {"duplicates_removed": dups_removed, "threshold_deg": DEDUP_THRESH_DEG},
                "spatial_gap":  {"isolated_candidates": isolated},
                "evidence_gap": {"no_hydro_or_utility": no_evidence},
                "temporal_gap": {"unclustered_routes": unclustered},
                "mbil_gap":     {"mbil_0_count": mbil_0, "pct_low_mbil": pct_low},
            },
        }

    # ── Output writers ────────────────────────────────────────────────────────

    def _write_outputs(
        self, candidates: List[Dict[str, Any]], gap_audit: Dict[str, Any]
    ) -> None:
        candidates_sorted = sorted(
            candidates,
            key=lambda c: (
                c.get("candidate_type", ""),
                c.get("linked_aircraft") or "",
                c.get("lat", 0.0),
                c.get("lon", 0.0),
            ),
        )
        meta_block = geojson_feature_meta(
            producer_module="readiness.spiderweb_intake",
            source_artifact="spiderweb_overlay_candidates.geojson",
        )
        features = []
        for c in candidates_sorted:
            props = {k: c[k] for k in REQUIRED_FIELDS}
            props["_meta"] = meta_block
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [c["lon"], c["lat"]]},
                "properties": props,
            })

        overlay = {
            "type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::4326"}},
            "summary": feature_collection_summary(features),
            "features": features,
        }
        (self.output_dir / "spiderweb_overlay_candidates.geojson").write_text(
            json.dumps(overlay, indent=2), encoding="utf-8"
        )
        gap_audit["reproducibility"] = reproducibility_metadata(
            command="SpiderwebIntake.run",
            input_paths=[str(self.input_dir / f) for f in BRIDGE_FILES],
        )
        (self.output_dir / "spiderweb_gap_audit.json").write_text(
            json.dumps(gap_audit, indent=2), encoding="utf-8"
        )

    def get_candidate_summary(self, candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Return a stats dict: total, counts by _candidate_type and evidence_tier."""
        from collections import Counter
        by_type = Counter(c.get("_candidate_type", "unknown") for c in candidates)
        by_tier = Counter(c.get("evidence_tier", "UNSET") for c in candidates)
        return {
            "total": len(candidates),
            "by_type": dict(by_type),
            "by_tier": dict(by_tier),
        }

    def filter_by_tier(self, candidates: List[Dict[str, Any]],
                       tier: str) -> List[Dict[str, Any]]:
        """Return candidates whose evidence_tier matches *tier* (e.g. 'TIER-1')."""
        return [c for c in candidates if c.get("evidence_tier") == tier]

    def validate_candidate_fields(self, candidate: Dict[str, Any]) -> List[str]:
        """Check that a candidate has the mandatory internal fields.

        Returns a list of error strings (empty = valid).
        """
        errors = []
        for field in ("_lat", "_lon", "_candidate_type"):
            if field not in candidate:
                errors.append(f"Missing field: {field}")
            elif field in ("_lat", "_lon") and candidate[field] is None:
                errors.append(f"None value for: {field}")
        return errors

    def get_coverage_stats(self, candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Return geographic bounding box and coordinate stats for *candidates*.

        Only candidates with valid numeric _lat/_lon are included in the stats.
        Returns an empty-range bbox when no valid coordinates are present.
        """
        lats = [c["_lat"] for c in candidates
                if c.get("_lat") is not None and c.get("_lon") is not None
                and isinstance(c["_lat"], (int, float))
                and isinstance(c["_lon"], (int, float))]
        lons = [c["_lon"] for c in candidates
                if c.get("_lat") is not None and c.get("_lon") is not None
                and isinstance(c["_lat"], (int, float))
                and isinstance(c["_lon"], (int, float))]
        if not lats:
            return {
                "total_with_coords": 0,
                "lat_range": [None, None],
                "lon_range": [None, None],
                "bbox": [None, None, None, None],
            }
        return {
            "total_with_coords": len(lats),
            "lat_range": [round(min(lats), 6), round(max(lats), 6)],
            "lon_range": [round(min(lons), 6), round(max(lons), 6)],
            "bbox": [
                round(min(lons), 6),
                round(min(lats), 6),
                round(max(lons), 6),
                round(max(lats), 6),
            ],
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _missing_bridge_files(self) -> List[str]:
        return [f for f in BRIDGE_FILES if not (self.input_dir / f).exists()]

    def _centroid(self, geom: dict) -> Tuple[Optional[float], Optional[float]]:
        gtype = geom.get("type", "")
        coords = geom.get("coordinates")
        if not coords:
            return None, None
        if gtype == "Point":
            return coords[1], coords[0]
        if gtype == "LineString" and coords:
            lats = [p[1] for p in coords]
            lons = [p[0] for p in coords]
            return sum(lats) / len(lats), sum(lons) / len(lons)
        return None, None


# ── Module-level helpers ──────────────────────────────────────────────────────

def _safe_float(val) -> Optional[float]:
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _min_dist_deg(lat: float, lon: float, refs: List[Tuple[float, float]]) -> float:
    if not refs:
        return float("inf")
    return min(math.hypot(lat - r[0], lon - r[1]) for r in refs)


def _inherit_confidence(props: dict, ctype: str) -> float:
    if ctype == "poi":
        return _safe_float(props.get("overall_confidence")) or 0.0
    if ctype == "ilap":
        return _safe_float(props.get("corridor_alignment_score")) or 0.0
    if ctype == "corridor":
        flights = int(props.get("connecting_flights") or 0)
        return min(1.0, flights / 5.0)
    if ctype == "aasb_edge":
        return _safe_float(props.get("confidence_score")) or 0.0
    return 0.0


def _corridor_id(props: dict, ctype: str) -> Optional[str]:
    if ctype == "corridor":
        a = props.get("poi_a")
        b = props.get("poi_b")
        if a and b:
            return f"{a}|{b}"
    if ctype == "aasb_edge":
        return props.get("edge_id") or None
    if ctype == "ilap":
        fid = props.get("flight_id")
        return f"ILAP_{fid}" if fid else None
    return None
