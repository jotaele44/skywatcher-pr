"""Skywatcher FPIM: flight path and behavior context only.

FPIM owns aircraft-identity resolution (skywatcher.fpim.aircraft_profile),
route/track extraction and behavior detection (fr24/route_extractor.py,
track_vectorizer.py, flight_fusion.py, wave_validator.py, endpoint_matcher.py),
and POI tracing (skywatcher.correlation.footprint_proximity): enumerating
every point of interest — any geographical point, natural or manmade, of
interest to humans — along or near a flight path, regardless of the POI's
relevance/correlation to the aircraft or any flight-behavior label.

FPIM's detection and POI-tracing logic must never branch on callsign,
known-operator, or mission labels to decide *whether* a track gets analyzed —
labeled and unlabeled/unknown tracks are treated identically.

FPIM does not import from satim or corrim, and its public surface
intentionally excludes skywatcher.legacy.quarantined_mission_inference
(heuristic mission/intent deduction), which is quarantined for backward
compatibility only. See docs/MODULE_SPEC_FPIM.md and
docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md.
"""
