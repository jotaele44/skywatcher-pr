"""Scoped RLSM extraction adapter for operator-uploaded screenshots.

Never synthesizes native trajectories or modifies the canonical flight corpus.
Every field and association is provisional until independently adjudicated.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Any


def _read_ocr(conn: sqlite3.Connection, screenshot_id: int) -> list[dict]:
    # Append-only OCR attempts: latest receipt per zone, no historical blending.
    return [dict(r) for r in conn.execute(
        """SELECT obs_id,zone,raw_text,confidence_mean,ocr_status FROM ocr_observations
           WHERE obs_id IN (
               SELECT MAX(obs_id) FROM ocr_observations WHERE screenshot_id=?
               GROUP BY zone
           ) ORDER BY zone""", (screenshot_id,))]


def provisional_fields(ocr_rows: list[dict]) -> tuple[dict, list[dict]]:
    """Build candidate fields without losing conflicting source observations."""
    from fr24.rlsm_extractors import (
        RE_ALT,
        RE_HEADING,
        RE_REG_C,
        RE_REG_N,
        RE_REG_OE,
        RE_SPEED_KT,
        RE_SPEED_MPH,
        _scan_text,
    )

    readable = [r for r in ocr_rows if r.get("ocr_status") == "ok" and (r.get("raw_text") or "").strip()]
    if not readable:
        return {}, [{"class": "SCOPE", "note": "no usable source OCR", "status": "UNRESOLVED"}]
    text = " ".join(r["raw_text"] for r in readable)
    parsed = _scan_text(text)
    raw_regs = sorted({
        m.group(0) for row in readable
        for pattern in (RE_REG_N, RE_REG_C, RE_REG_OE)
        for m in pattern.finditer(row["raw_text"])
    })
    conflicts = []
    if len(raw_regs) > 1:
        parsed.pop("registration", None)
        conflicts.append({
            "class": "IDENTITY", "field": "registration", "status": "UNRESOLVED",
            "raw_registration_candidates": raw_regs,
            "note": "multiple OCR registration strings; no selection is justified",
        })
    elif len(raw_regs) == 1:
        parsed["registration"] = raw_regs[0]

    # Conflicting same-unit UI values are not arbitrarily first-picked.
    for field, pattern in (("altitude_ft", RE_ALT), ("heading_deg", RE_HEADING),
                           ("speed_kt", RE_SPEED_KT), ("speed_kt", RE_SPEED_MPH)):
        values = {m.group(1) for row in readable for m in pattern.finditer(row["raw_text"])}
        if len(values) > 1:
            parsed.pop(field, None)
            conflicts.append({"class": "SCHEMA", "status": "UNRESOLVED",
                              "field": field, "raw_value_candidates": sorted(values),
                              "note": "multiple displayed values of one unit; no selection justified"})
    # Recover callsign independently from registration only when the UI labels it.
    # Generic callsign parsing from _scan_text remains available when no registration
    # suppresses it, but an explicit label can coexist with a visible registration.
    callsign_label_pattern = re.compile(
        r"\bCALLSIGN\s*[:#-]?\s*([A-Z0-9]{2,10})\b",
        re.I,
    )
    explicit_callsigns = {
        match.group(1).upper()
        for row in readable
        for match in callsign_label_pattern.finditer(row["raw_text"])
    }
    generic_callsign = parsed.get("callsign")
    callsign_candidates = set(explicit_callsigns)
    if generic_callsign:
        callsign_candidates.add(str(generic_callsign).upper())
    if len(callsign_candidates) == 1:
        parsed["callsign"] = next(iter(callsign_candidates))
    elif len(callsign_candidates) > 1:
        parsed.pop("callsign", None)
        conflicts.append({
            "class": "IDENTITY",
            "field": "callsign",
            "status": "UNRESOLVED",
            "raw_callsign_candidates": sorted(callsign_candidates),
            "note": "conflicting displayed callsign candidates; no selection is justified",
        })

    # A flight ID is eligible for MFL projection only with its explicit GUI label.
    flight_id_pattern = re.compile(
        r"\b(?:FLIGHT\s*ID|FR24\s*(?:FLIGHT\s*)?ID)\s*[:#-]?\s*([0-9a-f]{6,8})\b",
        re.I,
    )
    displayed_ids = sorted({
        match.group(1) for row in readable
        for match in flight_id_pattern.finditer(row["raw_text"])
    })
    if len(displayed_ids) == 1:
        parsed["source_flight_id_displayed"] = displayed_ids[0]
    elif len(displayed_ids) > 1:
        conflicts.append({
            "class": "IDENTITY", "field": "source_flight_id_displayed",
            "status": "UNRESOLVED", "raw_flight_id_candidates": displayed_ids,
            "note": "conflicting explicit displayed flight IDs",
        })
    # Never equate displayed height/speed with whole-flight maximums.
    result = {}
    for field, value in parsed.items():
        supporting = [r for r in readable if (
            (field == "registration" and value in r["raw_text"]) or
            (field == "source_flight_id_displayed" and
             any(m.group(1) == value for m in flight_id_pattern.finditer(r["raw_text"]))) or
            (field == "callsign" and (
                any(m.group(1).upper() == str(value).upper()
                    for m in callsign_label_pattern.finditer(r["raw_text"]))
                or str(value) in r["raw_text"]
            )) or
            (field not in {"registration", "source_flight_id_displayed", "callsign"})
        )]
        result[field] = {
            "value": value,
            "evidence_state": "INFERENCE",
            "certification": "CANDIDATE_NOT_IDENTITY",
            "source_ocr_ids": [r["obs_id"] for r in supporting],
            "raw_excerpts": [{"zone": r["zone"], "text": r["raw_text"]} for r in supporting],
            "ocr_confidence_mean": (
                sum(float(r["confidence_mean"]) for r in supporting if r["confidence_mean"] is not None)
                / max(1, sum(r["confidence_mean"] is not None for r in supporting))
            ),
        }
    return result, conflicts


def _perceptual_duplicate_candidates(
    conn: sqlite3.Connection,
    screenshot_id: int,
    phash: str | None,
    *,
    threshold: int = 4,
) -> list[dict]:
    """Return the complete local pHash-neighborhood as discovery-only evidence."""
    if not phash:
        return []
    from scripts.rlsm_inventory import hamming_distance

    candidates = []
    rows = conn.execute(
        """SELECT screenshot_id,sha256,filename,rel_path,phash
           FROM screenshots
           WHERE screenshot_id<>? AND phash IS NOT NULL
           ORDER BY screenshot_id""",
        (screenshot_id,),
    ).fetchall()
    for row in rows:
        distance = hamming_distance(phash, row["phash"])
        if distance <= threshold:
            candidates.append({
                "screenshot_id": int(row["screenshot_id"]),
                "sha256": row["sha256"],
                "filename_raw": row["filename"],
                "rel_path": row["rel_path"],
                "phash": row["phash"],
                "hamming_distance": distance,
                "relationship": "PERCEPTUAL_SIMILARITY_DISCOVERY_ONLY",
                "certification": "CANDIDATE_NOT_IDENTITY",
            })
    return candidates


def _rendered_track_observation(image_path: Path) -> dict:
    """Observe the rendered FR24 trail without promoting it to raw trajectory."""
    try:
        from fr24.track_vectorizer import vectorize_image
    except ImportError as exc:
        return {
            "status": "BLOCKED_DEPENDENCY",
            "evidence_type": "RENDERED_TRAIL",
            "raw_trajectory": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    try:
        features = vectorize_image(str(image_path))
    except Exception as exc:  # detector failure is isolated from OCR extraction
        return {
            "status": "BLOCKED",
            "evidence_type": "RENDERED_TRAIL",
            "raw_trajectory": False,
            "error": f"{type(exc).__name__}: {exc}"[:300],
        }
    if features is None:
        return {
            "status": "UNRESOLVED_NO_DETECTED_COMPONENT",
            "evidence_type": "RENDERED_TRAIL",
            "raw_trajectory": False,
            "certification": "UNRESOLVED",
            "note": "detector found no qualifying rendered-trail component; absence is not certified",
        }
    return {
        "status": "OBSERVED",
        "evidence_type": "RENDERED_TRAIL",
        "raw_trajectory": False,
        "path_shape": features.path_shape,
        "has_loop": bool(features.has_loop),
        "has_orbit": bool(features.has_orbit),
        "has_gap": bool(features.has_gap),
        "track_length_px": features.track_length_px,
        "bbox": list(features.bbox),
        "component_count": features.component_count,
        "confidence": features.confidence,
        "certification": "PROVISIONAL_PIXEL_OBSERVATION",
    }


def _persisted_georeference_evidence(
    conn: sqlite3.Connection,
    screenshot_id: int,
) -> list[dict]:
    """Read, never synthesize, supported georeference receipts already in RLSM."""
    exists = conn.execute(
        """SELECT 1 FROM sqlite_master
           WHERE type='table' AND name='screenshot_georeferences'"""
    ).fetchone()
    if not exists:
        return []
    rows = conn.execute(
        """SELECT georef_version,status,method,viewport_profile,anchor_count,
                  scale_m_per_px,fit_residual_m,zoom_rung,zoom_support,
                  confidence,estimated_error_m,observed_at
           FROM screenshot_georeferences
           WHERE screenshot_id=?
           ORDER BY georef_version""",
        (screenshot_id,),
    ).fetchall()
    return [
        {
            **dict(row),
            "evidence_state": "COMPUTED",
            "certification": (
                "PROVISIONAL_SUPPORTED_GEOREFERENCE"
                if row["status"] == "located"
                else "UNRESOLVED"
            ),
        }
        for row in rows
    ]


def _discover_corpus_candidates(corpus_db: Path, fields: dict) -> tuple[list[dict], str]:
    """Preserve the full union of exact displayed-source-ID and callsign candidates."""
    callsign = fields.get("callsign", {}).get("value")
    source_flight_id = fields.get("source_flight_id_displayed", {}).get("value")
    if not callsign and not source_flight_id:
        return [], "NOT_QUERIED_NO_SUPPORTED_IDENTITY_FIELD"
    if not corpus_db.is_file():
        return [], "BLOCKED_CORPUS_UNAVAILABLE"

    conn = sqlite3.connect(f"file:{corpus_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(flight_corpus_records)")
        }
        required = {
            "corpus_record_id",
            "snapshot_id",
            "corpus_uid",
            "callsign_raw",
            "start_time_utc",
            "end_time_utc",
        }
        if not required <= columns:
            raise RuntimeError("canonical corpus tables unavailable for reconciliation")

        source_id_supported = "source_flight_id_raw" in columns
        select_source_id = (
            "source_flight_id_raw"
            if source_id_supported
            else "NULL AS source_flight_id_raw"
        )
        candidate_map: dict[int, dict[str, Any]] = {}

        def add_rows(rows: list[sqlite3.Row], basis: str) -> None:
            for row in rows:
                record_id = int(row["corpus_record_id"])
                candidate = candidate_map.setdefault(
                    record_id,
                    {
                        **dict(row),
                        "match_basis": [],
                        "association_status": "CANDIDATE_NOT_IDENTITY",
                    },
                )
                if basis not in candidate["match_basis"]:
                    candidate["match_basis"].append(basis)

        if source_flight_id and source_id_supported:
            rows = conn.execute(
                f"""SELECT corpus_record_id,snapshot_id,corpus_uid,{select_source_id},
                           callsign_raw,start_time_utc,end_time_utc
                    FROM flight_corpus_records
                    WHERE LOWER(TRIM(source_flight_id_raw))=LOWER(TRIM(?))
                    ORDER BY snapshot_id,corpus_record_id""",
                (source_flight_id,),
            ).fetchall()
            add_rows(rows, "EXACT_DISPLAYED_SOURCE_FLIGHT_ID")

        if callsign:
            rows = conn.execute(
                f"""SELECT corpus_record_id,snapshot_id,corpus_uid,{select_source_id},
                           callsign_raw,start_time_utc,end_time_utc
                    FROM flight_corpus_records
                    WHERE UPPER(TRIM(callsign_raw))=UPPER(TRIM(?))
                    ORDER BY snapshot_id,corpus_record_id""",
                (callsign,),
            ).fetchall()
            add_rows(rows, "EXACT_DISPLAYED_CALLSIGN")

        state = (
            "QUERIED"
            if not source_flight_id or source_id_supported
            else "QUERIED_CALLSIGN_ONLY_SOURCE_ID_COLUMN_UNAVAILABLE"
        )
        candidates = sorted(
            candidate_map.values(),
            key=lambda row: (int(row["snapshot_id"]), int(row["corpus_record_id"])),
        )
        return candidates, state
    except sqlite3.OperationalError as exc:
        raise RuntimeError("canonical corpus tables unavailable for reconciliation") from exc
    finally:
        conn.close()

def extract_into_rlsm(
    image_path: Path,
    expected_sha: str,
    root: Path,
    rlsm_db: Path,
    corpus_db: Path,
    *,
    filename_raw: str | None = None,
    reprocess_existing: bool = False,
    perceptual_duplicate_mode: str = "off",
    rendered_track_mode: str = "off",
    georeference_mode: str = "existing_only",
) -> dict[str, Any]:
    import PIL.Image

    from fr24 import rlsm_ocr
    from skywatcher.fr24.screenshot_metadata import parse_filename_timestamp

    if perceptual_duplicate_mode not in {"off", "discover"}:
        raise ValueError("unsupported perceptual_duplicate_mode")
    if rendered_track_mode not in {"off", "local"}:
        raise ValueError("unsupported rendered_track_mode")
    if georeference_mode not in {"off", "existing_only"}:
        raise ValueError("unsupported georeference_mode")

    if not shutil.which("tesseract") or rlsm_ocr.pytesseract is None:
        return {"status": "BLOCKED", "error": "local Tesseract is not installed"}
    if not image_path.is_file() or image_path.is_symlink():
        return {"status": "BLOCKED", "error": "source image missing or linked"}
    data = image_path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_sha:
        return {"status": "BLOCKED", "error": "source bytes changed after inventory"}
    PIL.Image.MAX_IMAGE_PIXELS = 20_000_000
    width = height = None
    phash = None
    try:
        with PIL.Image.open(image_path) as image:
            width, height = image.size
            if width * height > 20_000_000:
                return {"status": "BLOCKED", "error": "pixel budget exceeded"}
            image.verify()
        if perceptual_duplicate_mode == "discover":
            from scripts.rlsm_inventory import ahash_8x8
            with PIL.Image.open(image_path) as image:
                image.load()
                phash = ahash_8x8(image)
    except (OSError, ValueError, PIL.Image.DecompressionBombError):
        return {"status": "BLOCKED", "error": "unsupported or corrupt image format"}

    try:
        relative = image_path.resolve(strict=True).relative_to(root.resolve()).as_posix()
    except ValueError:
        return {"status": "BLOCKED", "error": "RLSM images must remain under the repository root"}
    rlsm_db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(rlsm_db, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        existing_schema = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='screenshots'"
        ).fetchone()
        if not existing_schema:
            schema = (root / "data" / "rlsm" / "schema.sql")
            if not schema.is_file():
                return {"status": "BLOCKED", "error": "RLSM schema.sql is missing"}
            conn.executescript(schema.read_text(encoding="utf-8"))
        required_tables = {"screenshots", "source_manifestations", "processing_runs", "ocr_observations"}
        present = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not required_tables <= present:
            return {"status": "BLOCKED", "error": "RLSM database requires migration"}

        row = conn.execute(
            "SELECT screenshot_id,ocr_status,phash,width,height FROM screenshots WHERE sha256=?",
            (expected_sha,),
        ).fetchone()
        reused = row is not None
        if row is None:
            cursor = conn.execute(
                """INSERT INTO screenshots
                   (sha256,filename,rel_path,month_bucket,filename_ts,ext,size_bytes,
                    width,height,phash,ingest_status,ocr_status,source_availability,ingested_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))""",
                (expected_sha, filename_raw or image_path.name, relative, None,
                 parse_filename_timestamp(filename_raw or image_path.name),
                 image_path.suffix.lower(), len(data), width, height, phash,
                 "ok", "pending", "present")
            )
            screenshot_id = int(cursor.lastrowid)
        else:
            screenshot_id = int(row["screenshot_id"])
            if phash and not row["phash"]:
                conn.execute(
                    "UPDATE screenshots SET phash=?,width=COALESCE(width,?),height=COALESCE(height,?) "
                    "WHERE screenshot_id=?",
                    (phash, width, height, screenshot_id),
                )
        conn.execute(
            """INSERT OR IGNORE INTO source_manifestations
               (rel_path,sha256,screenshot_id,filename,ext,size_bytes,
                manifestation_role,source_availability,observed_at)
               VALUES (?,?,?,?,?,?,?,'present',datetime('now'))""",
            (relative, expected_sha, screenshot_id, filename_raw or image_path.name,
             image_path.suffix.lower(), len(data),
             "duplicate_payload" if reused else "canonical_payload")
        )
        conn.commit()
        perceptual_duplicates = (
            _perceptual_duplicate_candidates(conn, screenshot_id, phash)
            if perceptual_duplicate_mode == "discover"
            else []
        )
        rendered_track = (
            _rendered_track_observation(image_path)
            if rendered_track_mode == "local"
            else {"status": "NOT_REQUESTED"}
        )
        georeference_evidence = (
            _persisted_georeference_evidence(conn, screenshot_id)
            if georeference_mode == "existing_only"
            else []
        )
        if row is None or row["ocr_status"] != "ok" or reprocess_existing:
            run_id = conn.execute(
                """INSERT INTO processing_runs
                   (run_kind,started_at,status,n_inputs,n_processed,n_failed)
                   VALUES ('ocr',datetime('now'),'in_progress',1,0,0)"""
            ).lastrowid
            conn.commit()
            receipt = rlsm_ocr.process_screenshot(conn, screenshot_id, relative, run_id)
            conn.execute(
                """UPDATE processing_runs SET ended_at=datetime('now'),
                   status=?,n_processed=?,n_failed=?,notes=? WHERE run_id=?""",
                ("completed" if receipt.get("ok") else "failed",
                 int(bool(receipt.get("ok"))), int(not receipt.get("ok")),
                 str(receipt.get("reason") or ""), run_id)
            )
            conn.commit()
            if not receipt.get("ok"):
                return {
                    "status": "BLOCKED", "screenshot_id": screenshot_id,
                    "was_reused": reused, "error": receipt.get("reason", "OCR failed"),
                    "perceptual_duplicates": perceptual_duplicates,
                    "rendered_track": rendered_track,
                    "georeference_evidence": georeference_evidence,
                }
        ocr = _read_ocr(conn, screenshot_id)
        fields, contradictions = provisional_fields(ocr)
        if not any(row.get("ocr_status") == "ok" and (row.get("raw_text") or "").strip() for row in ocr):
            return {
                "status": "BLOCKED", "screenshot_id": screenshot_id,
                "was_reused": reused, "contradictions": contradictions,
                "error": "OCR produced no usable text; negative evidence is unverified",
                "perceptual_duplicates": perceptual_duplicates,
                "rendered_track": rendered_track,
                "georeference_evidence": georeference_evidence,
            }
        candidates, query_state = _discover_corpus_candidates(corpus_db, fields)
        if query_state != "QUERIED":
            contradictions.append({"class": "SCOPE", "status": "OPEN",
                                   "note": query_state + ": candidate absence cannot be treated as a negative search"})
        return {
            "status": "NEEDS_REVIEW" if fields else "EXTRACTED_EMPTY",
            "screenshot_id": screenshot_id, "was_reused": reused,
            "fields": fields, "contradictions": contradictions,
            "candidates": candidates,
            "perceptual_duplicates": perceptual_duplicates,
            "rendered_track": rendered_track,
            "georeference_evidence": georeference_evidence,
        }
    finally:
        conn.close()
