"""SKYWATCHER FR24 INGEST PACKAGE

Consolidated, canonical home for FlightRadar24 (FR24) screenshot-processing
ownership in Skywatcher. This package is the single import surface for the
FR24 screenshot pipeline responsibilities that were previously scattered across
top-level ``fr24/*`` modules and ``integration/geo_calibration.py`` (and, before
the repository-boundary correction, duplicated in ``spiderweb-pr``).

Ownership map (mission responsibilities 1-18):

    screenshot_source      -> source abstraction (1), extension validation (2)
    screenshot_identity    -> SHA-256 screenshot identity (3)
    flightradar24_ocr      -> FR24 OCR abstraction (4)
    ocr_normalization      -> OCR observation normalization (5)
    telemetry_parser       -> telemetry field parsing (6), coordinate parsing +
                              confidence (7)
    screenshot_metadata    -> screenshot metadata extraction (8)
    flight_reconstruction  -> association (9), reconstruction (10),
                              track-point construction (11)
    duplicate_detection    -> duplicate detection (12)
    telemetry_validation   -> error/failure accounting (13),
                              schema validation (17)
    review_status          -> review-status handling (14)
    mission_classification -> gated mission classification
                              (speculative-until-evidence-gated policy)
    database               -> database schema (15)
    database_migrations    -> database initialization + migrations (16)
    spiderweb_export       -> Skywatcher canonical export + Spiderweb bridge
                              serialization (18)

The modules here wrap and re-export the existing, tested implementations rather
than duplicating logic, so the pre-existing ``fr24/*`` test suite continues to
pass while this package provides the consolidated boundary the mission requires.
"""

from __future__ import annotations

__all__ = [
    "screenshot_source",
    "screenshot_identity",
    "flightradar24_ocr",
    "ocr_normalization",
    "telemetry_parser",
    "screenshot_metadata",
    "flight_reconstruction",
    "duplicate_detection",
    "telemetry_validation",
    "review_status",
    "mission_classification",
    "database",
    "database_migrations",
    "spiderweb_export",
]

FR24_INGEST_PACKAGE_VERSION = "skywatcher_fr24_ingest_v1.0.0"
