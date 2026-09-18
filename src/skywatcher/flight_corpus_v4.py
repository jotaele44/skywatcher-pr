"""Read-only query helpers for a validated Flight Corpus V4 import directory."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


class FlightCorpusV4:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.manifest = json.loads((self.root / "import_manifest.json").read_text(encoding="utf-8"))

    def _dataset_path(self, role: str) -> Path:
        matches = [row for row in self.manifest["datasets"] if row["role"] == role]
        if len(matches) != 1:
            raise ValueError(f"expected exactly one dataset for role {role}, got {len(matches)}")
        return self.root / matches[0]["path"]

    @staticmethod
    def _rows(path: Path) -> list[dict[str, str]]:
        with path.open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))

    def route_family_monthly(self, family_id: str | None = None) -> list[dict[str, str]]:
        rows = self._rows(self._dataset_path("TEMPORAL_RECURRENCE"))
        if family_id is None:
            return rows
        return [row for row in rows if row.get("consensus_family_id") == str(family_id)]

    def candidate_events(self, aircraft: str | None = None) -> list[dict[str, str]]:
        rows = self._rows(self._dataset_path("CANDIDATE_EVENTS"))
        if aircraft is None:
            return rows
        return [row for row in rows if row.get("folder") == aircraft]

    def raw_lineage_geojson(self) -> dict[str, Any]:
        return json.loads(self._dataset_path("RAW_LINEAGE_GEOMETRY").read_text(encoding="utf-8"))
