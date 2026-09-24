"""Append-only contradiction tracking for Space-Track evidence."""

from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from .control_plane import logical_json_sha256
from .models import CertificationState, ContradictionRecord


class ContradictionRegister:
    def __init__(self) -> None:
        self._records: dict[str, ContradictionRecord] = {}

    @staticmethod
    def _build(
        category: str,
        key: str,
        observations: Iterable[str],
        *,
        state: CertificationState = CertificationState.UNRESOLVED,
    ) -> ContradictionRecord:
        ordered = tuple(sorted(set(str(value) for value in observations)))
        contradiction_id = logical_json_sha256(
            {"category": category, "key": key, "observations": ordered}
        )[:24]
        return ContradictionRecord(
            contradiction_id=contradiction_id,
            category=category,
            key=key,
            observations=ordered,
            state=state,
        )

    def add(
        self,
        category: str,
        key: str,
        observations: Iterable[str],
        *,
        state: CertificationState = CertificationState.UNRESOLVED,
    ) -> ContradictionRecord:
        record = self._build(category, key, observations, state=state)
        existing = self._records.get(record.contradiction_id)
        if existing is not None and existing != record:
            raise RuntimeError("contradiction identifier collision")
        self._records[record.contradiction_id] = record
        return record

    def ingest(self, record: ContradictionRecord) -> None:
        existing = self._records.get(record.contradiction_id)
        if existing is not None and existing != record:
            raise RuntimeError("contradiction identifier collision")
        self._records[record.contradiction_id] = record

    def supersede(self, contradiction_id: str, *, by_id: str) -> ContradictionRecord:
        if contradiction_id not in self._records:
            raise KeyError(contradiction_id)
        if by_id not in self._records:
            raise KeyError(by_id)
        updated = replace(
            self._records[contradiction_id],
            state=CertificationState.SUPERSEDED,
            superseded_by=by_id,
        )
        self._records[contradiction_id] = updated
        return updated

    def unresolved(self) -> tuple[ContradictionRecord, ...]:
        return tuple(
            record
            for record in self.all()
            if record.state is CertificationState.UNRESOLVED
        )

    def all(self) -> tuple[ContradictionRecord, ...]:
        return tuple(self._records[key] for key in sorted(self._records))
