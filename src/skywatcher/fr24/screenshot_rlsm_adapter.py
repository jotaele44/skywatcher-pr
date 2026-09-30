"""Scoped RLSM extraction adapter for operator-uploaded screenshots.

Never synthesizes native trajectories or modifies the canonical flight corpus.
Every field and association is provisional until independently adjudicated.
"""
from __future__ import annotations

import hashlib
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
    from fr24.rlsm_extractors import RE_REG_N, RE_REG_C, RE_REG_OE, _scan_text

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
            "class": "IDENTITY", "status": "UNRESOLVED",
            "raw_registration_candidates": raw_regs,
            "note": "multiple OCR registration strings; no selection is justified",
        })
    elif len(raw_regs) == 1:
        parsed["registration"] = raw_regs[0]

    # Never equate displayed height/speed with whole-flight maximums.
    result = {}
    for field, value in parsed.items():
        supporting = [r for r in readable if (
            (field == "registration" and value in r["raw_text"]) or
            (field != "registration")
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


def _discover_corpus_candidates(corpus_db: Path, fields: dict) -> list[dict]:
    # Callsign is discovery only; registration is never equated to callsign.
    candidate = fields.get("callsign", {}).get("value")
    if not candidate or not corpus_db.is_file():
        return []
    conn = sqlite3.connect(f"file:{corpus_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT corpus_record_id,snapshot_id,corpus_uid,callsign_raw,
               start_time_utc,end_time_utc FROM flight_corpus_records
               WHERE callsign_raw=? ORDER BY snapshot_id,corpus_record_id""",
            (candidate,)
        ).fetchall()
        return [dict(row) for row in rows]  # No arbitrary candidate truncation.
    except sqlite3.OperationalError:
        # Schema absent is a genuine missing dependency, not an empty match universe.
        raise RuntimeError("canonical corpus tables unavailable for reconciliation")
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
) -> dict[str, Any]:
    import PIL.Image
    from fr24 import rlsm_ocr
    from skywatcher.fr24.screenshot_metadata import parse_filename_timestamp

    if not shutil.which("tesseract") or rlsm_ocr.pytesseract is None:
        return {"status": "BLOCKED", "error": "local Tesseract is not installed"}
    if not image_path.is_file() or image_path.is_symlink():
        return {"status": "BLOCKED", "error": "source image missing or linked"}
    data = image_path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_sha:
        return {"status": "BLOCKED", "error": "source bytes changed after inventory"}
    PIL.Image.MAX_IMAGE_PIXELS = 20_000_000
    try:
        with PIL.Image.open(image_path) as image:
            if image.width * image.height > 20_000_000:
                return {"status": "BLOCKED", "error": "pixel budget exceeded"}
            image.verify()
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

        row = conn.execute("SELECT screenshot_id,ocr_status FROM screenshots WHERE sha256=?",
                           (expected_sha,)).fetchone()
        reused = row is not None
        if row is None:
            cursor = conn.execute(
                """INSERT INTO screenshots
                   (sha256,filename,rel_path,month_bucket,filename_ts,ext,size_bytes,
                    ingest_status,ocr_status,source_availability,ingested_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,datetime('now'))""",
                (expected_sha, filename_raw or image_path.name, relative, None,
                 parse_filename_timestamp(filename_raw or image_path.name),
                 image_path.suffix.lower(), len(data), "ok", "pending", "present")
            )
            screenshot_id = int(cursor.lastrowid)
        else:
            screenshot_id = int(row["screenshot_id"])
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
        if row is None or row["ocr_status"] != "ok":
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
                }
        ocr = _read_ocr(conn, screenshot_id)
        fields, contradictions = provisional_fields(ocr)
        if not any(row.get("ocr_status") == "ok" and (row.get("raw_text") or "").strip() for row in ocr):
            return {
                "status": "BLOCKED", "screenshot_id": screenshot_id,
                "was_reused": reused, "contradictions": contradictions,
                "error": "OCR produced no usable text; negative evidence is unverified",
            }
        candidates = _discover_corpus_candidates(corpus_db, fields)
        return {
            "status": "NEEDS_REVIEW" if fields else "EXTRACTED_EMPTY",
            "screenshot_id": screenshot_id, "was_reused": reused,
            "fields": fields, "contradictions": contradictions,
            "candidates": candidates,
        }
    finally:
        conn.close()
