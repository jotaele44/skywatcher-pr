"""Schema checks for SATIM route findings ledgers."""

from __future__ import annotations

from dataclasses import dataclass

from .loaders import Ledger


class SchemaError(ValueError):
    """Raised when a ledger does not satisfy the required column contract."""


@dataclass(frozen=True)
class LedgerSchema:
    """Minimal column contract for one ledger."""

    filename: str
    required_columns: tuple[str, ...]


LEDGER_SCHEMAS: dict[str, LedgerSchema] = {
    "SATIM_TRACK_LEDGER.csv": LedgerSchema(
        filename="SATIM_TRACK_LEDGER.csv",
        required_columns=("latitude", "longitude", "source", "verification_score", "provenance_level"),
    ),
    "SATIM_GRAPH_NODES.csv": LedgerSchema(
        filename="SATIM_GRAPH_NODES.csv",
        required_columns=("node_id", "node_type", "label", "confidence", "source"),
    ),
    "SATIM_GRAPH_EDGES.csv": LedgerSchema(
        filename="SATIM_GRAPH_EDGES.csv",
        required_columns=("source", "target", "edge_type", "weight", "provenance"),
    ),
    "SATIM_GIS_JOIN_LEDGER.csv": LedgerSchema(
        filename="SATIM_GIS_JOIN_LEDGER.csv",
        required_columns=("source", "latitude", "longitude", "gis_join_status", "gis_layer_count"),
    ),
    "SATIM_ERROR_LEDGER.csv": LedgerSchema(
        filename="SATIM_ERROR_LEDGER.csv",
        required_columns=("source", "stage", "error_type", "message"),
    ),
}

REQUIRED_FILENAMES: tuple[str, ...] = tuple(LEDGER_SCHEMAS)


def missing_columns(ledger: Ledger, schema: LedgerSchema) -> tuple[str, ...]:
    """Return missing columns for a loaded ledger."""

    present = set(ledger.fieldnames)
    return tuple(column for column in schema.required_columns if column not in present)


def validate_ledger(ledger: Ledger) -> None:
    """Validate one ledger against its required column schema."""

    schema = LEDGER_SCHEMAS.get(ledger.name)
    if schema is None:
        raise SchemaError(f"No schema registered for ledger: {ledger.name}")
    missing = missing_columns(ledger, schema)
    if missing:
        raise SchemaError(f"{ledger.name} missing required columns: {', '.join(missing)}")


def validate_ledgers(ledgers: dict[str, Ledger]) -> None:
    """Validate all required ledgers."""

    missing_files = [name for name in REQUIRED_FILENAMES if name not in ledgers]
    if missing_files:
        raise SchemaError(f"Missing required ledgers: {', '.join(missing_files)}")
    for name in REQUIRED_FILENAMES:
        validate_ledger(ledgers[name])
