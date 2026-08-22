"""Empirical, corpus-bound calibration gate for RLSM OCR.

Calibration reads a frozen, human-labeled manifest and runs the *current* OCR
configuration without writing production ``ocr_observations``. A PASS is bound
to the latest corpus digest; a later corpus freeze invalidates it automatically.

The acceptance thresholds are evidence inputs in the frozen manifest, not
silent constants in code. A calibration outcome also refreshes the separate
``RLSM_MASS_OCR_READY`` gate, so production workers cannot start merely because
one component gate passed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

from PIL import Image, ImageOps

from fr24.rlsm_corpus_ingest import (
    DB_PATH,
    MASS_OCR_GATE,
    OCR_GATE,
    REPO,
    ensure_corpus_schema,
    refresh_mass_ocr_gate,
    sha256_file,
    stable_json,
    utc_now,
)
from fr24.rlsm_ocr import _ocr_zone, _tess_lang
from fr24.rlsm_preprocess import scale_for
from fr24.rlsm_source_availability import open_stable_source
from fr24.rlsm_zones import ZONE_OCR_CONFIG, zones_for

CALIBRATION_PROTOCOL = "rlsm-ocr-calibration-v1.0"
DEFAULT_OUTPUT = REPO / "outputs" / "rlsm_calibration"


class CalibrationBlocked(RuntimeError):
    pass


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    if len(a) > len(b):
        a, b = b, a
    previous = list(range(len(a) + 1))
    for j, cb in enumerate(b, 1):
        current = [j]
        for i, ca in enumerate(a, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[i] + 1,
                    previous[i - 1] + (ca != cb),
                )
            )
        previous = current
    return previous[-1]


def _cer(expected: str, observed: str) -> float:
    return _levenshtein(expected, observed) / max(1, len(expected))


def _manifest_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bounded_rate(acceptance: dict, key: str) -> float:
    try:
        value = float(acceptance[key])
    except (TypeError, ValueError) as exc:
        raise CalibrationBlocked(f"acceptance {key} must be numeric") from exc
    if not 0.0 <= value <= 1.0:
        raise CalibrationBlocked(f"acceptance {key} must be within [0, 1]")
    return value


def _validate_manifest(data: dict) -> None:
    required = {"schema_version", "corpus_digest", "acceptance", "cases"}
    missing = sorted(required - set(data))
    if missing:
        raise CalibrationBlocked("manifest missing fields: " + ", ".join(missing))
    if data["schema_version"] != CALIBRATION_PROTOCOL:
        raise CalibrationBlocked(
            f"schema_version must be {CALIBRATION_PROTOCOL!r}; got {data['schema_version']!r}"
        )
    acceptance = data["acceptance"]
    if not isinstance(acceptance, dict):
        raise CalibrationBlocked("acceptance must be an object")
    for key in (
        "min_cases",
        "min_zone_exact_rate",
        "max_mean_char_error_rate",
        "max_hard_negative_false_positive_rate",
        "required_strata",
    ):
        if key not in acceptance:
            raise CalibrationBlocked(f"acceptance missing {key}")

    try:
        min_cases = int(acceptance["min_cases"])
    except (TypeError, ValueError) as exc:
        raise CalibrationBlocked("acceptance min_cases must be an integer") from exc
    if min_cases < 2:
        raise CalibrationBlocked("acceptance min_cases must be at least 2")
    _bounded_rate(acceptance, "min_zone_exact_rate")
    _bounded_rate(acceptance, "max_mean_char_error_rate")
    _bounded_rate(acceptance, "max_hard_negative_false_positive_rate")
    required_strata = acceptance["required_strata"]
    if not isinstance(required_strata, list) or not required_strata:
        raise CalibrationBlocked("acceptance required_strata must be a non-empty list")

    cases = data["cases"]
    if not isinstance(cases, list) or not cases:
        raise CalibrationBlocked("cases must be a non-empty list")
    if min_cases > len(cases):
        raise CalibrationBlocked("acceptance min_cases exceeds the frozen case count")

    seen: set[tuple[int, str]] = set()
    roles: set[str] = set()
    for index, case in enumerate(cases):
        for key in (
            "screenshot_id",
            "sha256",
            "screenshot_family",
            "orientation",
            "case_role",
            "zones",
        ):
            if key not in case:
                raise CalibrationBlocked(f"case[{index}] missing {key}")
        role = str(case["case_role"])
        if role not in {"positive", "hard_negative"}:
            raise CalibrationBlocked(f"case[{index}] has invalid case_role")
        roles.add(role)
        if not isinstance(case["zones"], dict) or not case["zones"]:
            raise CalibrationBlocked(f"case[{index}].zones must be non-empty")
        identity = (int(case["screenshot_id"]), str(case["sha256"]))
        if identity in seen:
            raise CalibrationBlocked(f"duplicate calibration identity: {identity}")
        seen.add(identity)
    if roles != {"positive", "hard_negative"}:
        raise CalibrationBlocked(
            "calibration corpus must contain both positive and hard_negative cases"
        )


def _latest_pass_digest(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        """SELECT corpus_digest FROM corpus_freeze_runs
           WHERE status='PASS' AND corpus_digest IS NOT NULL
           ORDER BY corpus_run_id DESC LIMIT 1"""
    ).fetchone()
    if not row:
        raise CalibrationBlocked("no PASS corpus freeze is available")
    return str(row[0])


def _ocr_case(path: Path) -> tuple[dict[str, str], dict[str, float]]:
    with open_stable_source(path) as source_handle, Image.open(source_handle) as image:
        image.load()
        image = ImageOps.exif_transpose(image)
        zones = zones_for(*image.size)
        crops = {zone.name: image.crop(zone.crop_box()) for zone in zones}

    language = _tess_lang()
    texts: dict[str, str] = {}
    confidences: dict[str, float] = {}
    for zone in zones:
        cfg = ZONE_OCR_CONFIG.get(
            zone.name, {"psm": 6, "preprocess": "high_contrast"}
        )
        psm = int(cfg.get("psm", 6))
        mode = str(cfg.get("preprocess", "none"))
        scale = scale_for(mode, cfg.get("scale"))
        config = f"--oem 1 --psm {psm} -l {language}"
        raw_text, _boxes, conf_mean, _conf_min, _n_words = _ocr_zone(
            crops[zone.name], zone, config, mode=mode, scale=scale
        )
        texts[zone.name] = raw_text
        confidences[zone.name] = conf_mean
    return texts, confidences


def _hard_negative_identity_false_positive(texts: dict[str, str]) -> bool:
    # Import lazily: this is precisely the downstream parser being calibrated.
    from fr24.rlsm_extractors import _scan_text

    parsed = _scan_text(" ".join(texts.values()))
    return bool(parsed.get("registration") or parsed.get("callsign"))


def _upsert_gate(
    conn: sqlite3.Connection,
    *,
    status: str,
    corpus_digest: str,
    evidence_sha256: str | None,
    detail: str,
) -> None:
    conn.execute(
        """INSERT INTO pipeline_certifications
           (gate_name, status, bound_corpus_digest, evidence_sha256, decided_at, detail)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(gate_name) DO UPDATE SET
             status=excluded.status,
             bound_corpus_digest=excluded.bound_corpus_digest,
             evidence_sha256=excluded.evidence_sha256,
             decided_at=excluded.decided_at,
             detail=excluded.detail""",
        (OCR_GATE, status, corpus_digest, evidence_sha256, utc_now(), detail),
    )
    conn.commit()


def _refresh_mass_gate(conn: sqlite3.Connection, corpus_digest: str) -> bool:
    ready = refresh_mass_ocr_gate(conn, corpus_digest=corpus_digest)
    conn.commit()
    return ready


def run(
    manifest_path: Path,
    *,
    db_path: Path = DB_PATH,
    repo_root: Path = REPO,
    output_dir: Path = DEFAULT_OUTPUT,
) -> dict:
    manifest_path = manifest_path.expanduser().resolve()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    _validate_manifest(data)
    manifest_hash = _manifest_sha256(manifest_path)

    conn = sqlite3.connect(db_path, timeout=60.0)
    conn.execute("PRAGMA foreign_keys=ON")
    ensure_corpus_schema(conn)
    corpus_digest = _latest_pass_digest(conn)
    if str(data["corpus_digest"]) != corpus_digest:
        _upsert_gate(
            conn,
            status="BLOCKED",
            corpus_digest=corpus_digest,
            evidence_sha256=manifest_hash,
            detail="calibration manifest is bound to a different corpus digest",
        )
        _refresh_mass_gate(conn, corpus_digest)
        conn.close()
        raise CalibrationBlocked(
            "calibration manifest corpus_digest does not match latest PASS freeze"
        )

    acceptance = data["acceptance"]
    results: list[dict] = []
    hard_negative_total = 0
    hard_negative_fp = 0
    zone_total = 0
    zone_exact = 0
    cer_values: list[float] = []
    strata: set[str] = set()

    try:
        for case in data["cases"]:
            screenshot_id = int(case["screenshot_id"])
            expected_sha = str(case["sha256"])
            row = conn.execute(
                """SELECT sha256, rel_path, source_availability
                   FROM screenshots WHERE screenshot_id=?""",
                (screenshot_id,),
            ).fetchone()
            if not row:
                raise CalibrationBlocked(f"unknown screenshot_id {screenshot_id}")
            database_sha, rel_path, availability = map(str, row)
            if database_sha != expected_sha:
                raise CalibrationBlocked(
                    f"screenshot {screenshot_id} SHA differs from calibration manifest"
                )
            if availability not in {"present", "restored"}:
                raise CalibrationBlocked(
                    f"screenshot {screenshot_id} source is {availability}"
                )
            source = repo_root / rel_path
            if not source.is_file():
                raise CalibrationBlocked(
                    f"screenshot {screenshot_id} source is missing: {rel_path}"
                )
            if sha256_file(source) != expected_sha:
                raise CalibrationBlocked(
                    f"screenshot {screenshot_id} source bytes no longer match SHA-256"
                )

            observed, confidences = _ocr_case(source)
            case_zone_results = []
            for zone, expected_text in sorted(case["zones"].items()):
                observed_text = observed.get(zone)
                if observed_text is None:
                    raise CalibrationBlocked(
                        f"screenshot {screenshot_id} expected unknown zone {zone!r}"
                    )
                expected_text = str(expected_text)
                error_rate = _cer(expected_text, observed_text)
                exact = observed_text == expected_text
                zone_total += 1
                zone_exact += int(exact)
                cer_values.append(error_rate)
                case_zone_results.append(
                    {
                        "zone": zone,
                        "expected_raw": expected_text,
                        "observed_raw": observed_text,
                        "exact": exact,
                        "char_error_rate": error_rate,
                        "ocr_confidence_mean": confidences.get(zone),
                    }
                )

            role = str(case["case_role"])
            negative_fp = False
            if role == "hard_negative":
                hard_negative_total += 1
                negative_fp = _hard_negative_identity_false_positive(observed)
                hard_negative_fp += int(negative_fp)

            stratum = f"{case['screenshot_family']}|{case['orientation']}|{role}"
            strata.add(stratum)
            results.append(
                {
                    "screenshot_id": screenshot_id,
                    "sha256": expected_sha,
                    "screenshot_family": case["screenshot_family"],
                    "orientation": case["orientation"],
                    "case_role": role,
                    "stratum": stratum,
                    "hard_negative_identity_false_positive": negative_fp,
                    "zones": case_zone_results,
                }
            )

        case_count = len(results)
        zone_exact_rate = zone_exact / max(1, zone_total)
        mean_cer = sum(cer_values) / max(1, len(cer_values))
        negative_fp_rate = hard_negative_fp / hard_negative_total
        missing_strata = sorted(set(map(str, acceptance["required_strata"])) - strata)
        checks = {
            "min_cases": case_count >= int(acceptance["min_cases"]),
            "required_strata": not missing_strata,
            "min_zone_exact_rate": zone_exact_rate
            >= float(acceptance["min_zone_exact_rate"]),
            "max_mean_char_error_rate": mean_cer
            <= float(acceptance["max_mean_char_error_rate"]),
            "max_hard_negative_false_positive_rate": negative_fp_rate
            <= float(acceptance["max_hard_negative_false_positive_rate"]),
        }
        status = "PASS" if all(checks.values()) else "FAIL"
        evidence = {
            "protocol": CALIBRATION_PROTOCOL,
            "manifest_sha256": manifest_hash,
            "corpus_digest": corpus_digest,
            "case_count": case_count,
            "zone_count": zone_total,
            "zone_exact_rate": zone_exact_rate,
            "mean_char_error_rate": mean_cer,
            "hard_negative_cases": hard_negative_total,
            "hard_negative_false_positives": hard_negative_fp,
            "hard_negative_false_positive_rate": negative_fp_rate,
            "observed_strata": sorted(strata),
            "missing_required_strata": missing_strata,
            "acceptance": acceptance,
            "checks": checks,
            "status": status,
        }
        evidence_hash = hashlib.sha256(
            (stable_json(evidence) + stable_json(results)).encode("utf-8")
        ).hexdigest()
        _upsert_gate(
            conn,
            status=status,
            corpus_digest=corpus_digest,
            evidence_sha256=evidence_hash,
            detail=stable_json(evidence),
        )
        mass_ocr_ready = _refresh_mass_gate(conn, corpus_digest)

        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "calibration_results.json").write_text(
            json.dumps(results, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        certification = dict(evidence)
        certification["evidence_sha256"] = evidence_hash
        certification["mass_ocr_gate"] = MASS_OCR_GATE
        certification["mass_ocr_ready"] = mass_ocr_ready
        (output_dir / "calibration_certification.json").write_text(
            json.dumps(certification, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return certification
    except CalibrationBlocked as exc:
        _upsert_gate(
            conn,
            status="BLOCKED",
            corpus_digest=corpus_digest,
            evidence_sha256=manifest_hash,
            detail=str(exc),
        )
        _refresh_mass_gate(conn, corpus_digest)
        raise
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run corpus-bound empirical RLSM OCR calibration."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--repo-root", type=Path, default=REPO)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        result = run(
            args.manifest,
            db_path=args.db,
            repo_root=args.repo_root,
            output_dir=args.output_dir,
        )
    except CalibrationBlocked as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, indent=2))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
