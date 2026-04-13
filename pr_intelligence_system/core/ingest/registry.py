import logging
from datetime import datetime

logger = logging.getLogger(__name__)

_registry: list = []


def register_loaded_file(filepath: str, fmt: str, record_count: int) -> None:
    """Register a successfully loaded file in the global ingestion registry."""
    entry = {
        'filepath':     filepath,
        'format':       fmt,
        'record_count': record_count,
        'loaded_at':    datetime.utcnow().isoformat(),
    }
    _registry.append(entry)
    logger.info(f"Registered: [{fmt.upper()}] {filepath} -> {record_count} records")


def get_registry() -> list:
    """Return a shallow copy of the current registry."""
    return list(_registry)


def clear_registry() -> None:
    """Clear all entries from the registry."""
    global _registry
    _registry = []


def print_registry_summary() -> None:
    """Print a human-readable summary of all registered files."""
    print(f"\n{'='*60}")
    print(f"INGESTION REGISTRY SUMMARY  ({len(_registry)} file(s) loaded)")
    print(f"{'='*60}")
    for entry in _registry:
        print(
            f"  [{entry['format'].upper():<8}] "
            f"{entry['record_count']:>6} records  "
            f"{entry['filepath']}"
        )
    print('=' * 60)
