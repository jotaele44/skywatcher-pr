"""GATIM CSV normalizer.

Normalizes candidate CSV exports into a stable review-ledger schema.
This module is intentionally read-only with respect to source files.
"""
from __future__ import annotations

import csv
import re
from dataclasses import asdict, dataclass
from hashlib import sha1
from pathlib import Path
from typing import Iterable, Optional

COORD_RE = re.compile(r"(?<!\d)([-+]?\d{1,2}\.\d+)[,\s]+([-+]?\d{1,3}\.\d+)(?!\d)")
DMS_RE = re.compile(r"(\d{1,3})°(\d{1,2})['’](\d{1,2}(?:\.\d+)?)?\"?\s*([NSEW])", re.I)

SCHEMA = [
    "gatim_id",
    "source_file",
    "source_dataset",
    "source_row",
    "title",
    "note",
    "url",
    "tags",
    "comment",
    "lat",
    "lon",
    "coord_status",
    "dedupe_cluster_id",
    "dedupe_cluster_size",
    "class_primary",
    "evidence_tier",
    "visual_features",
    "grid_id",
    "satim_link_status",
    "review_priority",
    "confidence",
    "normalization_notes",
]


@dataclass
class GATIMRow:
    gatim_id: str
    source_file: str
    source_dataset: str
    source_row: int
    title: str
    note: str
    url: str
    tags: str
    comment: str
    lat: str = ""
    lon: str = ""
    coord_status: str = "missing"
    dedupe_cluster_id: str = ""
    dedupe_cluster_size: str = ""
    class_primary: str = ""
    evidence_tier: str = ""
    visual_features: str = ""
    grid_id: str = ""
    satim_link_status: str = "none"
    review_priority: str = ""
    confidence: str = ""
    normalization_notes: str = ""

    def to_dict(self) -> dict[str, str]:
        data = asdict(self)
        return {key: str(data.get(key, "")) for key in SCHEMA}


def dataset_name(path: Path) -> str:
    return path.stem.replace("’", "'").replace("What's Here_", "WHATS_HERE").upper().replace(" ", "_")


def _dms_to_decimal(text: str) -> Optional[tuple[float, float]]:
    parts = list(DMS_RE.finditer(text or ""))
    if len(parts) < 2:
        return None
    values = []
    for match in parts[:2]:
        deg = float(match.group(1))
        minutes = float(match.group(2))
        seconds = float(match.group(3) or 0)
        hemi = match.group(4).upper()
        value = deg + minutes / 60 + seconds / 3600
        if hemi in {"S", "W"}:
            value *= -1
        values.append(value)
    return values[0], values[1]


def extract_coords(*texts: str) -> tuple[str, str, str, str]:
    joined = " ".join(text or "" for text in texts)
    for text in texts:
        match = COORD_RE.search(text or "")
        if match:
            return f"{float(match.group(1)):.7f}", f"{float(match.group(2)):.7f}", "direct", "decimal coordinate extracted"
    dms = _dms_to_decimal(joined)
    if dms:
        return f"{dms[0]:.7f}", f"{dms[1]:.7f}", "direct", "DMS coordinate extracted"
    if "google.com/maps/place" in joined or "maps.app.goo.gl" in joined:
        return "", "", "needs_geocode", "place URL lacks embedded coordinate"
    return "", "", "missing", "no coordinate found"


def stable_id(source_file: str, row_num: int, title: str, url: str) -> str:
    raw = f"{source_file}|{row_num}|{title}|{url}".encode("utf-8")
    return "GATIM_" + sha1(raw).hexdigest()[:10].upper()


def normalize_csv(path: str | Path) -> list[GATIMRow]:
    csv_path = Path(path)
    rows: list[GATIMRow] = []
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for idx, row in enumerate(reader, start=2):
            title = (row.get("Title") or "").strip()
            note = (row.get("Note") or "").strip()
            url = (row.get("URL") or "").strip()
            tags = (row.get("Tags") or "").strip()
            comment = (row.get("Comment") or "").strip()
            if not any([title, note, url, tags, comment]):
                continue
            lat, lon, status, notes = extract_coords(title, note, url, tags, comment)
            rows.append(
                GATIMRow(
                    gatim_id=stable_id(csv_path.name, idx, title, url),
                    source_file=csv_path.name,
                    source_dataset=dataset_name(csv_path),
                    source_row=idx,
                    title=title,
                    note=note,
                    url=url,
                    tags=tags,
                    comment=comment,
                    lat=lat,
                    lon=lon,
                    coord_status=status,
                    normalization_notes=notes,
                )
            )
    return rows


def normalize_many(paths: Iterable[str | Path]) -> list[GATIMRow]:
    out: list[GATIMRow] = []
    for path in paths:
        out.extend(normalize_csv(path))
    return out


def write_ledger(rows: Iterable[GATIMRow], output_path: str | Path) -> None:
    with Path(output_path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SCHEMA)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_dict())
