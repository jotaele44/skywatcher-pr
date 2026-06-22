#!/usr/bin/env python3
"""
Skywatcher OCR registry validation pass.

Purpose:
  Validate OCR-recovered FR24 N-number candidates against local FAA registry files
  before they are promoted into platform_master or joined to P-Route events.

Inputs:
  - ocr_new_tails.csv
  - events.csv
  - FAA MASTER.txt
  - FAA DEREG.txt
  - FAA RESERVED.txt
  - FAA ACFTREF.txt

Outputs:
  - registry_validated_tails.csv
  - platform_master_patch.csv
  - ocr_false_positive_patterns.csv
  - validation_summary.json

Default paths assume this is run from the skywatcher-pr repo root after:
  python3 scripts/fr24_ocr_parallel.py
  python3 scripts/fr24_ocr_finalize.py
  python3 scripts/build_new_tails.py

Example:
  python3 scripts/skywatcher_ocr_registry_validation_pass.py \
    --ocr-new-tails ocr_new_tails.csv \
    --events events.csv \
    --faa-dir data/faa_registry \
    --out-dir outputs/registry_validation

Notes:
  - No network calls.
  - Does not mutate existing ledgers.
  - Treats FAA registry-negative high-frequency tails as OCR quarantine candidates.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

REPO = Path(__file__).resolve().parents[1]

# FAA N-number rule used here:
# N + 1-5 digits, optional 1-2 suffix letters, no I/O, and max 5 chars after N.
N_NUMBER_RE = re.compile(r"^N[1-9][0-9]{0,4}[A-HJ-NP-Z]{0,2}$")
BAD_N_CHARS = {"I", "O"}

TAIL_COLUMN_CANDIDATES = (
    "tail",
    "registration",
    "n_number",
    "n-number",
    "nnumber",
    "aircraft_registration",
    "reg",
    "recovered_tail",
    "candidate_tail",
)
COUNT_COLUMN_CANDIDATES = (
    "count",
    "event_count",
    "image_count",
    "sightings",
    "n",
    "occurrences",
    "registration_event_count",
)
IMAGE_COLUMN_CANDIDATES = (
    "image",
    "image_path",
    "file",
    "file_path",
    "screenshot",
    "screenshot_id",
    "source_image",
    "rel_path",
)


@dataclass
class TailCandidate:
    tail: str
    source_count: int = 0
    event_count: int = 0
    image_count: int = 0
    first_source: str = ""
    source_rows: int = 0


@dataclass
class RegistryRow:
    tail: str
    source: str
    raw: Dict[str, str]


def norm_header(value: str) -> str:
    """Normalize CSV headers for robust FAA/user-output parsing."""
    return re.sub(r"[^a-z0-9]+", "_", (value or "").strip().lower()).strip("_")


def norm_tail(value: object) -> str:
    """Normalize a possible N-number without inventing characters."""
    text = str(value or "").upper().strip()
    text = text.replace(" ", "").replace("-", "")
    text = re.sub(r"[^A-Z0-9]", "", text)
    if text and not text.startswith("N") and re.fullmatch(r"[0-9][A-Z0-9]{1,5}", text):
        # Only add N for obvious stripped N-number values from FAA files.
        text = f"N{text}"
    return text


def is_valid_n_number(tail: str) -> bool:
    """Return True for syntactically valid FAA N-numbers, excluding I/O."""
    if not tail:
        return False
    if len(tail) > 6:
        return False
    if any(ch in tail[1:] for ch in BAD_N_CHARS):
        return False
    return bool(N_NUMBER_RE.match(tail))


def is_short_tail_edge(tail: str) -> bool:
    """Short N-numbers are legal but OCR-risky in screenshots."""
    return bool(tail and len(tail) <= 3)


def read_csv_rows(path: Path) -> List[Dict[str, str]]:
    """Read a CSV file with utf-8-sig fallback and normalized headers."""
    if not path.exists():
        return []
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            with path.open("r", encoding=encoding, newline="") as f:
                sample = f.read(8192)
                f.seek(0)
                dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|") if sample.strip() else csv.excel
                reader = csv.DictReader(f, dialect=dialect)
                if not reader.fieldnames:
                    return []
                normalized = [norm_header(h) for h in reader.fieldnames]
                rows = []
                for raw_row in reader:
                    row = {}
                    for original_key, normalized_key in zip(reader.fieldnames, normalized):
                        row[normalized_key] = (raw_row.get(original_key) or "").strip()
                    rows.append(row)
                return rows
        except UnicodeDecodeError:
            continue
        except csv.Error:
            continue
    raise RuntimeError(f"Could not parse CSV: {path}")


def read_single_column_or_csv(path: Path) -> List[Dict[str, str]]:
    """Read generated candidate CSVs; support headerless one-tail-per-line files."""
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8-sig", errors="replace").strip()
    if not text:
        return []
    first_line = text.splitlines()[0]
    if "," not in first_line and "\t" not in first_line and norm_tail(first_line):
        rows = []
        for line in text.splitlines():
            tail = norm_tail(line)
            if tail:
                rows.append({"tail": tail})
        return rows
    return read_csv_rows(path)


def get_first(row: Mapping[str, str], keys: Sequence[str]) -> str:
    for key in keys:
        k = norm_header(key)
        if k in row and str(row[k]).strip():
            return str(row[k]).strip()
    return ""


def infer_tail_from_row(row: Mapping[str, str]) -> str:
    explicit = get_first(row, TAIL_COLUMN_CANDIDATES)
    if explicit:
        return norm_tail(explicit)
    # Last resort: scan values for a valid-looking N-number token.
    for value in row.values():
        text = str(value or "").upper()
        for token in re.findall(r"\bN[0-9A-Z][0-9A-Z\-]{1,6}\b", text):
            tail = norm_tail(token)
            if tail:
                return tail
    return ""


def infer_count_from_row(row: Mapping[str, str]) -> int:
    raw = get_first(row, COUNT_COLUMN_CANDIDATES)
    if not raw:
        return 0
    m = re.search(r"\d+", raw.replace(",", ""))
    return int(m.group(0)) if m else 0


def infer_image_from_row(row: Mapping[str, str]) -> str:
    return get_first(row, IMAGE_COLUMN_CANDIDATES)


def load_tail_candidates(ocr_new_tails: Path, events_csv: Path) -> Dict[str, TailCandidate]:
    candidates: Dict[str, TailCandidate] = {}

    def ensure(tail: str) -> TailCandidate:
        if tail not in candidates:
            candidates[tail] = TailCandidate(tail=tail)
        return candidates[tail]

    for row in read_single_column_or_csv(ocr_new_tails):
        tail = infer_tail_from_row(row)
        if not tail:
            continue
        c = ensure(tail)
        c.source_count += infer_count_from_row(row)
        c.source_rows += 1
        if not c.first_source:
            c.first_source = str(ocr_new_tails)

    event_counter: Counter[str] = Counter()
    image_sets: Dict[str, set] = defaultdict(set)

    for row in read_csv_rows(events_csv):
        tail = infer_tail_from_row(row)
        if not tail:
            continue
        event_counter[tail] += 1
        image_id = infer_image_from_row(row)
        if image_id:
            image_sets[tail].add(image_id)
        ensure(tail)

    for tail, count in event_counter.items():
        candidates[tail].event_count = count
    for tail, images in image_sets.items():
        candidates[tail].image_count = len(images)

    # If ocr_new_tails carried a count but events.csv did not carry the tail,
    # keep source_count as the only count signal.
    return candidates


def load_faa_table(path: Path, source: str) -> Dict[str, RegistryRow]:
    rows = read_csv_rows(path)
    out: Dict[str, RegistryRow] = {}
    for row in rows:
        # FAA raw headers normalize "N-NUMBER" to "n_number".
        tail = norm_tail(get_first(row, ("n_number", "nnumber", "n_num", "n")))
        if not tail:
            for key in row:
                if key.replace("_", "") in {"nnumber", "nnum", "n"}:
                    tail = norm_tail(row[key])
                    break
        if tail:
            out[tail] = RegistryRow(tail=tail, source=source, raw=row)
    return out


def load_acftref(path: Path) -> Dict[str, Dict[str, str]]:
    out: Dict[str, Dict[str, str]] = {}
    for row in read_csv_rows(path):
        code = get_first(row, ("code", "mfr_mdl_code", "aircraft_code"))
        if code:
            out[code.strip()] = row
    return out


def row_blob_text(row: Mapping[str, str]) -> str:
    return " | ".join(str(v or "") for v in row.values()).upper()


def aircraft_from_acftref(master_row: Mapping[str, str], acftref: Mapping[str, Mapping[str, str]]) -> Tuple[str, str]:
    mfr_mdl_code = get_first(master_row, ("mfr_mdl_code", "mfr_model_code"))
    ref = acftref.get(mfr_mdl_code, {})
    manufacturer = get_first(ref, ("mfr", "manufacturer"))
    model = get_first(ref, ("model",))
    return manufacturer, model


def classify_tail(
    candidate: TailCandidate,
    master: Mapping[str, RegistryRow],
    dereg: Mapping[str, RegistryRow],
    reserved: Mapping[str, RegistryRow],
) -> Tuple[str, str, str, str, str, bool]:
    """
    Return:
      registry_class, promotion_status, registry_source, reason, warning_flags, quarantine
    """
    tail = candidate.tail
    warnings: List[str] = []

    if tail == "N253TH":
        warnings.append("forced_quarantine_known_high_frequency_reserved_ocr_cluster")

    if is_short_tail_edge(tail):
        warnings.append("short_tail_edge")

    if any(ch in tail[1:] for ch in BAD_N_CHARS):
        return "OCR_SUSPECT", "reject", "format", "contains_forbidden_i_or_o", ";".join(warnings), True

    if not is_valid_n_number(tail):
        return "OCR_SUSPECT", "reject", "format", "invalid_n_number_format", ";".join(warnings), True

    if tail in master:
        blob = row_blob_text(master[tail].raw)
        if "SALE REPORTED" in blob:
            return "SALE_REPORTED", "hold", "MASTER", "real_aircraft_but_sale_reported_or_certificate_unstable", ";".join(warnings), False
        return "CONFIRMED_ACTIVE", "promote", "MASTER", "assigned_in_faa_master", ";".join(warnings), False

    if tail in reserved:
        quarantine = tail == "N253TH" or candidate.event_count >= 25 or candidate.source_count >= 25
        return "RESERVED_ONLY", "reject", "RESERVED", "reserved_n_number_not_assigned", ";".join(warnings), quarantine

    if tail in dereg:
        return "DEREGISTERED", "hold", "DEREG", "deregistered_match_verify_screenshot_date_before_use", ";".join(warnings), False

    if is_short_tail_edge(tail):
        return "SHORT_TAIL_EDGE", "hold", "none", "legal_format_but_short_ocr_risk_registry_negative", ";".join(warnings), True

    high_frequency = candidate.event_count >= 25 or candidate.source_count >= 25
    if high_frequency:
        return "OCR_SUSPECT", "reject", "none", "registry_negative_high_frequency_paradox", ";".join(warnings), True

    return "OCR_SUSPECT", "hold", "none", "registry_negative_low_frequency", ";".join(warnings), True


def write_csv(path: Path, fieldnames: Sequence[str], rows: Iterable[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore", quoting=csv.QUOTE_ALL)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate OCR-recovered N-numbers against local FAA registry files.")
    parser.add_argument("--ocr-new-tails", default=str(REPO / "ocr_new_tails.csv"))
    parser.add_argument("--events", default=str(REPO / "events.csv"))
    parser.add_argument("--faa-dir", default=str(REPO / "data" / "faa_registry"))
    parser.add_argument("--out-dir", default=str(REPO / "outputs" / "registry_validation"))
    parser.add_argument("--master", default=None)
    parser.add_argument("--dereg", default=None)
    parser.add_argument("--reserved", default=None)
    parser.add_argument("--acftref", default=None)
    args = parser.parse_args()

    ocr_new_tails = Path(args.ocr_new_tails)
    events_csv = Path(args.events)
    faa_dir = Path(args.faa_dir)
    out_dir = Path(args.out_dir)

    master_path = Path(args.master) if args.master else faa_dir / "MASTER.txt"
    dereg_path = Path(args.dereg) if args.dereg else faa_dir / "DEREG.txt"
    reserved_path = Path(args.reserved) if args.reserved else faa_dir / "RESERVED.txt"
    acftref_path = Path(args.acftref) if args.acftref else faa_dir / "ACFTREF.txt"

    missing = [str(p) for p in (ocr_new_tails, events_csv, master_path, dereg_path, reserved_path, acftref_path) if not p.exists()]
    if missing:
        print(json.dumps({"status": "failed", "missing_inputs": missing}, indent=2), file=sys.stderr)
        return 2

    candidates = load_tail_candidates(ocr_new_tails, events_csv)
    master = load_faa_table(master_path, "MASTER")
    dereg = load_faa_table(dereg_path, "DEREG")
    reserved = load_faa_table(reserved_path, "RESERVED")
    acftref = load_acftref(acftref_path)

    validated_rows: List[Dict[str, object]] = []
    platform_rows: List[Dict[str, object]] = []
    fp_rows: List[Dict[str, object]] = []

    for tail in sorted(candidates):
        c = candidates[tail]
        registry_class, promotion_status, registry_source, reason, warnings, quarantine = classify_tail(c, master, dereg, reserved)
        event_count = c.event_count or c.source_count
        master_raw = master[tail].raw if tail in master else {}
        dereg_raw = dereg[tail].raw if tail in dereg else {}
        reserved_raw = reserved[tail].raw if tail in reserved else {}
        active_raw = master_raw or dereg_raw or reserved_raw

        manufacturer, model = aircraft_from_acftref(master_raw, acftref) if master_raw else ("", "")
        owner_name = get_first(active_raw, ("name", "registrant_name", "reserved_name"))
        city = get_first(active_raw, ("city",))
        state = get_first(active_raw, ("state",))
        status_code = get_first(active_raw, ("status_code",))
        cert_issue_date = get_first(active_raw, ("cert_issue_date", "certificate_issue_date"))
        last_action_date = get_first(active_raw, ("last_action_date",))
        dereg_date = get_first(active_raw, ("deregistered_date", "dereg_date"))
        mfr_mdl_code = get_first(master_raw, ("mfr_mdl_code", "mfr_model_code"))

        row = {
            "tail": tail,
            "registry_class": registry_class,
            "promotion_status": promotion_status,
            "quarantine": "yes" if quarantine else "no",
            "registry_source": registry_source,
            "reason": reason,
            "warning_flags": warnings,
            "event_count": event_count,
            "events_csv_count": c.event_count,
            "ocr_new_tails_count": c.source_count,
            "image_count": c.image_count,
            "valid_n_number_format": "yes" if is_valid_n_number(tail) else "no",
            "short_tail_edge": "yes" if is_short_tail_edge(tail) else "no",
            "owner_name": owner_name,
            "city": city,
            "state": state,
            "manufacturer": manufacturer,
            "model": model,
            "mfr_mdl_code": mfr_mdl_code,
            "status_code": status_code,
            "cert_issue_date": cert_issue_date,
            "last_action_date": last_action_date,
            "deregistered_date": dereg_date,
            "first_source": c.first_source,
        }
        validated_rows.append(row)

        if promotion_status in {"promote", "hold"} and registry_class in {
            "CONFIRMED_ACTIVE",
            "SALE_REPORTED",
            "DEREGISTERED",
            "SHORT_TAIL_EDGE",
            "OCR_SUSPECT",
        }:
            platform_rows.append({
                "tail": tail,
                "platform_status": promotion_status,
                "registry_class": registry_class,
                "event_count": event_count,
                "owner_name": owner_name,
                "city": city,
                "state": state,
                "manufacturer": manufacturer,
                "model": model,
                "mfr_mdl_code": mfr_mdl_code,
                "warning_flags": warnings,
                "validation_reason": reason,
                "source": "skywatcher_ocr_registry_validation_pass",
            })

        if quarantine or promotion_status == "reject":
            fp_rows.append({
                "tail": tail,
                "pattern_class": registry_class,
                "event_count": event_count,
                "reason": reason,
                "warning_flags": warnings,
                "quarantine": "yes" if quarantine else "no",
                "recommended_action": "block_from_platform_master",
            })

    validated_fields = [
        "tail", "registry_class", "promotion_status", "quarantine", "registry_source", "reason",
        "warning_flags", "event_count", "events_csv_count", "ocr_new_tails_count", "image_count",
        "valid_n_number_format", "short_tail_edge", "owner_name", "city", "state", "manufacturer",
        "model", "mfr_mdl_code", "status_code", "cert_issue_date", "last_action_date",
        "deregistered_date", "first_source",
    ]
    platform_fields = [
        "tail", "platform_status", "registry_class", "event_count", "owner_name", "city", "state",
        "manufacturer", "model", "mfr_mdl_code", "warning_flags", "validation_reason", "source",
    ]
    fp_fields = [
        "tail", "pattern_class", "event_count", "reason", "warning_flags", "quarantine", "recommended_action",
    ]

    write_csv(out_dir / "registry_validated_tails.csv", validated_fields, validated_rows)
    write_csv(out_dir / "platform_master_patch.csv", platform_fields, platform_rows)
    write_csv(out_dir / "ocr_false_positive_patterns.csv", fp_fields, fp_rows)

    class_counts = Counter(str(r["registry_class"]) for r in validated_rows)
    promotion_counts = Counter(str(r["promotion_status"]) for r in validated_rows)
    quarantine_count = sum(1 for r in validated_rows if r["quarantine"] == "yes")

    summary = {
        "status": "completed",
        "inputs": {
            "ocr_new_tails": str(ocr_new_tails),
            "events": str(events_csv),
            "master": str(master_path),
            "dereg": str(dereg_path),
            "reserved": str(reserved_path),
            "acftref": str(acftref_path),
        },
        "outputs": {
            "registry_validated_tails": str(out_dir / "registry_validated_tails.csv"),
            "platform_master_patch": str(out_dir / "platform_master_patch.csv"),
            "ocr_false_positive_patterns": str(out_dir / "ocr_false_positive_patterns.csv"),
            "validation_summary": str(out_dir / "validation_summary.json"),
        },
        "candidate_tails": len(candidates),
        "faa_rows": {
            "master": len(master),
            "dereg": len(dereg),
            "reserved": len(reserved),
            "acftref": len(acftref),
        },
        "registry_class_counts": dict(sorted(class_counts.items())),
        "promotion_counts": dict(sorted(promotion_counts.items())),
        "quarantine_count": quarantine_count,
        "forced_quarantine": ["N253TH"],
        "p_route_event_join_gate": "run only after reviewing platform_master_patch.csv and accepting non-quarantined promote rows",
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "validation_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
