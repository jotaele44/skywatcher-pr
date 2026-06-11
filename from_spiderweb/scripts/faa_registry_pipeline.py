#!/usr/bin/env python3
"""FAA Releasable Aircraft Data Pipeline.

Downloads/parses the FAA Releasable Aircraft Registration Database and emits
one normalized record per requested N-number.

Design principles:
- FAA bulk download is the authoritative source.
- Input N-numbers may include or omit the leading "N".
- FAA files are treated as comma-delimited text, usually without headers.
- Reference files are joined deterministically by FAA code.
- Missing permissible fields are not classified as errors.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sqlite3
import sys
import urllib.request
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

FAA_ZIP_URL = "https://registry.faa.gov/database/ReleasableAircraft.zip"
FAA_DOC_URL = "https://registry.faa.gov/database/ardata.pdf"

MASTER_FIELDS = [
    "n_number",
    "serial_number",
    "aircraft_mfr_model_code",
    "engine_mfr_model_code",
    "year_mfr",
    "type_registrant",
    "name",
    "street1",
    "street2",
    "city",
    "state",
    "zip_code",
    "region",
    "county_mail",
    "country_mail",
    "last_activity_date",
    "certificate_issue_date",
    "certification",
    "type_aircraft",
    "type_engine",
    "status_code",
    "mode_s_code",
    "fractional_ownership",
    "airworthiness_date",
    "other_name_1",
    "other_name_2",
    "other_name_3",
    "other_name_4",
    "other_name_5",
    "expiration_date",
    "unique_id",
    "kit_mfr",
    "kit_model",
    "mode_s_code_hex",
    # The FAA page notes an Aircraft Certificate Expiration Date was added to
    # the Master Download file. Keep this tolerant field for current/future
    # releases; extra columns are also retained as extra_#.
    "aircraft_certificate_expiration_date",
]

ACFTREF_FIELDS = [
    "aircraft_mfr_model_series_code",
    "aircraft_manufacturer_name",
    "model_name",
    "type_aircraft_ref",
    "type_engine_ref",
    "aircraft_category_code",
    "builder_certification_code",
    "number_of_engines",
    "number_of_seats",
    "aircraft_weight_code",
    "aircraft_cruising_speed_mph",
    "tc_data_sheet",
    "tc_data_holder",
]

ENGINE_FIELDS = [
    "engine_mfr_model_code",
    "engine_manufacturer_name",
    "engine_model_name",
    "type_engine_ref",
    "engine_horsepower",
    "pounds_of_thrust",
]

DEREG_FIELDS = [
    "n_number",
    "serial_number",
    "aircraft_mfr_model_code",
    "status_code",
    "name",
    "street1",
    "street2",
    "city",
    "state",
    "zip_code",
    "certificate_issue_date",
    "airworthiness_date",
    "cancel_date",
    "mode_s_code",
    "mode_s_code_hex",
]

TYPE_REGISTRANT = {
    "1": "Individual",
    "2": "Partnership",
    "3": "Corporation",
    "4": "Co-Owned",
    "5": "Government",
    "7": "LLC",
    "8": "Non Citizen Corporation",
    "9": "Non Citizen Co-Owned",
}

TYPE_AIRCRAFT = {
    "1": "Glider",
    "2": "Balloon",
    "3": "Blimp/Dirigible",
    "4": "Fixed wing single engine",
    "5": "Fixed wing multi engine",
    "6": "Rotorcraft",
    "7": "Weight-shift-control",
    "8": "Powered Parachute",
    "9": "Gyroplane",
    "H": "Hybrid Lift",
    "O": "Other",
}

TYPE_ENGINE = {
    "0": "None",
    "1": "Reciprocating",
    "2": "Turbo-prop",
    "3": "Turbo-shaft",
    "4": "Turbo-jet",
    "5": "Turbo-fan",
    "6": "Ramjet",
    "7": "2 Cycle",
    "8": "4 Cycle",
    "9": "Unknown",
    "10": "Electric",
    "11": "Rotary",
}

STATUS_CODE = {
    "A": "Triennial registration form mailed; not returned by post office",
    "D": "Expired dealer",
    "E": "Certificate revoked by enforcement action",
    "M": "Valid registration assigned to manufacturer dealer certificate",
    "N": "Non-citizen corporation flight-hour report not returned",
    "R": "Registration pending",
    "S": "Second triennial form mailed; not returned by post office",
    "T": "Valid registration from trainee",
    "V": "Valid registration",
    "W": "Certificate deemed ineffective or invalid",
    "X": "Enforcement letter",
    "Z": "Permanent reserved",
    "1": "Triennial form returned undeliverable",
    "2": "N-number assigned, not registered",
    "3": "N-number assigned to non-type-certificated aircraft, not registered",
    "4": "N-number assigned as import, not registered",
    "5": "Reserved N-number",
    "6": "Administratively canceled",
    "7": "Sale reported",
    "8": "Second triennial attempt made; no response",
    "9": "Certificate revoked",
    "10": "Assigned, not registered, pending cancellation",
    "11": "Assigned non-type-certificated amateur, pending cancellation",
    "12": "Assigned import, pending cancellation",
    "13": "Registration expired",
    "14": "First notice for re-registration/renewal",
    "15": "Second notice for re-registration/renewal",
    "16": "Expired, pending cancellation",
    "17": "Sale reported, pending cancellation",
    "18": "Sale reported, canceled",
    "19": "Registration pending, pending cancellation",
    "20": "Registration pending, canceled",
    "21": "Revoked, pending cancellation",
    "22": "Revoked, canceled",
    "23": "Expired dealer, pending cancellation",
    "24": "Third notice for re-registration/renewal",
    "25": "First notice for registration renewal",
    "26": "Second notice for registration renewal",
    "27": "Registration expired",
    "28": "Third notice for registration renewal",
    "29": "Registration expired, pending cancellation",
}

OUTPUT_FIELDS = [
    "registration",
    "faa_n_number_raw",
    "match_status",
    "source_state",
    "source_file",
    "source_record_count",
    "conflict_flag",
    "conflict_notes",
    "resolution_rule",
    "status_code",
    "status_label",
    "type_registrant_code",
    "type_registrant_label",
    "owner_name",
    "street1",
    "street2",
    "city",
    "state",
    "zip_code",
    "region",
    "county_mail",
    "country_mail",
    "serial_number",
    "aircraft_mfr_model_code",
    "aircraft_manufacturer",
    "aircraft_model",
    "engine_mfr_model_code",
    "engine_manufacturer",
    "engine_model",
    "year_manufactured",
    "type_aircraft_code",
    "type_aircraft_label",
    "type_engine_code",
    "type_engine_label",
    "certification",
    "certificate_issue_date",
    "last_activity_date",
    "airworthiness_date",
    "registration_expiration_date",
    "aircraft_certificate_expiration_date",
    "mode_s_code",
    "mode_s_code_hex",
    "fractional_ownership",
    "unique_id",
    "kit_mfr",
    "kit_model",
    "other_names",
    "source_faa_zip_url",
    "source_faa_doc_url",
    "run_timestamp_utc",
]


@dataclass(frozen=True)
class LocatedFiles:
    master: Path
    aircraft_ref: Optional[Path]
    engine_ref: Optional[Path]
    deregistered: Optional[Path]


def clean(value: object) -> str:
    if value is None:
        return ""
    return str(value).replace("\x00", "").strip()


def normalize_key(value: str) -> str:
    """Return FAA internal key without the leading N."""
    s = clean(value).upper()
    s = re.sub(r"[^A-Z0-9]", "", s)
    if s.startswith("N"):
        s = s[1:]
    return s


def format_registration(key_or_value: str) -> str:
    key = normalize_key(key_or_value)
    return f"N{key}" if key else ""


def extract_registrations_from_text(text: str) -> List[str]:
    out: List[str] = []
    for raw in re.split(r"[\n,;\t ]+", text):
        token = raw.strip().upper()
        if not token or token.startswith("#"):
            continue
        key = normalize_key(token)
        if key and re.fullmatch(r"[1-9][0-9]{0,4}[A-HJ-NP-Z]{0,2}", key):
            out.append(format_registration(key))
    # Preserve input order while deduping.
    seen = set()
    ordered = []
    for reg in out:
        if reg not in seen:
            seen.add(reg)
            ordered.append(reg)
    return ordered


def load_registrations(path: Path) -> Tuple[List[str], Dict[str, str]]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    regs = extract_registrations_from_text(text)
    if not regs:
        raise ValueError(f"No valid N-number registrations found in {path}")
    key_to_reg = {normalize_key(reg): reg for reg in regs}
    return regs, key_to_reg


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download_faa_zip(dest: Path, url: str = FAA_ZIP_URL, force: bool = False) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not force:
        return dest
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    with urllib.request.urlopen(url, timeout=120) as r, tmp.open("wb") as f:
        shutil.copyfileobj(r, f)
    tmp.replace(dest)
    return dest


def extract_zip(zip_path: Path, faa_dir: Path) -> None:
    faa_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(faa_dir)


def locate_files(faa_dir: Path) -> LocatedFiles:
    files = [p for p in faa_dir.rglob("*") if p.is_file()]
    by_name = {p.name.upper(): p for p in files}

    def first_matching(*needles: str) -> Optional[Path]:
        for p in files:
            name = p.name.upper()
            if all(n.upper() in name for n in needles):
                return p
        return None

    master = by_name.get("MASTER.TXT") or first_matching("MASTER")
    acftref = by_name.get("ACFTREF.TXT") or first_matching("ACFTREF") or first_matching("AIRCRAFT", "REF")
    engine = by_name.get("ENGINE.TXT") or first_matching("ENGINE")
    dereg = by_name.get("DEREG.TXT") or by_name.get("DEREGISTERED.TXT") or first_matching("DEREG")
    if not master:
        available = ", ".join(sorted(p.name for p in files)[:50])
        raise FileNotFoundError(f"Could not locate FAA master file under {faa_dir}. Available: {available}")
    return LocatedFiles(master=master, aircraft_ref=acftref, engine_ref=engine, deregistered=dereg)


def looks_like_header(row: Sequence[str], expected_first: str) -> bool:
    if not row:
        return False
    normalized = re.sub(r"[^a-z0-9]", "", row[0].lower())
    return expected_first.replace("_", "") in normalized or "nnumber" in normalized


def read_faa_csv(path: Path, fieldnames: Sequence[str]) -> List[Dict[str, str]]:
    encodings = ["utf-8-sig", "latin-1"]
    last_error: Optional[Exception] = None
    for enc in encodings:
        try:
            with path.open("r", newline="", encoding=enc, errors="replace") as f:
                reader = csv.reader(f)
                rows = [list(map(clean, row)) for row in reader if any(clean(x) for x in row)]
            break
        except Exception as exc:  # pragma: no cover - defensive fallback
            last_error = exc
    else:  # pragma: no cover
        raise last_error or RuntimeError(f"Could not read {path}")

    if not rows:
        return []

    if looks_like_header(rows[0], fieldnames[0]):
        header = [re.sub(r"[^a-z0-9]+", "_", h.lower()).strip("_") for h in rows[0]]
        records = []
        for row in rows[1:]:
            rec = {header[i]: row[i] if i < len(row) else "" for i in range(len(header))}
            records.append(rec)
        return records

    records = []
    for row in rows:
        rec = {fieldnames[i]: row[i] if i < len(row) else "" for i in range(len(fieldnames))}
        if len(row) > len(fieldnames):
            for j, value in enumerate(row[len(fieldnames):], start=1):
                rec[f"extra_{j}"] = value
        records.append(rec)
    return records


def parse_date(value: str) -> str:
    s = clean(value)
    if not s:
        return ""
    for fmt in ("%Y%m%d", "%Y/%m/%d", "%m/%d/%Y", "%y%m%d"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return s


def make_ref_map(rows: Iterable[Dict[str, str]], key_field: str) -> Dict[str, Dict[str, str]]:
    out = {}
    for row in rows:
        key = clean(row.get(key_field, "")).upper()
        if key and key not in out:
            out[key] = row
    return out


def split_aircraft_code(code: str) -> Tuple[str, str, str]:
    s = clean(code).upper()
    return s[:3], s[3:5], s[5:7]


def split_engine_code(code: str) -> Tuple[str, str]:
    s = clean(code).upper()
    return s[:3], s[3:5]


def status_rank(row: Dict[str, str]) -> Tuple[int, str, str]:
    # Larger tuple wins. Valid statuses outrank inactive states; later dates win next.
    code = clean(row.get("status_code", "")).upper()
    active_bonus = 2 if code in {"V", "M", "T"} else 1 if code in {"R"} else 0
    date = parse_date(row.get("last_activity_date") or row.get("expiration_date") or row.get("certificate_issue_date") or "")
    return active_bonus, date, clean(row.get("unique_id", ""))


def normalize_master_record(
    row: Dict[str, str],
    aircraft_ref: Dict[str, Dict[str, str]],
    engine_ref: Dict[str, Dict[str, str]],
    source_file: str,
    source_state: str,
    source_record_count: int,
    run_ts: str,
    conflict_flag: bool = False,
    conflict_notes: str = "",
    resolution_rule: str = "single_or_highest_ranked_faa_record",
) -> Dict[str, str]:
    ac_code = clean(row.get("aircraft_mfr_model_code", "")).upper()
    en_code = clean(row.get("engine_mfr_model_code", "")).upper()
    ac_ref = aircraft_ref.get(ac_code, {})
    en_ref = engine_ref.get(en_code, {})
    type_aircraft_code = clean(row.get("type_aircraft", "") or ac_ref.get("type_aircraft_ref", "")).upper()
    type_engine_code = clean(row.get("type_engine", "") or en_ref.get("type_engine_ref", "")).upper()
    other_names = [clean(row.get(f"other_name_{i}", "")) for i in range(1, 6)]
    other_names = [x for x in other_names if x]

    out = {
        "registration": format_registration(row.get("n_number", "")),
        "faa_n_number_raw": clean(row.get("n_number", "")),
        "match_status": "matched" if source_state == "master" else source_state,
        "source_state": source_state,
        "source_file": source_file,
        "source_record_count": str(source_record_count),
        "conflict_flag": "yes" if conflict_flag else "no",
        "conflict_notes": conflict_notes,
        "resolution_rule": resolution_rule,
        "status_code": clean(row.get("status_code", "")).upper(),
        "status_label": STATUS_CODE.get(clean(row.get("status_code", "")).upper(), ""),
        "type_registrant_code": clean(row.get("type_registrant", "")),
        "type_registrant_label": TYPE_REGISTRANT.get(clean(row.get("type_registrant", "")), ""),
        "owner_name": clean(row.get("name", "")),
        "street1": clean(row.get("street1", "")),
        "street2": clean(row.get("street2", "")),
        "city": clean(row.get("city", "")),
        "state": clean(row.get("state", "")),
        "zip_code": clean(row.get("zip_code", "")),
        "region": clean(row.get("region", "")),
        "county_mail": clean(row.get("county_mail", "")),
        "country_mail": clean(row.get("country_mail", "")),
        "serial_number": clean(row.get("serial_number", "")),
        "aircraft_mfr_model_code": ac_code,
        "aircraft_manufacturer": clean(ac_ref.get("aircraft_manufacturer_name", "")),
        "aircraft_model": clean(ac_ref.get("model_name", "")),
        "engine_mfr_model_code": en_code,
        "engine_manufacturer": clean(en_ref.get("engine_manufacturer_name", "")),
        "engine_model": clean(en_ref.get("engine_model_name", "")),
        "year_manufactured": clean(row.get("year_mfr", "")),
        "type_aircraft_code": type_aircraft_code,
        "type_aircraft_label": TYPE_AIRCRAFT.get(type_aircraft_code, ""),
        "type_engine_code": type_engine_code,
        "type_engine_label": TYPE_ENGINE.get(type_engine_code, ""),
        "certification": clean(row.get("certification", "")),
        "certificate_issue_date": parse_date(row.get("certificate_issue_date", "")),
        "last_activity_date": parse_date(row.get("last_activity_date", "")),
        "airworthiness_date": parse_date(row.get("airworthiness_date", "")),
        "registration_expiration_date": parse_date(row.get("expiration_date", "")),
        "aircraft_certificate_expiration_date": parse_date(row.get("aircraft_certificate_expiration_date", "")),
        "mode_s_code": clean(row.get("mode_s_code", "")),
        "mode_s_code_hex": clean(row.get("mode_s_code_hex", "")),
        "fractional_ownership": clean(row.get("fractional_ownership", "")),
        "unique_id": clean(row.get("unique_id", "")),
        "kit_mfr": clean(row.get("kit_mfr", "")),
        "kit_model": clean(row.get("kit_model", "")),
        "other_names": " | ".join(other_names),
        "source_faa_zip_url": FAA_ZIP_URL,
        "source_faa_doc_url": FAA_DOC_URL,
        "run_timestamp_utc": run_ts,
    }
    return out


def unresolved_record(registration: str, reason: str, run_ts: str) -> Dict[str, str]:
    out = {field: "" for field in OUTPUT_FIELDS}
    out.update({
        "registration": registration,
        "match_status": "missing",
        "source_state": "unresolved",
        "source_file": "",
        "source_record_count": "0",
        "conflict_flag": "no",
        "conflict_notes": reason,
        "resolution_rule": "no_matching_faa_master_or_deregistered_record",
        "source_faa_zip_url": FAA_ZIP_URL,
        "source_faa_doc_url": FAA_DOC_URL,
        "run_timestamp_utc": run_ts,
    })
    return out


def consolidate(
    target_regs: List[str],
    key_to_reg: Dict[str, str],
    files: LocatedFiles,
    run_ts: str,
    include_deregistered: bool = True,
) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    master_rows = read_faa_csv(files.master, MASTER_FIELDS)
    ac_ref_rows = read_faa_csv(files.aircraft_ref, ACFTREF_FIELDS) if files.aircraft_ref else []
    en_ref_rows = read_faa_csv(files.engine_ref, ENGINE_FIELDS) if files.engine_ref else []
    ac_ref = make_ref_map(ac_ref_rows, "aircraft_mfr_model_series_code")
    en_ref = make_ref_map(en_ref_rows, "engine_mfr_model_code")

    grouped: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for row in master_rows:
        key = normalize_key(row.get("n_number", ""))
        if key in key_to_reg:
            grouped[key].append(row)

    outputs: Dict[str, Dict[str, str]] = {}
    conflicts: List[Dict[str, str]] = []
    for key, rows in grouped.items():
        selected = sorted(rows, key=status_rank, reverse=True)[0]
        conflict_flag = len(rows) > 1
        notes = ""
        if conflict_flag:
            compared = Counter((clean(r.get("name")), clean(r.get("status_code")), clean(r.get("expiration_date"))) for r in rows)
            notes = f"{len(rows)} FAA master rows; selected highest status/date rank; variants={len(compared)}"
            conflicts.append({"registration": key_to_reg[key], "notes": notes})
        outputs[key] = normalize_master_record(
            selected,
            ac_ref,
            en_ref,
            files.master.name,
            "master",
            len(rows),
            run_ts,
            conflict_flag=conflict_flag,
            conflict_notes=notes,
        )

    dereg_hits = 0
    if include_deregistered and files.deregistered:
        dereg_rows = read_faa_csv(files.deregistered, DEREG_FIELDS)
        dereg_grouped: Dict[str, List[Dict[str, str]]] = defaultdict(list)
        unresolved_keys = [k for k in key_to_reg if k not in outputs]
        unresolved_set = set(unresolved_keys)
        for row in dereg_rows:
            key = normalize_key(row.get("n_number", ""))
            if key in unresolved_set:
                dereg_grouped[key].append(row)
        for key, rows in dereg_grouped.items():
            selected = sorted(rows, key=status_rank, reverse=True)[0]
            outputs[key] = normalize_master_record(
                selected,
                ac_ref,
                en_ref,
                files.deregistered.name,
                "deregistered",
                len(rows),
                run_ts,
                conflict_flag=len(rows) > 1,
                conflict_notes=(f"{len(rows)} deregistered rows" if len(rows) > 1 else ""),
                resolution_rule="not_in_master; selected highest_ranked_deregistered_record",
            )
            outputs[key]["match_status"] = "deregistered"
            dereg_hits += 1

    final_rows = []
    for reg in target_regs:
        key = normalize_key(reg)
        final_rows.append(outputs.get(key) or unresolved_record(reg, "No matching current master or deregistered record", run_ts))

    metadata = {
        "run_timestamp_utc": run_ts,
        "target_count": len(target_regs),
        "matched_master_count": sum(1 for r in final_rows if r["source_state"] == "master"),
        "matched_deregistered_count": dereg_hits,
        "missing_count": sum(1 for r in final_rows if r["match_status"] == "missing"),
        "conflict_count": len(conflicts),
        "files": {
            "master": str(files.master),
            "aircraft_ref": str(files.aircraft_ref) if files.aircraft_ref else None,
            "engine_ref": str(files.engine_ref) if files.engine_ref else None,
            "deregistered": str(files.deregistered) if files.deregistered else None,
        },
        "file_hashes_sha256": {p.name: sha256_file(p) for p in [files.master, *(x for x in [files.aircraft_ref, files.engine_ref, files.deregistered] if x)]},
        "conflicts": conflicts,
    }
    return final_rows, metadata


def write_csv(path: Path, rows: List[Dict[str, str]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_sqlite(path: Path, rows: List[Dict[str, str]], metadata: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    try:
        cur = con.cursor()
        cur.execute("DROP TABLE IF EXISTS faa_aircraft_consolidated")
        cols = ", ".join(f'"{f}" TEXT' for f in OUTPUT_FIELDS)
        cur.execute(f"CREATE TABLE faa_aircraft_consolidated ({cols}, PRIMARY KEY(registration))")
        placeholders = ",".join("?" for _ in OUTPUT_FIELDS)
        quoted = ",".join(f'"{f}"' for f in OUTPUT_FIELDS)
        cur.executemany(
            f"INSERT OR REPLACE INTO faa_aircraft_consolidated ({quoted}) VALUES ({placeholders})",
            [[r.get(f, "") for f in OUTPUT_FIELDS] for r in rows],
        )
        cur.execute("DROP TABLE IF EXISTS faa_registry_run_metadata")
        cur.execute("CREATE TABLE faa_registry_run_metadata (key TEXT PRIMARY KEY, value TEXT)")
        for key, value in metadata.items():
            cur.execute("INSERT OR REPLACE INTO faa_registry_run_metadata VALUES (?, ?)", (key, json.dumps(value, sort_keys=True)))
        con.commit()
    finally:
        con.close()


def missingness(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    total = len(rows)
    out = []
    for field in OUTPUT_FIELDS:
        missing = sum(1 for r in rows if not clean(r.get(field, "")))
        out.append({
            "field": field,
            "missing_count": str(missing),
            "total_count": str(total),
            "missing_pct": f"{(missing / total * 100) if total else 0:.2f}",
        })
    return out


def write_report(path: Path, rows: List[Dict[str, str]], metadata: Dict[str, object], missing_rows: List[Dict[str, str]]) -> None:
    status_counts = Counter(r.get("match_status", "") for r in rows)
    type_counts = Counter(r.get("type_aircraft_label", "") or "Unknown" for r in rows)
    top_missing = sorted(missing_rows, key=lambda r: float(r["missing_pct"]), reverse=True)[:15]
    lines = []
    lines.append("# FAA Registry Consolidation Validation Report")
    lines.append("")
    lines.append(f"Run timestamp UTC: `{metadata['run_timestamp_utc']}`")
    lines.append("")
    lines.append("## Source authority")
    lines.append("")
    lines.append(f"- FAA ZIP: `{FAA_ZIP_URL}`")
    lines.append(f"- FAA documentation: `{FAA_DOC_URL}`")
    lines.append("- Rule: FAA bulk registry data is authoritative for registry fields; missing permissible fields are not validation failures.")
    lines.append("")
    lines.append("## Coverage")
    lines.append("")
    lines.append("| Metric | Count |")
    lines.append("|---|---:|")
    lines.append(f"| Target registrations | {metadata['target_count']} |")
    lines.append(f"| Matched in master | {metadata['matched_master_count']} |")
    lines.append(f"| Matched in deregistered file | {metadata['matched_deregistered_count']} |")
    lines.append(f"| Missing/unresolved | {metadata['missing_count']} |")
    lines.append(f"| Conflict groups | {metadata['conflict_count']} |")
    lines.append("")
    lines.append("## Match status counts")
    lines.append("")
    lines.append("| Status | Count |")
    lines.append("|---|---:|")
    for k, v in status_counts.most_common():
        lines.append(f"| {k or 'blank'} | {v} |")
    lines.append("")
    lines.append("## Aircraft type counts")
    lines.append("")
    lines.append("| Aircraft type | Count |")
    lines.append("|---|---:|")
    for k, v in type_counts.most_common():
        lines.append(f"| {k} | {v} |")
    lines.append("")
    lines.append("## Highest missingness fields")
    lines.append("")
    lines.append("| Field | Missing | Total | Missing % |")
    lines.append("|---|---:|---:|---:|")
    for r in top_missing:
        lines.append(f"| {r['field']} | {r['missing_count']} | {r['total_count']} | {r['missing_pct']} |")
    lines.append("")
    lines.append("## Conflict handling")
    lines.append("")
    if metadata.get("conflicts"):
        lines.append("| Registration | Notes |")
        lines.append("|---|---|")
        for c in metadata["conflicts"]:
            lines.append(f"| {c['registration']} | {c['notes']} |")
    else:
        lines.append("No duplicate/conflict groups detected in the selected FAA master records.")
    lines.append("")
    lines.append("## File hashes")
    lines.append("")
    lines.append("| File | SHA-256 |")
    lines.append("|---|---|")
    for name, digest in metadata.get("file_hashes_sha256", {}).items():
        lines.append(f"| {name} | `{digest}` |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_mermaid(path: Path) -> None:
    path.write_text(
        """# FAA Registry ETL Diagrams

```mermaid
flowchart LR
    A[Input N-number list] --> B[Normalize to FAA keys]
    C[FAA ReleasableAircraft.zip] --> D[Extract TXT files]
    D --> E[Parse MASTER.txt]
    D --> F[Parse ACFTREF.txt]
    D --> G[Parse ENGINE.txt]
    D --> H[Parse DEREG if enabled]
    B --> I[Filter target registrations]
    E --> I
    I --> J[Join make/model and engine refs]
    F --> J
    G --> J
    H --> K[Fill non-master misses]
    J --> L[Consolidate one row per N-number]
    K --> L
    L --> M[CSV + SQLite + validation report]
```

```mermaid
timeline
    title FAA Releasable Aircraft Data Pipeline
    T0 : Download or reuse FAA ZIP
    T1 : Extract files and hash sources
    T2 : Normalize target registrations
    T3 : Filter master/deregistered records
    T4 : Join reference tables
    T5 : Resolve duplicate candidates
    T6 : Export consolidated records and QA report
```
""",
        encoding="utf-8",
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="FAA Releasable Aircraft Registry pipeline")
    parser.add_argument("--registrations", required=True, type=Path, help="Text file with N-numbers; comma/newline separated accepted")
    parser.add_argument("--faa-dir", type=Path, default=Path("data/faa_registry"), help="Directory holding extracted FAA TXT files")
    parser.add_argument("--faa-zip", type=Path, default=Path("data/faa_registry/ReleasableAircraft.zip"), help="FAA ZIP path")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/faa_registry"), help="Output directory")
    parser.add_argument("--download", action="store_true", help="Download FAA ZIP before parsing")
    parser.add_argument("--force-download", action="store_true", help="Overwrite existing FAA ZIP")
    parser.add_argument("--no-extract", action="store_true", help="Do not extract ZIP before parsing")
    parser.add_argument("--no-deregistered", action="store_true", help="Do not search deregistered file for master misses")
    parser.add_argument("--download-url", default=FAA_ZIP_URL, help="FAA ZIP URL")
    args = parser.parse_args(argv)

    run_ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    target_regs, key_to_reg = load_registrations(args.registrations)

    if args.download:
        download_faa_zip(args.faa_zip, args.download_url, force=args.force_download)
    if args.faa_zip.exists() and not args.no_extract:
        extract_zip(args.faa_zip, args.faa_dir)

    files = locate_files(args.faa_dir)
    rows, metadata = consolidate(target_regs, key_to_reg, files, run_ts, include_deregistered=not args.no_deregistered)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    consolidated_csv = args.output_dir / "faa_registry_consolidated.csv"
    missing_csv = args.output_dir / "faa_registry_missingness.csv"
    metadata_json = args.output_dir / "faa_registry_summary.json"
    report_md = args.output_dir / "faa_registry_validation_report.md"
    mermaid_md = args.output_dir / "faa_registry_etl_diagrams.md"
    sqlite_path = args.output_dir / "faa_registry.db"

    write_csv(consolidated_csv, rows, OUTPUT_FIELDS)
    miss = missingness(rows)
    write_csv(missing_csv, miss, ["field", "missing_count", "total_count", "missing_pct"])
    write_sqlite(sqlite_path, rows, metadata)
    metadata_json.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_report(report_md, rows, metadata, miss)
    write_mermaid(mermaid_md)

    print(json.dumps({
        "target_count": metadata["target_count"],
        "matched_master_count": metadata["matched_master_count"],
        "matched_deregistered_count": metadata["matched_deregistered_count"],
        "missing_count": metadata["missing_count"],
        "conflict_count": metadata["conflict_count"],
        "outputs": {
            "consolidated_csv": str(consolidated_csv),
            "sqlite": str(sqlite_path),
            "report_md": str(report_md),
            "missingness_csv": str(missing_csv),
            "summary_json": str(metadata_json),
            "diagrams_md": str(mermaid_md),
        },
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
