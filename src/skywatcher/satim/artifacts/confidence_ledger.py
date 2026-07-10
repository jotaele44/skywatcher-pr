from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


class ConfidenceLedger:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _last_hash(self) -> str | None:
        if not self.path.exists():
            return None
        lines = [x for x in self.path.read_text(encoding="utf-8").splitlines() if x.strip()]
        return json.loads(lines[-1])["entry_hash"] if lines else None

    def append(self, entry: Mapping[str, Any]) -> dict[str, Any]:
        record = dict(entry)
        # ``previous_entry_hash`` matches satim_confidence_ledger_entry_v1: a
        # 64-char hex digest, or null for the genesis entry.
        record["previous_entry_hash"] = self._last_hash()
        canonical = json.dumps(record, sort_keys=True, separators=(",", ":"))
        record["entry_hash"] = hashlib.sha256(canonical.encode()).hexdigest()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
        return record

    def verify(self) -> bool:
        prev: str | None = None
        if not self.path.exists():
            return True
        for line in self.path.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            h = r.pop("entry_hash")
            if r.get("previous_entry_hash") != prev:
                return False
            calc = hashlib.sha256(
                json.dumps(r, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            if calc != h:
                return False
            prev = h
        return True
