"""Centralised logging configuration for GEO-PR-INT."""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path


_ROOT_LOGGER_NAME = "geo_pr_int"
_LOG_DIR = Path(__file__).resolve().parent.parent / "data" / "logs"


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the geo_pr_int root namespace."""
    return logging.getLogger(f"{_ROOT_LOGGER_NAME}.{name}")


def configure_logging(
    level: str = "INFO",
    log_to_file: bool = True,
    log_dir: Path | None = None,
) -> logging.Logger:
    """Configure the root geo_pr_int logger.

    Call once at process start (idempotent on repeat calls).

    Parameters
    ----------
    level      : log level name ("DEBUG", "INFO", "WARNING", "ERROR")
    log_to_file: whether to write a timestamped log file
    log_dir    : override default log directory

    Returns
    -------
    The root geo_pr_int Logger instance.
    """
    root = logging.getLogger(_ROOT_LOGGER_NAME)

    if root.handlers:
        return root  # already configured

    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(getattr(logging, level.upper(), logging.INFO))
    ch.setFormatter(fmt)
    root.addHandler(ch)

    # File handler
    if log_to_file:
        _dir = log_dir or _LOG_DIR
        _dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fh = logging.FileHandler(_dir / f"geo_pr_int_{ts}.log", encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        root.addHandler(fh)

    return root
