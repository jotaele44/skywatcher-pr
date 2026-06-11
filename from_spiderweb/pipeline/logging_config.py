"""Central logging configuration with an optional JSON formatter (T10-80).

Runners historically used bare ``print()``; this module gives them one shared,
structured logging setup. Call :func:`configure_logging` once at process start
(e.g. from ``run_all.py``) and use :func:`get_logger` everywhere else.

The JSON formatter emits one object per line — ``{"ts","level","logger","msg"}``
plus any ``extra=`` fields — so logs are greppable and machine-parseable in CI
and aggregators without changing call sites.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any, Dict

# Reserved LogRecord attributes we never copy into the JSON "extra" bag.
_RESERVED = frozenset(vars(logging.makeLogRecord({})))


class JsonFormatter(logging.Formatter):
    """Render a LogRecord as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # Copy any user-supplied extra=... fields.
        for key, val in record.__dict__.items():
            if key not in _RESERVED and key not in payload:
                payload[key] = val
        return json.dumps(payload, default=str, sort_keys=True)


def configure_logging(level: int = logging.INFO, *, json_format: bool = False) -> None:
    """Install a single stderr handler on the root logger (idempotent).

    Args:
        level: root log level (e.g. ``logging.DEBUG``).
        json_format: emit JSON lines when True, else a concise text format.
    """
    root = logging.getLogger()
    root.setLevel(level)
    # Replace any handlers we previously installed so repeat calls don't stack.
    for h in list(root.handlers):
        if getattr(h, "_spiderweb_managed", False):
            root.removeHandler(h)

    handler = logging.StreamHandler(sys.stderr)
    handler._spiderweb_managed = True  # type: ignore[attr-defined]
    if json_format:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%SZ",
            )
        )
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger (thin wrapper over ``logging.getLogger``)."""
    return logging.getLogger(name)
